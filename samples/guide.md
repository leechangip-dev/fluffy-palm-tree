# 번역 도구 사용 가이드

이 가이드는 Claude API 기반 번역 자동화 도구의 사용 방법을 설명합니다.

## 시작하기

### 1. 환경 설정

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-api-key"
```

### 2. 기본 사용법

텍스트를 직접 번역하거나 파일 단위로 번역할 수 있습니다.

```bash
# 텍스트 번역
python src/cli.py text "번역할 내용" -t en

# 파일 번역
python src/cli.py file 파일경로 -t en

# 여러 언어로 동시 번역
python src/cli.py file 파일경로 -t en,ja,zh
```

## 지원 언어 목록

| 코드 | 언어 |
|------|------|
| ko | 한국어 |
| en | 영어 |
| ja | 일본어 |
| zh | 중국어 (간체) |
| zh-tw | 중국어 (번체) |
| es | 스페인어 |
| fr | 프랑스어 |
| de | 독일어 |
| pt | 포르투갈어 |
| vi | 베트남어 |

## 고급 기능

### 번역 캐시

동일한 텍스트를 반복 번역할 때 API 호출을 줄여 비용을 절감합니다.

```bash
# 캐시 비활성화
python src/cli.py --no-cache file 파일경로 -t en
```

### 언어 자동 감지

소스 언어를 지정하지 않으면 자동으로 감지합니다.

```bash
python src/cli.py detect 파일경로
```

### 번역 맥락 지정

`-c` 옵션으로 번역 품질을 높일 수 있습니다.

```bash
python src/cli.py file 파일경로 -t en -c "기술 문서, IT 소프트웨어 관련"
```

## GitHub Actions 자동화

`samples/` 폴더의 파일을 수정하고 push하면 자동으로 번역이 실행됩니다.

1. 소스 파일 수정
2. `git push`
3. GitHub Actions 자동 실행
4. 번역 파일 자동 생성 및 커밋
