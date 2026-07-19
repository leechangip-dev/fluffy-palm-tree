"""Playwright로 실제 브라우저를 조작해 로그인/제출하는 방식.

신청 폼이 JS로 렌더링되거나, 캡차·동적 토큰 때문에 순수 HTTP 요청으로는
재현이 어려운 사이트에 사용한다. HTTP 방식보다 느리지만 훨씬 범용적이다.
"""
from __future__ import annotations

import logging

from playwright.sync_api import Page, sync_playwright

logger = logging.getLogger(__name__)


class BrowserApplicationSubmitter:
    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._page: Page | None = None

    def __enter__(self) -> "BrowserApplicationSubmitter":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        return self

    def __exit__(self, *exc) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    @property
    def page(self) -> Page:
        assert self._page is not None, "with 블록 안에서만 사용하세요."
        return self._page

    def login(self) -> None:
        b = self.config["browser"]
        if not b.get("login_url"):
            return
        self.page.goto(b["login_url"], wait_until="domcontentloaded")
        self.page.fill(b["id_selector"], b["credentials_id"])
        self.page.fill(b["pw_selector"], b["credentials_pw"])
        self.page.click(b["login_button_selector"])
        self.page.wait_for_load_state("networkidle")
        logger.info("로그인 완료")

    def prepare(self) -> None:
        """신청 폼 페이지로 미리 이동해 대기한다(제출 버튼 클릭만 남겨둔 상태)."""
        b = self.config["browser"]
        self.page.goto(b["form_url"], wait_until="domcontentloaded")

    def submit(self) -> None:
        b = self.config["browser"]
        if b.get("reload_before_submit"):
            self.page.reload(wait_until="domcontentloaded")
        self.page.click(b["submit_button_selector"])

    def is_success(self) -> bool:
        b = self.config["browser"]
        selector = b.get("success_selector")
        if selector:
            return self.page.locator(selector).count() > 0
        text = b.get("success_text")
        if text:
            return text in self.page.content()
        return True
