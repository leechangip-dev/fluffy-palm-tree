"""requests 세션으로 로그인 후 신청 폼을 직접 POST하는 제출기.

대상 사이트가 순수 서버 렌더링(폼 action이 명확한 API/URL)일 때 가장 빠르다.
브라우저 개발자도구 Network 탭에서 로그인·신청 요청의 URL/메서드/파라미터를
확인해 config.yaml의 http 섹션에 그대로 옮겨 적으면 된다.

많은 공공기관/체육시설 사이트(예: FMCS 계열 CMS)는 폼마다 CSRF 성격의 히든
필드(예: SecurityToken)를 새로 발급한다. `http.csrf_field`를 지정하면 로그인
전, 그리고 제출 직전에 해당 필드 값을 페이지에서 읽어와 자동으로 채워 넣는다.
"""
from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)


def _extract_hidden_field(html_text: str, field: str) -> str:
    """<input ... name="field" ... value="..." ...> 형태에서 value를 추출한다.

    속성 순서(name/value)에 상관없이 동작하도록 input 태그 전체를 먼저 찾은 뒤
    그 안에서 value를 검색한다.
    """
    input_match = re.search(
        rf'<input[^>]*name=["\']{re.escape(field)}["\'][^>]*>', html_text
    )
    if not input_match:
        raise ValueError(f"입력 필드 '{field}'를 페이지에서 찾을 수 없습니다.")
    value_match = re.search(r'value=["\']([^"\']*)["\']', input_match.group(0))
    return value_match.group(1) if value_match else ""


class HttpApplicationSubmitter:
    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            config.get("headers", {"User-Agent": "Mozilla/5.0"})
        )
        self._cached_submit_token: str | None = None

    def _fetch_token(self, url: str, field: str) -> str:
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        return _extract_hidden_field(resp.text, field)

    def login(self) -> None:
        http_cfg = self.config["http"]
        login_url = http_cfg.get("login_url")
        if not login_url:
            return
        fields = dict(http_cfg.get("login_fields", {}))
        csrf_field = http_cfg.get("csrf_field")
        if csrf_field:
            token_url = http_cfg.get("login_token_url", login_url)
            fields[csrf_field] = self._fetch_token(token_url, csrf_field)
        method = http_cfg.get("login_method", "POST").upper()
        resp = self.session.request(method, login_url, data=fields, timeout=10)
        resp.raise_for_status()
        logger.info("로그인 요청 완료: status=%s", resp.status_code)

    def prewarm(self) -> None:
        """제출 직전, 연결을 미리 맺고(가능하면) CSRF 토큰을 미리 확보해둔다."""
        http_cfg = self.config["http"]
        submit_url = http_cfg["submit_url"]
        csrf_field = http_cfg.get("csrf_field")
        try:
            if csrf_field:
                token_url = http_cfg.get("submit_token_url", submit_url)
                self._cached_submit_token = self._fetch_token(token_url, csrf_field)
                logger.info("제출용 토큰 사전 확보 완료")
            else:
                self.session.head(submit_url, timeout=5)
        except requests.RequestException as exc:
            logger.warning("사전 준비(prewarm) 실패, 무시하고 계속 진행: %s", exc)

    def submit(self) -> requests.Response:
        http_cfg = self.config["http"]
        fields = dict(http_cfg.get("submit_fields", {}))
        csrf_field = http_cfg.get("csrf_field")
        if csrf_field:
            if self._cached_submit_token is not None:
                fields[csrf_field] = self._cached_submit_token
                self._cached_submit_token = None  # 1회성으로 간주, 재시도 시 새로 발급받음
            else:
                token_url = http_cfg.get("submit_token_url", http_cfg["submit_url"])
                fields[csrf_field] = self._fetch_token(token_url, csrf_field)
        method = http_cfg.get("submit_method", "POST").upper()
        url = http_cfg["submit_url"]
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
