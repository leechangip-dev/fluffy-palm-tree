# Translation Tool Usage Guide

This guide explains how to use the Claude API-based translation automation tool.

## Getting Started

### 1. Environment Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-api-key"
```

### 2. Basic Usage

You can translate text directly or translate on a file-by-file basis.

```bash
# Text translation
python src/cli.py text "번역할 내용" -t en

# File translation
python src/cli.py file 파일경로 -t en

# Simultaneous translation into multiple languages
python src/cli.py file 파일경로 -t en,ja,zh
```

## Supported Languages

| Code | Language |
|------|------|
| ko | Korean |
| en | English |
| ja | Japanese |
| zh | Chinese (Simplified) |
| zh-tw | Chinese (Traditional) |
| es | Spanish |
| fr | French |
| de | German |
| pt | Portuguese |
| vi | Vietnamese |

## Advanced Features

### Translation Cache

Reduces API calls and lowers costs when repeatedly translating the same text.

```bash
# Disable cache
python src/cli.py --no-cache file 파일경로 -t en
```

### Automatic Language Detection

If no source language is specified, it will be detected automatically.

```bash
python src/cli.py detect 파일경로
```

### Specifying Translation Context

You can improve translation quality using the `-c` option.

```bash
python src/cli.py file 파일경로 -t en -c "기술 문서, IT 소프트웨어 관련"
```

## GitHub Actions Automation

Translation runs automatically when you modify files in the `samples/` folder and push.

1. Modify source files
2. `git push`
3. GitHub Actions runs automatically
4. Translation files are automatically generated and committed