"""광교복합체육센터(sgsc.co.kr) 수강신청 전용 실행 스크립트.

강좌 목록 폴링은 HTTP로(빠름), 실제 신청서 작성은 Playwright 브라우저(headed)로
처리한다. 신청서에 캡차가 나타나면 자동화를 멈추고 사람이 마무리하도록 만들었다
(캡차를 자동으로 우회하지 않는다 — 정상적인 봇 방지 장치이므로).

신청서 페이지(#form_lecture_reg, itemcd/memno 라디오, 제출 버튼 셀렉터)는 실제
페이지의 view-source로 검증되었다. 다만 itemcd/memno가 전부 비활성화된 상태로만
확인했으므로(관내접수기간 제한), 실제로 선택 가능한 상태에서의 제출 자체는
아직 사람이 직접 지켜보며 확인한 적이 없다.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from . import timing
from .config import load_config
from .sgsc_lecture import poll_for_course

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


def _cookies_from_browser(context) -> dict:
    return {c["name"]: c["value"] for c in context.cookies()}


def _select_first_enabled_radio(page, name: str, timeout: int = 10000):
    """지정된 name의 라디오 중 비활성화되지 않은 첫 번째 것을 선택한다.

    전부 비활성화된 상태라면(예: 관내접수기간 제한, 마감 등) 그 title 속성에
    담긴 사유를 로그로 남기고 예외를 던진다 — 단순 타임아웃보다 원인 파악이
    쉽도록.
    """
    enabled = page.locator(f'#form_lecture_reg input[name="{name}"]:not([disabled])').first
    try:
        enabled.wait_for(state="visible", timeout=timeout)
    except PlaywrightTimeoutError:
        disabled = page.locator(f'#form_lecture_reg input[name="{name}"][disabled]').first
        if disabled.count() > 0:
            reason = disabled.get_attribute("title") or "사유 미상"
            logger.error("'%s' 항목 중 선택 가능한 것이 없습니다 (사유: %s)", name, reason)
        else:
            logger.error("'%s' 항목을 찾지 못했습니다.", name)
        raise
    enabled.check()
    return enabled


def run(cfg: dict, dry_run: bool = False) -> None:
    sgsc_cfg = cfg["sgsc"]
    base_url = sgsc_cfg["base_url"]

    offset = timing.measure_server_offset(
        cfg.get("time_sync", {}).get("reference_url", base_url + "/"),
        samples=cfg.get("time_sync", {}).get("samples", 7),
    )
    logger.info("서버-로컬 시계 오차: %.3f초", offset.offset_seconds)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto(f"{base_url}/fmcs/26", wait_until="domcontentloaded")
        page.fill("#user_id", sgsc_cfg["user_id"])
        page.fill("#user_password", sgsc_cfg["user_password"])
        page.click('#memberLoginForm button[type="submit"]')
        page.wait_for_load_state("networkidle")
        logger.info("로그인 완료")

        # 목록 폴링은 requests가 브라우저 리로드보다 훨씬 빠르므로,
        # 로그인된 브라우저의 쿠키를 그대로 requests 세션에 옮겨서 사용한다.
        session = requests.Session()
        session.cookies.update(_cookies_from_browser(page.context))

        target_epoch = _target_epoch(cfg)
        lead = cfg.get("prewarm_lead_seconds", 2.0)
        timing.wait_until(target_epoch - lead, offset.offset_seconds)
        logger.info("오픈 %.1f초 전: 대기 중", lead)

        timing.wait_until(target_epoch, offset.offset_seconds)
        logger.info("오픈 시각 도달, 강좌 목록 폴링 시작")

        course = poll_for_course(
            session,
            base_url,
            company_code=sgsc_cfg["center"],
            category_cd=sgsc_cfg["class_category"],
            name_contains=sgsc_cfg.get("name_contains") or None,
            timeout=sgsc_cfg.get("poll_timeout_seconds", 20),
            poll_interval=sgsc_cfg.get("poll_interval_seconds", 0.4),
        )
        logger.info(
            "강좌 확보: %s (comcd=%s, classcd=%s)",
            course.class_nm, course.comcd, course.class_cd,
        )

        read_url = (
            f"{base_url}/fmcs/12?center={sgsc_cfg['center']}&action=read&page=1"
            f"&event={sgsc_cfg['event']}&class={sgsc_cfg['class_category']}"
            f"&comcd={course.comcd}&classcd={course.class_cd}&type=R"
        )
        page.goto(read_url, wait_until="domcontentloaded")

        _select_first_enabled_radio(page, "itemcd")
        logger.info("수강기간 선택 완료")

        _select_first_enabled_radio(page, "memno")
        logger.info("신청자 선택 완료")

        captcha = page.locator('#form_lecture_reg input[name="captcha"]')
        has_captcha = captcha.count() > 0 and captcha.first.is_visible()

        if dry_run:
            logger.info(
                "[dry-run] 여기서 멈춥니다. 실제 제출 버튼은 누르지 않았습니다. "
                "브라우저 창에서 폼 상태(선택된 수강기간/신청자, 캡차 유무)를 "
                "직접 확인해보세요."
            )
            page.pause()
            return

        if has_captcha:
            logger.warning(
                "캡차가 감지되었습니다. 자동으로 풀 수 없으니 브라우저 창에서 "
                "직접 입력한 뒤 신청 버튼을 눌러주세요. 스크립트는 여기서 멈춥니다."
            )
            page.pause()
            return

        page.once("dialog", lambda dialog: dialog.accept())
        submit_button = page.locator(
            '#form_lecture_reg button[type="submit"], #form_lecture_reg [type="submit"]'
        )
        submit_button.first.click()
        page.wait_for_load_state("networkidle")

        logger.info("제출 완료. 결과 페이지 URL: %s", page.url)
        logger.info("브라우저 창에서 신청 결과를 직접 확인하세요.")
        page.pause()


def main() -> None:
    parser = argparse.ArgumentParser(description="광교복합체육센터 수강신청 자동화")
    parser.add_argument("config", help="YAML 설정 파일 경로")
    parser.add_argument("--env-file", default=".env", help="환경변수(.env) 파일 경로")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="수강기간/신청자 선택까지만 하고 실제 제출 버튼은 누르지 않음(리허설용)",
    )
    parser.add_argument(
        "--open-at",
        help="target.open_at을 덮어씀 (형식: 'YYYY-MM-DD HH:MM:SS', config.yaml의 timezone 기준)",
    )
    parser.add_argument(
        "--name-contains",
        help="sgsc.name_contains를 덮어씀(강좌명 일부로 필터링). 빈 문자열이면 필터 없음",
    )
    args = parser.parse_args()

    load_dotenv(args.env_file)
    cfg = load_config(args.config)

    if args.open_at:
        cfg.setdefault("target", {})["open_at"] = args.open_at
    if args.name_contains is not None:
        cfg.setdefault("sgsc", {})["name_contains"] = args.name_contains

    run(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
