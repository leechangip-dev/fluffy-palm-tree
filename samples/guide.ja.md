# 翻訳ツール使用ガイド

このガイドでは、Claude APIベースの翻訳自動化ツールの使用方法を説明します。

## はじめに

### 1. 環境設定

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-api-key"
```

### 2. 基本的な使い方

テキストを直接翻訳したり、ファイル単位で翻訳したりすることができます。

```bash
# テキスト翻訳
python src/cli.py text "번역할 내용" -t en

# ファイル翻訳
python src/cli.py file ファイルパス -t en

# 複数の言語への同時翻訳
python src/cli.py file ファイルパス -t en,ja,zh
```

## 対応言語一覧

| コード | 言語 |
|------|------|
| ko | 韓国語 |
| en | 英語 |
| ja | 日本語 |
| zh | 中国語（簡体字） |
| zh-tw | 中国語（繁体字） |
| es | スペイン語 |
| fr | フランス語 |
| de | ドイツ語 |
| pt | ポルトガル語 |
| vi | ベトナム語 |

## 高度な機能

### 翻訳キャッシュ

同じテキストを繰り返し翻訳する際に、API呼び出しを減らしてコストを削減します。

```bash
# キャッシュを無効化
python src/cli.py --no-cache file ファイルパス -t en
```

### 言語の自動検出

ソース言語を指定しない場合、自動的に検出します。

```bash
python src/cli.py detect ファイルパス
```

### 翻訳コンテキストの指定

`-c` オプションで翻訳品質を向上させることができます。

```bash
python src/cli.py file ファイルパス -t en -c "技術文書、ITソフトウェア関連"
```

## GitHub Actions 自動化

`samples/` フォルダのファイルを修正してpushすると、自動的に翻訳が実行されます。

1. ソースファイルを修正
2. `git push`
3. GitHub Actions 自動実行
4. 翻訳ファイルの自動生成およびコミット