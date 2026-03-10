# 運用設計書 — Token Discovery Pipeline

## 1. コスト設計（ほぼ無料で運用する）

### 月次コスト試算

| コンポーネント | サービス | 月額目安 |
|---|---|---|
| コンピュート | Fly.io shared-cpu-1x (256MB) | **$0** (無料枠内) |
| ストレージ | Fly.io Volume 1GB | **$0.15** ≈ 無視可 |
| DB | SQLite on Volume | **$0** |
| AI分析 | Claude Haiku 4.5 (12h毎 × 30日 = 60回/月) | **$0.05〜$0.20** |
| GitHub API | 無料枠 5000 req/h | **$0** |
| GeckoTerminal | 無料枠 30 req/min | **$0** |
| GoPlus | 無料枠 | **$0** |
| 通知 | Discord Webhook | **$0** |
| CI/CD | GitHub Actions (2000 min/月) | **$0** |
| **合計** | | **$0.05〜$0.35/月** |

> **注意:** Claude API コストはトークン数に依存。
> Haiku は Input $0.80/MTok, Output $4/MTok (2025年現在)。
> 1回の分析あたり約 ~500 input + ~300 output tokens → ~$0.001/token。
> 1日10トークン × 30日 = 300分析/月 → **約$0.30/月**。

---

## 2. インフラ構成

```
GitHub (コード管理)
    │
    ├── GitHub Actions (CI/CD)
    │       ├── Lint (black, isort)
    │       ├── Unit Tests
    │       ├── Integration Tests
    │       └── Deploy to Fly.io (main ブランチのみ)
    │
    └── Fly.io (実行環境)
            ├── Docker Container (python:3.11-slim)
            │       └── APScheduler (バックグラウンドワーカー)
            │               ├── L1+L2 every 4h
            │               ├── L3 every 6h
            │               ├── L4+L5 every 12h
            │               ├── L6 daily 08:00 UTC
            │               ├── waitlist check every 1h
            │               └── cleanup weekly
            └── Fly Volume (1GB)
                    └── token_pipeline.db (SQLite)
```

---

## 3. 初期セットアップ手順

### 3.1 Fly.io セットアップ

```bash
# Fly CLI インストール
curl -L https://fly.io/install.sh | sh

# ログイン
flyctl auth login

# アプリ作成 (初回のみ)
flyctl apps create token-pipeline

# ボリューム作成 (SQLite永続化)
flyctl volumes create pipeline_data --size 1 --region nrt

# シークレット設定
flyctl secrets set \
  ANTHROPIC_API_KEY="sk-ant-..." \
  GITHUB_TOKEN="ghp_..." \
  DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
  NOTION_API_KEY="secret_..." \
  NOTION_DATABASE_ID="..."
```

### 3.2 GitHub Actions シークレット設定

GitHub リポジトリ → Settings → Secrets and variables → Actions:

| シークレット名 | 説明 |
|---|---|
| `FLY_API_TOKEN` | `flyctl tokens create deploy` で取得 |

### 3.3 初回デプロイ

```bash
git push origin main
# GitHub Actions が自動的に CI → Deploy を実行
```

### 3.4 ローカル開発

```bash
cd token-pipeline
pip install -e ".[dev]"

# .env ファイル作成
cp ../.env.example .env
# エディタで .env を編集

# 一回だけ実行 (テスト)
PIPELINE_MODE=once python -m src.main

# スケジューラーとして起動
PIPELINE_MODE=scheduler python -m src.main

# テスト実行
pytest tests/unit -v
pytest tests/integration -v
```

---

## 4. 監視・アラート

### 4.1 ログ確認

```bash
# Fly.io ログリアルタイム
flyctl logs -a token-pipeline

# ログフィルタ (エラーのみ)
flyctl logs -a token-pipeline | grep "ERROR"
```

### 4.2 デプロイ状況確認

```bash
flyctl status -a token-pipeline
flyctl checks list -a token-pipeline
```

### 4.3 DB確認 (デバッグ用)

```bash
# Fly.io マシンにSSH接続
flyctl ssh console -a token-pipeline

# SQLite操作
sqlite3 /data/token_pipeline.db
.tables
SELECT count(*) FROM tokens;
SELECT * FROM daily_rankings ORDER BY date DESC LIMIT 10;
```

---

## 5. スケーリング戦略

### Phase 1 (現状): 無料枠内
- 単一コンテナ, SQLite, 256MB RAM
- 対象チェーン: 5チェーン
- AI分析: Claude Haiku (安価)

### Phase 2 ($5〜20/月): 品質向上
- メモリ 512MB に増強 (`flyctl scale memory 512`)
- Claude Sonnet に切替 (より高品質な分析)
- 対象チェーン を 10チェーンに拡張

### Phase 3 ($20〜50/月): 本格運用
- PostgreSQL 移行 (Fly Postgres Hobby: $5/月)
- Web ダッシュボード追加 (Streamlit on Fly: 追加$0)
- バックテスト機能

---

## 6. 障害対応

### APIが止まった場合
- GeckoTerminal → DexScreener に自動フォールバック
- DexScreener も停止 → DexPaprika に自動フォールバック
- Claude API → フォールバックスコア (30点) で処理継続

### コンテナがクラッシュした場合
Fly.io が自動再起動 (`auto_stop_machines = false` の場合)。

```bash
# 手動再起動
flyctl restart -a token-pipeline
```

### DB破損の場合

```bash
# バックアップからリストア (事前にバックアップを取っておくこと)
flyctl ssh console -a token-pipeline
sqlite3 /data/token_pipeline.db ".dump" > backup.sql
```

---

## 7. コスト最適化 Tips

1. **Claude APIコスト削減:**
   - `CLAUDE_MODEL=claude-haiku-4-5-20251001` (デフォルト) を維持
   - L4/L5 の実行頻度を 24h に下げる (設定で変更可能)
   - 既にスコア済みのトークンはスキップ (実装済み)

2. **API無料枠の保全:**
   - GeckoTerminal: 10 req/min (余裕あり)
   - GoPlus: バッチ処理でリクエスト数削減 (実装済み)
   - GitHub: 認証トークン設定で 5000 req/h を活用

3. **Fly.io 無料枠の保全:**
   - マシンを1台のみ稼働 (デフォルト)
   - `auto_stop_machines = true` は設定しない (スケジューラーが止まる)
   - `min_machines_running = 1` を維持

---

## 8. セキュリティ

- APIキーは全て環境変数 / Fly Secrets で管理
- `.env` は `.gitignore` に記載済み
- Docker コンテナは非rootユーザーで動作
- SQLite は Fly Volume (プライベートネットワーク内) に格納
- GitHub Actions の Secrets は暗号化保存

---

## 9. Discord 通知サンプル

```
📊 Daily Token Report — 2025-03-07

🥇 #1. $ALPHA (ethereum)
   Score: 78.5 / 100
   Chain: Ξ ethereum
   Breakdown:
     Security: 85 | Fundamentals: 70 | Narrative: 80 | Momentum: 65 | Community: 55
   Summary: "Promising DeFi protocol with active GitHub and CertiK audit."
   Chart: [DEXScreener](https://dexscreener.com/ethereum/0xpool1)

🥈 #2. $BETA (base)
   Score: 72.1 / 100
   ...
```
