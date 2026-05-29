# 翻译自动化工具介绍

本工具利用 Claude API 将各类文档自动翻译成多种语言。

## 主要功能

- **多语言支持**：支持韩语、英语、日语、中文、西班牙语等10种语言
- **文件格式**：支持翻译 Markdown、文本、JSON 文件
- **批量翻译**：将一个文件同时翻译成多种语言
- **代码保留**：代码块内容不进行翻译，保持原样

## 使用示例

```bash
# 单一语言翻译
python src/cli.py file samples/intro.md -t en

# 批量翻译
python src/cli.py file samples/intro.md -t en,ja,zh

# 直接翻译文本
python src/cli.py text "안녕하세요" -t en
```

## 注意事项

如需提高翻译质量，可通过 `-c` 选项额外提供文档的上下文信息。

## GitHub Actions 自动翻译

修改此文件并推送后，GitHub Actions 将自动生成英语、日语、中文翻译文件。

## 支持的文件格式

支持 Markdown、文本、JSON、YAML 等所有格式。

## 自动化效果

将重复性翻译工作自动化，可以节省时间和成本。与 GitHub Actions 联动时，文件修改后将立即执行翻译和验证。

## 注意事项

- 请通过 GitHub Secret 管理 API 密钥，避免对外泄露。
- 请勿直接修改翻译结果文件（`.en.md`、`.ja.md` 等）。修改源文件时将自动覆盖。
- 大容量文件的翻译可能需要较长时间。