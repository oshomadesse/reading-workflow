---
tags:
  - engineering
  - books-summary
  - done
---
# 読書サマリー自動生成システム

## 目的
毎朝7:00に「今日読むべき本」をAIが自動選定・リサーチし、インフォグラフィック付きのサマリーを生成してLINEに通知することで、読書習慣の定着と知識のインプットを効率化する。

## システム概要
GitHub Actions 上で Python スクリプトを定期実行し、複数のAIモデル（Gemini, GPT-5, Claude）を組み合わせて高品質な読書ノートを生成する。

### アーキテクチャ
- **実行環境**: GitHub Actions (Ubuntu latest)
- **言語**: Python 3.11+
- **AIモデル**:
    - 推薦: Gemini 2.5 Flash
    - リサーチ: GPT-5 (or Gemini Pro)
    - 図解生成: Claude 4.5 Sonnet
- **データソース**: Google Custom Search API (補助), Google Sheets (除外リスト)
- **通知**: LINE Messaging API (Flex Message)

## 機能仕様

### 1. 除外リスト取得 (Step 1)
- **担当**: `sheets_connector.py`
- **内容**: Google Sheetsから過去に読んだ本や除外したい本のリストを取得する。

### 2. 書籍推薦 (Step 2)
- **担当**: `gemini_recommend.py`
- **モデル**: Gemini 2.5 Flash
- **内容**: 除外リストを考慮し、指定カテゴリ（ビジネス、自己啓発、心理学など）から今日読むべき本を5冊推薦する。
- **フィルタ**: 日本語タイトル以外の除外、禁止ワード（小説など）の除外。

### 3. 選書 (Step 3)
- **内容**: 推薦された5冊の中からランダムに1冊を選択する。

### 4. Deep Research (Step 4)
- **担当**: `chatgpt_research.py`
- **モデル**: GPT-5
- **内容**: 選択された本について詳細なリサーチを行い、核心的メッセージ、エグゼクティブサマリー、アクションプラン等をJSON形式で抽出する。

### 5. インフォグラフィック生成 (Step 5)
- **担当**: `claude_infographic.py`
- **モデル**: Claude 3.5 Sonnet
- **内容**: リサーチ結果を元に、概念図解を含む単一のHTMLファイルを生成する。
- **出力**: `infographics/[書籍名]_infographic.html`
- **機能**: 生成されたHTMLは即時Pushされ、GitHub Pagesで公開される。

### 6. ノート生成 (Step 6-7)
- **内容**: リサーチ結果とインフォグラフィックへのリンクを含むMarkdownノートを作成する。
- **出力**: `artifacts/Books-YYYY-MM-DD.md` (CI環境)
- **同期**: ローカル環境へのPull時に `post-merge` フックで `100_Inbox` へ自動移動される。

### 7. 事後処理・通知 (Step 8-9)
- **除外リスト更新**: 選ばれた本をGoogle Sheetsに追記する。
- **通知**: LINE Messaging API (Flex Message) で、生成されたノートへのリンクとサマリーをユーザーに通知する。

## ディレクトリ構成
```
📖 books-summary/
├── .github/workflows/
│   └── daily_workflow.yml          # 定期実行ワークフロー
├── integrated_reading_workflow.py  # 統合ワークフロー実行スクリプト
├── chatgpt_research.py             # リサーチモジュール
├── claude_infographic.py           # インフォグラフィック生成モジュール
├── gemini_recommend.py             # 推薦モジュール
├── data/
│   ├── integrated/                 # 統合ログ (integrated_run_*.log)
│   └── modules/                    # モジュール別デバッグログ
├── artifacts/                      # 生成されたMarkdownノート (CI用)
├── infographics/                   # 生成されたHTML図解
└── requirements.txt                # 依存ライブラリ
```

## 環境変数 (GitHub Secrets)

| 変数名 | 説明 |
|---|---|
| `OPENAI_API_KEY` | OpenAI API Key (GPT-5用) |
| `ANTHROPIC_API_KEY` | Anthropic API Key (Claude用) |
| `GEMINI_API_KEY` | Google AI Studio API Key (Gemini用) |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API Token |
| `LINE_USER_ID` | LINE User ID (通知送信先) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Sheets/Drive API用 サービスアカウントJSON |
| `EXCLUDED_SHEET_ID` | 除外リスト用スプレッドシートID |

## 運用
- **スケジュール**: 毎日 7:00 JST
- **手動実行**: GitHub Actions タブから `workflow_dispatch` で実行可能
- **ローカル同期**: `auto_pull.sh` (LaunchAgent) により毎朝自動で成果物をローカルに取り込む。
