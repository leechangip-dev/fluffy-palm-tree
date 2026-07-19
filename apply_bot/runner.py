"""신청 자동화 실행기: 시계 동기화 -> 사전 준비 -> 정시 제출 -> 실패 시 재시도."""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from . import timing
from .config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _target_epoch(cfg: dict) -> float:
    target_cfg = cfg["target"]
    tz = ZoneInfo(target_cfg.get("timezone", "Asia/Seoul"))
    dt = datetime.strptime(target_cfg["open_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    return dt.timestamp()


def _sync_offset(cfg: dict) -> timing.ClockOffset:
    ts_cfg = cfg.get("time_sync", {})
    offset = timing.measure_server_offset(
        ts_cfg["reference_url"], samples=ts_cfg.get("samples", 7)
    )
    logger.info(
        "서버-로컬 시계 오차: %.3f초 (기준 RTT %.3f초)",
        offset.offset_seconds,
        offset.rtt_seconds,
    )
    return offset


def _run_retry_loop(cfg: dict, attempt_fn) -> bool:
    """attempt_fn() -> bool(성공 여부)을 성공하거나 재시도 소진까지 반복 호출한다."""
    retry_cfg = cfg.get("retry", {})
    max_attempts = retry_cfg.get("max_attempts", 10)
    window = retry_cfg.get("window_seconds", 10)
    backoff = retry_cfg.get("backoff_seconds", 0.3)

    deadline = time.time() + window
    for attempt in range(1, max_attempts + 1):
        ok = attempt_fn(attempt)
        if ok:
            logger.info("신청 성공! (시도 %d회)", attempt)
            return True
        if time.time() >= deadline:
            break
        time.sleep(backoff)
    logger.error("신청 실패: 재시도 %d회 소진", max_attempts)
    return False


def run_http(cfg: dict) -> bool:
    from .http_submitter import HttpApplicationSubmitter

    submitter = HttpApplicationSubmitter(cfg)
    submitter.login()

    offset = _sync_offset(cfg)
    target_epoch = _target_epoch(cfg)
    lead = cfg.get("prewarm_lead_seconds", 2.0)

    timing.wait_until(target_epoch - lead, offset.offset_seconds)
    submitter.prewarm()

    timing.wait_until(target_epoch, offset.offset_seconds)

    def attempt(n: int) -> bool:
        t0 = time.perf_counter()
        response = submitter.submit()
        elapsed = time.perf_counter() - t0
        ok = submitter.is_success(response)
        logger.info(
            "시도 %d: status=%s elapsed=%.3fs 성공=%s", n, response.status_code, elapsed, ok
        )
        return ok

    return _run_retry_loop(cfg, attempt)


def run_browser(cfg: dict) -> bool:
    from .browser_submitter import BrowserApplicationSubmitter

    headless = cfg.get("browser", {}).get("headless", True)
    with BrowserApplicationSubmitter(cfg, headless=headless) as submitter:
        submitter.login()

        offset = _sync_offset(cfg)
        target_epoch = _target_epoch(cfg)
        lead = cfg.get("prewarm_lead_seconds", 2.0)

        timing.wait_until(target_epoch - lead, offset.offset_seconds)
        submitter.prepare()

        timing.wait_until(target_epoch, offset.offset_seconds)

        def attempt(n: int) -> bool:
            t0 = time.perf_counter()
            submitter.submit()
            elapsed = time.perf_counter() - t0
            ok = submitter.is_success()
            logger.info("시도 %d: elapsed=%.3fs 성공=%s", n, elapsed, ok)
            return ok

        return _run_retry_loop(cfg, attempt)


def main() -> None:
    parser = argparse.ArgumentParser(description="특정 일시에 오픈되는 온라인 신청 자동화")
    parser.add_argument("config", help="YAML 설정 파일 경로")
    parser.add_argument("--mode", choices=["http", "browser"], help="config.yaml의 mode 값을 덮어씀")
    parser.add_argument("--env-file", default=".env", help="환경변수(.env) 파일 경로")
    args = parser.parse_args()

    load_dotenv(args.env_file)
    cfg = load_config(args.config)
    mode = args.mode or cfg.get("mode", "http")

    if mode == "http":
        success = run_http(cfg)
    elif mode == "browser":
        success = run_browser(cfg)
    else:
        raise ValueError(f"알 수 없는 mode: {mode}")

    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
