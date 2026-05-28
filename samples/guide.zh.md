# 翻译工具使用指南

本指南介绍基于 Claude API 的翻译自动化工具的使用方法。

## 快速入门

### 1. 环境配置

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-api-key"
```

### 2. 基本用法

可以直接翻译文本，也可以按文件单位进行翻译。

```bash
# 文本翻译
python src/cli.py text "번역할 내용" -t en

# 文件翻译
python src/cli.py file 파일경로 -t en

# 同时翻译为多种语言
python src/cli.py file 파일경로 -t en,ja,zh
```

## 支持的语言列表

| 代码 | 语言 |
|------|------|
| ko | 韩语 |
| en | 英语 |
| ja | 日语 |
| zh | 中文（简体）|
| zh-tw | 中文（繁体）|
| es | 西班牙语 |
| fr | 法语 |
| de | 德语 |
| pt | 葡萄牙语 |
| vi | 越南语 |

## 高级功能

### 翻译缓存

在重复翻译相同文本时，可减少 API 调用次数，从而降低费用。

```bash
# 禁用缓存
python src/cli.py --no-cache file 파일경로 -t en
```

### 语言自动检测

若未指定源语言，将自动进行检测。

```bash
python src/cli.py detect 파일경로
```

### 指定翻译上下文

使用 `-c` 选项可提升翻译质量。

```bash
python src/cli.py file 파일경로 -t en -c "기술 문서, IT 소프트웨어 관련"
```

## GitHub Actions 自动化

修改 `samples/` 文件夹中的文件并执行 push 后，将自动运行翻译。

1. 修改源文件
2. 执行 `git push`
3. GitHub Actions 自动运行
4. 自动生成并提交翻译文件