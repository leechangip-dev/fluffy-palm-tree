"""광교복합체육센터(sgsc.co.kr) 전용 강좌 목록 폴링 유틸리티.

강좌 목록 페이지(fmcs/12)는 자바스크립트가 /rest/lecture/list를 GET으로
호출해 JSON을 받아 화면을 그린다. 아직 오픈되지 않은 강좌는 고유
comcd/classcd가 없어 이 목록에 나타나지 않으므로, 오픈 시각 이후 이
엔드포인트를 짧은 간격으로 폴링해 원하는 강좌가 나타나는 즉시 식별 정보를
얻어낸다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class LectureCourse:
    comcd: str
    class_cd: str
    class_nm: str
    status: str
    raw: dict


def fetch_lecture_list(
    session: requests.Session,
    base_url: str,
    company_code: str,
    category_cd: str,
    category_level: int = 2,
    search_type: str = "%",
    page: int = 1,
    page_size: int = 50,
) -> list:
    resp = session.get(
        f"{base_url}/rest/lecture/list",
        params={
            "company_code": company_code,
            "search_type": search_type,
            "category_cd": category_cd,
            "category_level": category_level,
            "page": page,
            "page_size": page_size,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        if data.get("error"):
            raise RuntimeError(f"강좌 목록 조회 실패: {data.get('message')}")
        return data.get("result_values", [])
    return data


def poll_for_course(
    session: requests.Session,
    base_url: str,
    company_code: str,
    category_cd: str,
    name_contains: str | None = None,
    category_level: int = 2,
    timeout: float = 20.0,
    poll_interval: float = 0.4,
) -> LectureCourse:
    """상태가 'R'(접수중)인 강좌가 나타날 때까지 폴링한다."""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            courses = fetch_lecture_list(
                session, base_url, company_code, category_cd, category_level
            )
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            logger.warning("목록 조회 실패(재시도): %s", exc)
            time.sleep(poll_interval)
            continue

        for c in courses:
            if c.get("status") != "R":
                continue
            if name_contains and name_contains not in (c.get("class_nm") or ""):
                continue
            logger.info("강좌 발견(시도 %d회): %s", attempt, c.get("class_nm"))
            return LectureCourse(
                comcd=c["comcd"],
                class_cd=c["class_cd"],
                class_nm=c.get("class_nm", ""),
                status=c["status"],
                raw=c,
            )
        time.sleep(poll_interval)

    raise TimeoutError(f"{timeout}초 내에 조건에 맞는 강좌를 찾지 못했습니다.")
