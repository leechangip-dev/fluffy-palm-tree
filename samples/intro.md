# 번역 자동화 도구 소개

이 도구는 Claude API를 활용하여 다양한 문서를 여러 언어로 자동 번역합니다.

## 주요 기능

- **다국어 지원**: 한국어, 영어, 일본어, 중국어, 스페인어 등 10개 언어 지원
- **파일 형식**: Markdown, 텍스트, JSON 파일 번역
- **일괄 번역**: 하나의 파일을 여러 언어로 동시에 번역
- **코드 보존**: 코드 블록 내용은 번역하지 않고 그대로 유지

## 사용 예시

```bash
# 단일 언어 번역
python src/cli.py file samples/intro.md -t en

# 일괄 번역
python src/cli.py file samples/intro.md -t en,ja,zh

# 텍스트 직접 번역
python src/cli.py text "안녕하세요" -t en
```

## 참고 사항

번역 품질을 높이려면 `-c` 옵션으로 문서의 맥락 정보를 추가로 제공할 수 있습니다.

## GitHub Actions 자동 번역

이 파일을 수정하고 push하면 GitHub Actions가 자동으로 영어, 일본어, 중국어 번역 파일을 생성합니다.

## 지원 파일 형식

Markdown, 텍스트, JSON, YAML 형식을 모두 지원합니다.

## 자동화 효과

반복 번역 작업을 자동화하면 시간과 비용을 절감할 수 있습니다. GitHub Actions와 연동 시 파일 수정 즉시 번역이 실행됩니다.
