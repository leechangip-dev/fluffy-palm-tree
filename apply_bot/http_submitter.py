"""requests 세션으로 로그인 후 신청 폼을 직접 POST하는 제출기.

대상 사이트가 순수 서버 렌더링(폼 action이 명확한 API/URL)일 때 가장 빠르다.
브라우저 개발자도구 Network 탭에서 로그인·신청 요청의 URL/메서드/파라미터를
확인해 config.yaml의 http 섹션에 그대로 옮겨 적으면 된다.
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class HttpApplicationSubmitter:
    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            config.get("headers", {"User-Agent": "Mozilla/5.0"})
        )

    def login(self) -> None:
        http_cfg = self.config["http"]
        login_url = http_cfg.get("login_url")
        if not login_url:
            return
        method = http_cfg.get("login_method", "POST").upper()
        fields = http_cfg.get("login_fields", {})
        resp = self.session.request(method, login_url, data=fields, timeout=10)
        resp.raise_for_status()
        logger.info("로그인 요청 완료: status=%s", resp.status_code)

    def prewarm(self) -> None:
        """제출 URL로 가벼운 요청을 미리 보내 DNS/TCP/TLS 핸드셰이크를 선점한다."""
        submit_url = self.config["http"]["submit_url"]
        try:
            self.session.head(submit_url, timeout=5)
        except requests.RequestException as exc:
            logger.warning("사전 연결(prewarm) 실패, 무시하고 계속 진행: %s", exc)

    def submit(self) -> requests.Response:
        http_cfg = self.config["http"]
        method = http_cfg.get("submit_method", "POST").upper()
        url = http_cfg["submit_url"]
        fields = http_cfg.get("submit_fields", {})
        return self.session.request(method, url, data=fields, timeout=10)

    def is_success(self, response: requests.Response) -> bool:
        indicator = self.config["http"].get("success_indicator", {})
        expected_status = indicator.get("status_code")
        if expected_status is not None and response.status_code != expected_status:
            return False
        needle = indicator.get("body_contains")
        if needle and needle not in response.text:
            return False
        return True
