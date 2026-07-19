# apply_bot

특정 일자·시간에 열리는 온라인 신청(예: 구민체육센터 수영 정기권)에
정확한 오픈 시각을 맞춰 자동으로 제출하는 범용 프레임워크입니다.

두 가지 제출 방식을 모두 지원하며, 사이트별로 다른 부분은 `config.yaml`
설정 파일로 분리되어 있습니다.

- **http 모드**: `requests`로 로그인/제출 요청을 직접 전송합니다. 가장 빠르지만
  브라우저 개발자도구로 실제 요청(URL, 파라미터)을 미리 파악해야 합니다.
- **browser 모드**: Playwright로 실제 크로미움 브라우저를 조작합니다. 느리지만
  JS 렌더링/캡차 등으로 http 모드가 어려운 사이트에도 적용 가능합니다.

## 사용 전 꼭 확인하세요

- 본인 명의로, 본인이 신청 자격이 있는 서비스에만 사용하세요.
- 대상 사이트의 이용약관에 자동화/매크로 사용을 금지하는 조항이 있는지 먼저
  확인하세요. 특히 **공연/공연예매 티켓팅은 매크로 사용이 법으로 금지**되어
  있습니다(공연법 개정, 암표 방지법). 관공서·체육시설 등 개인 신청 목적이라도
  해당 기관의 약관을 우선 확인하세요.
- 짧은 시간에 과도한 요청을 반복해 서버에 부담을 주지 않도록
  `retry.max_attempts` / `backoff_seconds`를 상식적인 범위로 설정하세요.

## 설치

```bash
cd apply_bot
pip install -r requirements.txt
playwright install chromium   # browser 모드를 쓸 경우에만 필요
cp config.example.yaml config.yaml
cp .env.example .env
```

`.env`에 로그인 아이디/비밀번호를 채우고, `config.yaml`을 대상 사이트에 맞게 수정합니다.

## 설정 방법: 대상 요청 파악하기

1. 크롬 개발자도구(F12) → Network 탭을 열고, 실제로 로그인 → 신청 폼 제출을
   수동으로 한 번 해봅니다.
2. 로그인 요청의 URL, 메서드, 폼 데이터(payload)를 확인해
   `http.login_url` / `http.login_fields`에 옮겨 적습니다.
3. 신청(제출) 요청도 동일하게 `http.submit_url` / `http.submit_fields`에 옮깁니다.
4. 성공 시 응답에 공통으로 나타나는 상태 코드나 문구를
   `http.success_indicator`에 지정합니다.
5. 요청에 매번 바뀌는 토큰(CSRF 등)이 포함되어 있다면 http 모드로는 재현이
   어려울 수 있습니다 — 이 경우 browser 모드를 사용하세요.

browser 모드는 로그인/신청 폼의 CSS 선택자만 알면 되므로 설정이 더 간단합니다
(`browser.id_selector`, `browser.submit_button_selector` 등).

## 실행

```bash
python -m apply_bot.runner config.yaml
# 또는 config의 mode를 무시하고 강제 지정
python -m apply_bot.runner config.yaml --mode browser
```

동작 순서:

1. `time_sync.reference_url`에 여러 번 요청을 보내 로컬 PC 시계와 대상 서버
   시계의 오차를 측정합니다(공공기관 PC 시계가 몇 초씩 어긋나 있는 경우가 흔합니다).
2. 로그인을 미리 완료합니다.
3. 오픈 시각 `prewarm_lead_seconds`초 전에 연결을 미리 맺어두거나(http) 신청
   폼 페이지로 미리 이동해둡니다(browser).
4. 오픈 시각 정각에 밀리초 단위로 맞춰 제출 요청/클릭을 실행합니다.
5. 실패하면(정원 초과, 일시적 오류 등) `retry` 설정에 따라 짧은 간격으로
   재시도합니다.

모든 시도는 타임스탬프와 함께 로그로 출력되어, 실패 시 원인(상태 코드,
응답 내용)을 바로 확인할 수 있습니다.

## 사이트 전용 스크립트: 광교복합체육센터(sgsc.co.kr)

이 사이트는 강좌 목록을 AJAX로 불러오고, 신청 오픈 전에는 강좌 고유 코드
자체가 존재하지 않으며, 신청서에 수강기간·가족구성원 선택과 캡차가 관련될
수 있는 등 범용 `runner.py`로 다루기엔 흐름이 특수합니다. 그래서 이 사이트는
전용 스크립트로 처리합니다.

```bash
cp config.sgsc.example.yaml config.yaml   # target.open_at 등을 수정
python -m apply_bot.sgsc_apply config.yaml
```

동작 순서:

1. 화면이 보이는(headed) 브라우저로 로그인
2. 오픈 시각까지 대기
3. 오픈 시각부터 `GET /rest/lecture/list`를 짧은 간격으로 폴링(HTTP라서
   브라우저 새로고침보다 훨씬 빠름) — 강좌가 목록에 나타나는 즉시 감지
4. 해당 강좌의 신청서 페이지로 이동, 수강기간·신청자를 첫 번째 가능한
   옵션으로 자동 선택
5. **캡차가 나타나면 자동화를 멈추고** 사람이 직접 입력·제출하도록
   브라우저 창을 그대로 열어둠. 캡차가 없으면 확인창을 자동으로 수락하고
   제출까지 완료.

**미검증 주의**: 이 스크립트는 실제 사이트에 대해 end-to-end로 테스트되지
않았습니다(개발 환경의 네트워크 정책상 sgsc.co.kr 접속이 차단되어 있어,
로그인 폼과 목록 API 응답을 코드로만 보고 구현했습니다). 실제 신청 당일
전에 반드시 **현재 접수중인 다른 강좌(수영이 아니어도 무방)로 리허설**해서
셀렉터와 흐름이 실제 페이지와 맞는지 확인하세요.
