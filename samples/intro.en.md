# Introduction to Translation Automation Tool

This tool leverages the Claude API to automatically translate various documents into multiple languages.

## Key Features

- **Multilingual Support**: Supports 10 languages including Korean, English, Japanese, Chinese, and Spanish
- **File Formats**: Translates Markdown, text, and JSON files
- **Batch Translation**: Simultaneously translates a single file into multiple languages
- **Code Preservation**: Content inside code blocks is preserved as-is without translation

## Usage Examples

```bash
# Single language translation
python src/cli.py file samples/intro.md -t en

# Batch translation
python src/cli.py file samples/intro.md -t en,ja,zh

# Direct text translation
python src/cli.py text "안녕하세요" -t en
```

## Notes

To improve translation quality, you can provide additional context information about the document using the `-c` option.

## GitHub Actions Automatic Translation

When you modify this file and push it, GitHub Actions will automatically generate translated files in English, Japanese, and Chinese.

## Supported File Formats

Markdown, text, JSON, and YAML formats are all supported.

## Benefits of Automation

Automating repetitive translation tasks can save time and costs. When integrated with GitHub Actions, translation and verification are executed immediately upon file modification.

## Cautions

- Manage your API key as a GitHub Secret to prevent it from being exposed externally.
- Do not manually edit translated output files (`.en.md`, `.ja.md`, etc.). They will be automatically overwritten when the source file is modified.
- Large files may take time to translate.