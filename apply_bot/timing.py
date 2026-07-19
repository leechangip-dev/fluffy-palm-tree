"""목표 시각까지 정밀하게 대기하고, 서버 시간과 로컬 시계의 오차를 보정하는 유틸리티."""
from __future__ import annotations

import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import requests


@dataclass
class ClockOffset:
    offset_seconds: float
    rtt_seconds: float


def measure_server_offset(url: str, samples: int = 7, timeout: float = 5.0) -> ClockOffset:
    """HTTP Date 헤더와 로컬 시각을 비교해 서버 대비 로컬 시계 오차(초)를 추정한다.

    Date 헤더는 초 단위라 NTP만큼 정밀하진 않지만, 여러 번 측정해 왕복시간(RTT)이
    가장 짧은 샘플을 채택하면 네트워크 지연에 의한 오차를 크게 줄일 수 있다.
    """
    best: ClockOffset | None = None
    for _ in range(samples):
        t0 = time.time()
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException:
            continue
        t1 = time.time()
        rtt = t1 - t0
        date_header = resp.headers.get("Date")
        if not date_header:
            continue
        try:
            server_dt = parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            continue
        local_mid = t0 + rtt / 2
        offset = server_dt.timestamp() - local_mid
        if best is None or rtt < best.rtt_seconds:
            best = ClockOffset(offset_seconds=offset, rtt_seconds=rtt)
    return best if best is not None else ClockOffset(offset_seconds=0.0, rtt_seconds=0.0)


def wait_until(target_epoch: float, offset_seconds: float = 0.0, spin_threshold: float = 0.02) -> None:
    """target_epoch(서버 기준, UTC epoch초)까지 대기한다.

    offset_seconds는 measure_server_offset()의 결과로 로컬 시계를 서버 시계에 맞추는 데 쓰인다.
    마지막 spin_threshold(기본 20ms) 구간은 sleep 오차를 피하기 위해 바쁜 대기(spin)로 처리한다.
    """
    local_target = target_epoch - offset_seconds
    while True:
        remaining = local_target - time.time()
        if remaining <= 0:
            return
        if remaining > 1.0:
            time.sleep(min(remaining - 0.5, 1.0))
        elif remaining > spin_threshold:
            time.sleep(remaining - spin_threshold)
        else:
            while time.time() < local_target:
                pass
            return
