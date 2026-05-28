# Introduction to Translation Automation Tool

This tool leverages the Claude API to automatically translate various documents into multiple languages.

## Key Features

- **Multilingual Support**: Supports 10 languages including Korean, English, Japanese, Chinese, and Spanish
- **File Formats**: Translates Markdown, text, and JSON files
- **Batch Translation**: Simultaneously translates a single file into multiple languages
- **Code Preservation**: Content inside code blocks is preserved as-is without translation

## Usage Examples

```bash
# 단일 언어 번역
python src/cli.py file samples/intro.md -t en

# 일괄 번역
python src/cli.py file samples/intro.md -t en,ja,zh

# 텍스트 직접 번역
python src/cli.py text "안녕하세요" -t en
```

## Notes

To improve translation quality, you can provide additional context information about the document using the `-c` option.