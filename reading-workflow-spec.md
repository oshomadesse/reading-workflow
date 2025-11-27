# reading-workflow 仕様書

## 概要
本プロジェクトは、書籍の選定からリサーチ、インフォグラフィック生成、Obsidianノート作成までを自動化するワークフローシステムです。
`.999_Others/reading-workflow` フォルダ（主に `docs`）は成果物の格納場所の一部であり、システムの中核は `.999_Others` 直下のPythonスクリプト群によって担われています。

## ディレクトリ・ファイル構成

```
.999_Others/
├── integrated_reading_workflow.py  # 統合ワークフロー実行スクリプト（エントリーポイント）
├── chatgpt_research.py             # 書籍リサーチ (GPT-5 / Gemini Pro)
├── claude_infographic.py           # インフォグラフィック生成 (Claude 3.5 Sonnet)
├── gemini_recommend.py             # 書籍推薦 (Gemini Flash)
├── sheets_connector.py             # Google Sheets連携 (除外リスト管理)
├── infographics/                   # テンプレート格納
│   └── infographic_template.html
└── reading-workflow/
    └── docs/                       # インフォグラフィックHTML格納場所（アーカイブ的用途）
```

※ 実際の成果物（HTML, Markdown）は `100_Inbox` に出力されます。

## 自動化ワークフロー詳細 (`integrated_reading_workflow.py`)

`integrated_reading_workflow.py` を実行することで、以下のステップが順次処理されます。

### Step 1: 除外リスト取得
- **担当**: `sheets_connector.py`
- **内容**: Google Sheetsから過去に読んだ本や除外したい本のリストを取得します。

### Step 2: 書籍推薦
- **担当**: `gemini_recommend.py`
- **モデル**: Gemini 1.5 Flash
- **内容**: 除外リストを考慮し、指定カテゴリ（ビジネス、自己啓発など）から今日読むべき本を5冊推薦します。
- **フィルタ**: 日本語タイトル以外の除外、禁止ワード（小説など）の除外を行います。

### Step 3: 選書
- **内容**: 推薦された5冊の中からランダムに1冊を選択します。

### Step 4: Deep Research
- **担当**: `chatgpt_research.py`
- **モデル**: GPT-5 (または Gemini Pro)
- **内容**: 選択された本について詳細なリサーチを行い、以下の情報をJSON形式で抽出します。
    - 核心的メッセージ
    - エグゼクティブ・サマリー（問い×答え×根拠）
    - 主要概念
    - 関連書籍
    - 今日できるアクション

### Step 5: インフォグラフィック生成
- **担当**: `claude_infographic.py`
- **モデル**: Claude 3.5 Sonnet
- **内容**: Step 4のリサーチ結果を元に、単一のHTMLファイルとしてインフォグラフィックを生成します。
- **出力**: `100_Inbox/[書籍名]_infographic.html`
- **機能**: GitHub Pagesへの自動デプロイ機能も有しています。

### Step 6: 中間サマリ作成
- **内容**: ノート生成に必要な変数を整理・正規化します。

### Step 7: Obsidianノート生成
- **内容**: リサーチ結果とインフォグラフィックへのリンクを含むMarkdownノートを作成します。
- **出力**: `100_Inbox/Books-YYYY-MM-DD.md`
- **フォーマット**:
    - フロントマター: `tags: [books]`
    - 基本情報（著者、カテゴリ）
    - 生成コンテンツ（インフォグラフィックURL、リサーチレポートURL）
    - 今日できるアクション（チェックリスト）
    - 要約（核心メッセージ、エグゼクティブサマリー）
    - 関連書籍

### Step 8 & 9: 事後処理
- **除外リスト更新**: 選ばれた本をGoogle Sheetsの除外リストに追記します。
- **通知**: LINE Messaging APIを通じて、生成されたObsidianノートへのリンク（`obsidian://`）をユーザーに通知します。

## 成果物仕様 (HTML)

### ファイル命名規則
- `[書籍名]_infographic.html`
- 書籍名のスペースはアンダースコア `_` に置換されます。

### HTML構造
各ファイルは外部依存関係を持たない（CSS, JSが埋め込まれた）スタンドアローンなHTMLファイルです。

#### 基本構成
- **Doctype**: HTML5 (`<!DOCTYPE html>`)
- **Language**: `ja`
- **Meta**: UTF-8, Viewport設定あり（レスポンシブ対応）
- **Style**: `<head>` 内にCSSを記述
- **Script**: `<body>` 末尾にタブ切り替え用のスクリプトを記述

#### コンテンツ構成
1.  **ヘッダー**: 書籍タイトル
2.  **要約ブロック**: 「問い」「答え」「Why」「How」
3.  **ビジュアルフロー**: 概念図解
4.  **詳細タブ**:
    - 主要概念の詳細
    - 各章の要約
    - 具体例
    - 重要な引用
    - 今日のアクション

## 環境設定 (.env)
以下のAPIキーや設定が必要です。
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON` (またはPATH)
- `LINE_CHANNEL_ACCESS_TOKEN` (通知用)
- `VAULT_ROOT`, `INBOX_DIR` (Obsidianパス)
