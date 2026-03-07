# トークン発掘パイプライン — システム設計書

---

## 1. アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator (main.py)                │
│              APScheduler / cron ベースの制御              │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│  L1: Discovery │────▶│  L2: PreFilter │────▶│  L3: Security  │
│  (API収集)      │     │  (機械フィルタ)  │     │  (GoPlus等)    │
└────────────────┘     └────────────────┘     └────────────────┘
                                                      │
         ┌────────────────────────────────────────────┘
         ▼
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│ L4: Fundamentals│────▶│ L5: Sentiment  │────▶│  L6: Ranking   │
│ (GitHub+AI)     │     │ (Narrative+AI) │     │  (出力・通知)   │
└────────────────┘     └────────────────┘     └────────────────┘
         │                    │                       │
         ▼                    ▼                       ▼
┌─────────────────────────────────────────────────────────┐
│                  SQLite (token_pipeline.db)              │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              通知 (Discord Webhook / Notion API)         │
└─────────────────────────────────────────────────────────┘
```

---

## 2. ディレクトリ構成

```
token-pipeline/
├── config/
│   ├── settings.yaml          # 全体設定（閾値、重み、対象チェーン等）
│   └── chains.yaml            # チェーン別設定（RPC URL、Explorer API等）
│
├── src/
│   ├── __init__.py
│   ├── main.py                # エントリーポイント、Orchestrator
│   │
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── base.py            # Layer基底クラス（共通インターフェース）
│   │   ├── l1_discovery.py
│   │   ├── l2_prefilter.py
│   │   ├── l3_security.py
│   │   ├── l4_fundamentals.py
│   │   ├── l5_sentiment.py
│   │   └── l6_ranking.py
│   │
│   ├── clients/               # 外部API クライアント（1 API = 1 ファイル）
│   │   ├── __init__.py
│   │   ├── gecko_terminal.py
│   │   ├── dex_screener.py
│   │   ├── dex_paprika.py
│   │   ├── goplus.py
│   │   ├── github_client.py
│   │   └── claude_agent.py    # Claude APIラッパー
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py          # SQLAlchemy / dataclass モデル定義
│   │   ├── repository.py      # CRUD操作
│   │   └── migrations/        # スキーマ変更管理
│   │
│   ├── notifiers/
│   │   ├── __init__.py
│   │   ├── discord.py
│   │   └── notion.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── rate_limiter.py    # トークンバケット方式のレート制限
│       ├── retry.py           # リトライ + エクスポネンシャルバックオフ
│       └── logger.py          # 構造化ログ
│
├── tests/
│   ├── unit/
│   │   ├── test_l1_discovery.py
│   │   ├── test_l2_prefilter.py
│   │   └── ...
│   └── integration/
│       └── test_pipeline_e2e.py
│
├── pyproject.toml
└── README.md
```

---

## 3. データベーススキーマ

### 3.1 テーブル一覧

```
tokens              — トークンのマスタ情報
pools               — DEXプール情報（1トークン:多プール）
pipeline_runs       — パイプライン実行ログ
scan_results        — 各レイヤーの処理結果
daily_rankings      — 日次ランキング出力
wait_list           — 冷却期間中トークン
```

### 3.2 テーブル定義

#### tokens

| カラム | 型 | 説明 |
|---|---|---|
| id | TEXT (PK) | `{chain}:{contract_address}` の複合キー |
| chain | TEXT | solana / ethereum / base / ... |
| contract_address | TEXT | コントラクトアドレス |
| name | TEXT | トークン名 |
| symbol | TEXT | ティッカーシンボル |
| discovered_at | DATETIME | 初回発見日時 |
| status | TEXT | `active` / `dropped` / `watching` |
| drop_reason | TEXT | 除外理由（NULLable） |
| created_at | DATETIME | レコード作成日時 |
| updated_at | DATETIME | レコード更新日時 |

#### pools

| カラム | 型 | 説明 |
|---|---|---|
| id | TEXT (PK) | プールアドレス |
| token_id | TEXT (FK → tokens) | 対象トークン |
| dex | TEXT | DEX名（Raydium, Uniswap等） |
| base_token | TEXT | ペアの基軸トークン |
| liquidity_usd | REAL | 流動性（USD） |
| volume_24h | REAL | 24h出来高（USD） |
| txns_24h | INTEGER | 24h取引回数 |
| created_at | DATETIME | プール作成日時 |
| snapshot_at | DATETIME | データ取得日時 |

#### scan_results

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER (PK) | 自動採番 |
| token_id | TEXT (FK → tokens) | 対象トークン |
| layer | TEXT | `L1` ~ `L6` |
| score | REAL | 各レイヤーのスコア（0–100） |
| details | TEXT (JSON) | レイヤー固有の詳細データ |
| flags | TEXT (JSON) | 警告フラグ配列 |
| run_id | TEXT (FK → pipeline_runs) | 実行ID |
| scanned_at | DATETIME | 処理日時 |

#### pipeline_runs

| カラム | 型 | 説明 |
|---|---|---|
| id | TEXT (PK) | UUID |
| started_at | DATETIME | 開始日時 |
| finished_at | DATETIME | 終了日時 |
| status | TEXT | `running` / `completed` / `failed` |
| stats | TEXT (JSON) | 各レイヤーの処理件数等 |

#### daily_rankings

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER (PK) | 自動採番 |
| date | DATE | ランキング日 |
| rank | INTEGER | 順位（1–10） |
| token_id | TEXT (FK → tokens) | 対象トークン |
| total_score | REAL | 総合スコア |
| score_breakdown | TEXT (JSON) | 各スコアの内訳 |
| summary | TEXT | AI生成の30秒サマリー |
| risk_flags | TEXT (JSON) | リスクフラグ一覧 |

#### wait_list

| カラム | 型 | 説明 |
|---|---|---|
| token_id | TEXT (PK, FK → tokens) | 対象トークン |
| reason | TEXT | 待機理由 |
| eligible_at | DATETIME | フィルタ再通過可能日時 |

---

## 4. 各レイヤー詳細設計

### 4.1 Layer 1: Discovery

```
入力: なし（外部APIからプル）
出力: List[RawToken]  →  tokens / pools テーブルへ INSERT
```

**処理フロー:**

1. `GeckoTerminal` → 対象チェーンごとに `GET /networks/{chain}/new_pools` を呼ぶ
2. `DEX Screener` → `GET /token-boosts/latest` + `GET /token-profiles/latest` で boosted/trending 取得
3. 取得結果を `RawToken` データクラスに統一マッピング
4. 既知トークン（DBに存在済み）を除外
5. 新規トークンを `tokens` テーブルへ `status=active` で INSERT
6. プール情報を `pools` テーブルへ INSERT

**APIフォールバック戦略:**

```
Primary:   GeckoTerminal (30 calls/min)
Secondary: DEX Screener  (60–300 rpm, trending特化)
Fallback:  DexPaprika    (GeckoTerminal障害時のみ)
```

各クライアントは共通インターフェース `DiscoverySource` を実装し、
Orchestrator は健全なソースから順に呼ぶ。

**対象チェーン（初期）:**

```yaml
chains:
  - solana
  - ethereum
  - base
  - arbitrum
  - bsc
```

設定ファイルで追加・削除可能にする。

---

### 4.2 Layer 2: Pre-filter

```
入力: List[RawToken]  （L1 の出力 or DBからstatus=activeを取得）
出力: List[FilteredToken]  →  通過 / drop / wait_list に振り分け
```

**フィルタルール（設定ファイルで閾値変更可能）:**

```yaml
prefilter:
  min_liquidity_usd: 5000
  min_txns_24h: 10
  cooldown_minutes: 60           # 作成後N分以内 → wait_list
  max_single_wallet_share: 0.80  # 80%以上 → flag
  min_volume_sustain_hours: 6    # 出来高スパイク判定の最低持続時間
```

**判定ロジック（優先順）:**

1. `liquidity_usd < min_liquidity_usd` → `status=dropped`, `drop_reason=low_liquidity`
2. `txns_24h < min_txns_24h` → `status=dropped`, `drop_reason=low_activity`
3. `pool_age < cooldown_minutes` → `wait_list` テーブルへ移動
4. 出来高パターン分析 → 持続性なし → `status=dropped`
5. ウォレット集中度チェック → 80%超 → `flags` に `whale_concentration` 追加（drop はしない）

---

### 4.3 Layer 3: Security Scan

```
入力: List[FilteredToken]  （L2 通過分）
出力: List[ScannedToken]  →  Security Score 付与
```

**GoPlus API レスポンスのスコア化ルール:**

```yaml
security_scoring:
  # 各フラグの減点値（100点満点から引く）
  deductions:
    is_honeypot: -100            # 即座に drop
    cannot_sell_all: -80
    can_take_back_ownership: -40
    owner_change_balance: -40
    is_blacklisted: -30
    is_proxy: -20
    is_mintable: -15
    hidden_owner: -15
    external_call: -10
    is_open_source: 0            # false の場合 -20
    lp_holders_locked: 0         # false の場合 -10（警告のみ）

  drop_threshold: 40             # このスコア未満は drop
```

**処理フロー:**

1. `GoPlus Token Security API` にコントラクトアドレスを送信
2. レスポンスの各フラグを上記ルールでスコア化
3. `score < 40` → `status=dropped`, `drop_reason=security_fail`
4. LP ロック未確認 → `flags` に `lp_not_locked` 追加（通過させる）
5. `scan_results` テーブルに詳細を JSON 保存

**バッチ処理:**
GoPlus の無料枠を考慮し、1回のリクエストで複数トークンをまとめて送信。
レート制限到達時は `rate_limiter.py` でスリープ。

---

### 4.4 Layer 4: Fundamentals

```
入力: List[ScannedToken]  （L3 通過分）
出力: List[AnalyzedToken]  →  Fundamentals Score 付与
```

**GitHub 分析（自動）:**

```
GitHub Score の構成:
  commit_frequency   = 最近30日のコミット数 → 正規化（0–30）
  contributor_count   = ユニークコントリビューター数 → 正規化（0–30）
  recency            = 最終コミットからの経過日数 → 逆正規化（0–20）
  stars              = Star数 → 対数正規化（0–10）
  has_readme          = README.md の有無（0 or 10）
  ─────────────────────────────────────────────────────
  GitHub Score       = 上記合計（0–100）
```

GitHub リポジトリが不明な場合:
1. トークン公式サイトからリンクを探索（AIエージェント）
2. GitHub Search API でプロジェクト名検索
3. 見つからない場合 → `github_score = 0`、フラグ `no_github` 追加

**AIエージェント分析（Claude API）:**

- 入力: 公式サイトURL、ドキュメントURL（L1で取得済み or 検索で発見）
- プロンプト設計: 構造化出力（JSON）を要求

```
AIエージェントへの指示（要約）:
  1. プロジェクト概要を1文で
  2. トークノミクス構造（配分比率、Vesting、バーン有無）
  3. ロードマップの具体性（1–5段階）
  4. 監査レポートの有無と監査会社名
  5. チーム情報の透明性（1–5段階）
  → JSON で返却
```

**Fundamentals Score:**

```
fundamentals_score = github_score * 0.4 + ai_analysis_score * 0.6
```

---

### 4.5 Layer 5: Sentiment & Narrative

```
入力: List[AnalyzedToken]  （L4 通過分）
出力: List[ScoredToken]  →  Narrative Score + Community Score 付与
```

**CoinGecko カテゴリマッチング:**
- `GET /coins/{id}` → `categories` フィールドで自動分類
- 未登録トークンの場合 → AIエージェントが公式情報から分類

**市場テーマスコアリング（設定ファイルで更新）:**

```yaml
hot_narratives:
  - name: "AI"
    weight: 1.0
  - name: "RWA"
    weight: 0.9
  - name: "DePIN"
    weight: 0.85
  - name: "Meme"
    weight: 0.7
  - name: "GameFi"
    weight: 0.6
  # ... 月次で手動更新、または AI に自動提案させる
```

**AIエージェントの処理:**

```
入力: トークン名、カテゴリ、公式サイト要約（L4から引き継ぎ）
出力（JSON）:
  - narrative_category: "AI Agent"
  - narrative_alignment: 85         # 市場テーマとの合致度
  - competitive_summary: "..."      # 競合比較3行
  - novelty_score: 70               # 新規性
  - community_health: 60            # コミュニティ健全性推定
```

**Community Score:**

```
community_score の構成:
  has_discord        = 存在確認（0 or 20）
  has_telegram       = 存在確認（0 or 20）
  twitter_mentions   = 直近7日の言及数 → 正規化（0–30）
  twitter_engagement = エンゲージメント率 → 正規化（0–30）
  ─────────────────────────────────────────────────────
  Community Score    = 上記合計（0–100）
```

---

### 4.6 Layer 6: Ranking & Output

```
入力: List[ScoredToken]  （L5 まで通過した全トークン）
出力: DailyReport  →  daily_rankings テーブル + 通知送信
```

**総合スコア計算:**

```python
total_score = (
    security_score    * weights["security"]      # default 0.30
  + fundamentals_score * weights["fundamentals"]  # default 0.20
  + narrative_score    * weights["narrative"]      # default 0.25
  + momentum_score     * weights["momentum"]       # default 0.15
  + community_score    * weights["community"]      # default 0.10
)
```

重みは `settings.yaml` で調整可能。

**レポート生成フロー:**

1. 総合スコアで降順ソート
2. Top 10 を抽出
3. 各トークンの30秒サマリーを Claude API で生成（バッチ）
4. `daily_rankings` テーブルへ INSERT
5. 通知送信（Discord Webhook / Notion）

**Discord Webhook メッセージ構造:**

```
📊 Daily Token Report — 2025-03-07

🥇 1. $TOKEN_A (Solana)
   Score: 82/100
   "AIエージェント基盤。GitHub活発、LP90日ロック済み"
   ⚠️ mintable権限あり
   📈 https://dexscreener.com/solana/...

🥈 2. $TOKEN_B (Base)
   ...
```

---

## 5. 横断的関心事

### 5.1 レート制限管理

各APIクライアントに `RateLimiter` を注入する。

```
API別レート制限設定:
  GeckoTerminal:  30 calls/min  →  トークンバケット (30, refill=1/2sec)
  DEX Screener:   60 calls/min  →  トークンバケット (60, refill=1/sec)
  GoPlus:         制限調査中     →  保守的に 20 calls/min で開始
  GitHub:         5000 calls/h   →  トークンバケット (5000, refill=1.4/sec)
  CoinGecko:      10000 calls/月 →  日次バジェット管理 (~330/day)
  Claude API:     利用プランによる →  設定ファイルで制御
```

### 5.2 エラーハンドリング・リトライ

```
リトライポリシー:
  max_retries: 3
  backoff: exponential (1s → 2s → 4s)
  retry_on:
    - HTTP 429 (Rate Limited)
    - HTTP 500, 502, 503, 504
    - ConnectionError
    - Timeout
  no_retry_on:
    - HTTP 400 (Bad Request)
    - HTTP 401/403 (Auth Error)
    - HTTP 404 (Not Found)
```

各レイヤーは独立して失敗可能。
あるトークンの L4 が失敗しても、他のトークンの処理は継続する。
失敗したトークンは `scan_results.details` にエラー内容を記録し、次回実行で再試行。

### 5.3 ロギング

```
ログレベル設計:
  INFO   — レイヤー開始/終了、処理件数、スコア概要
  WARNING — フォールバック発生、レート制限到達、部分的なデータ欠損
  ERROR  — API障害、パース失敗、DB書き込み失敗
  DEBUG  — APIリクエスト/レスポンス生データ（開発時のみ）

出力先: stdout + ファイルローテーション (10MB × 5世代)
フォーマット: JSON Lines（構造化ログ）
```

### 5.4 設定管理

`settings.yaml` に全閾値・重み・対象チェーンを集約。
環境変数で上書き可能（`TOKEN_PIPELINE_MIN_LIQUIDITY=10000` など）。

```yaml
# settings.yaml（抜粋）
pipeline:
  schedule: "0 */4 * * *"    # 4時間ごとに実行
  target_chains:
    - solana
    - ethereum
    - base

prefilter:
  min_liquidity_usd: 5000
  min_txns_24h: 10
  cooldown_minutes: 60

security:
  drop_threshold: 40

ranking:
  weights:
    security: 0.30
    fundamentals: 0.20
    narrative: 0.25
    momentum: 0.15
    community: 0.10
  top_n: 10

notifications:
  discord_webhook_url: ${DISCORD_WEBHOOK_URL}
  notion_api_key: ${NOTION_API_KEY}
```

---

## 6. スケジューリング戦略

```
ジョブ一覧:
  ┌──────────────────┬───────────┬──────────────────────────┐
  │ ジョブ            │ 頻度      │ 説明                      │
  ├──────────────────┼───────────┼──────────────────────────┤
  │ discovery_run    │ 4時間毎    │ L1 → L2 を実行            │
  │ security_scan    │ 6時間毎    │ L3 を未スキャン分に実行      │
  │ deep_analysis    │ 12時間毎   │ L4 + L5 を実行（AI利用）    │
  │ daily_report     │ 1日1回     │ L6 を実行、レポート生成      │
  │ waitlist_check   │ 1時間毎    │ wait_list の冷却完了分を再投入│
  │ cleanup          │ 1週間毎    │ 30日以上前のdropデータ削除   │
  └──────────────────┴───────────┴──────────────────────────┘
```

L1–L2（APIコールのみ）は高頻度で回し、
L4–L5（Claude API利用）はコスト考慮で低頻度にする。

---

## 7. データフロー図

```
                    外部API群
                 ┌─────────────┐
                 │GeckoTerminal│
                 │DEX Screener │
                 │GoPlus       │
                 │GitHub       │
                 │CoinGecko    │
                 └──────┬──────┘
                        │
    ┌───────────────────▼───────────────────┐
    │            API Client Layer            │
    │  rate_limiter + retry + fallback       │
    └───────────────────┬───────────────────┘
                        │ RawToken / APIResponse
    ┌───────────────────▼───────────────────┐
    │          Pipeline Layers (L1–L6)       │
    │                                        │
    │  L1 ──▶ L2 ──▶ L3 ──▶ L4 ──▶ L5 ──▶ L6│
    │         │drop   │drop                  │
    │         ▼       ▼                      │
    │      (除外)   (除外)                    │
    └───────────────────┬───────────────────┘
                        │ ScoredToken
    ┌───────────────────▼───────────────────┐
    │           SQLite Database              │
    │  tokens / pools / scan_results /       │
    │  daily_rankings / wait_list            │
    └───────────────────┬───────────────────┘
                        │
    ┌───────────────────▼───────────────────┐
    │          Notification Layer            │
    │     Discord Webhook / Notion API       │
    └───────────────────────────────────────┘
```

---

## 8. MVP 開発ロードマップ

```
Phase 1 (Week 1–2): 基盤 + L1 + L2
  - プロジェクトセットアップ、DB初期化
  - GeckoTerminal / DEX Screener クライアント実装
  - Pre-filter ロジック実装
  - 動作確認: 候補リストが正しく生成されるか

Phase 2 (Week 3): L3 Security
  - GoPlus クライアント実装
  - スコアリングロジック実装
  - 動作確認: 既知のハニーポットが正しく排除されるか

Phase 3 (Week 4): L4 + L5 (AI統合)
  - GitHub クライアント実装
  - Claude API 統合（プロンプト設計 + JSON出力パース）
  - Sentiment スコアリング実装

Phase 4 (Week 5): L6 + 通知 + 運用開始
  - ランキングロジック + レポート生成
  - Discord Webhook 連携
  - スケジューラ設定
  - 1週間の試験運用 → 閾値チューニング
```

---

## 9. 将来の拡張ポイント

| 項目 | 概要 |
|---|---|
| PostgreSQL 移行 | データ量増加時に SQLite → PostgreSQL へ切替 |
| Web ダッシュボード | Streamlit or Next.js でリアルタイム閲覧 |
| バックテスト機能 | 過去のランキングと実際の価格推移を突合し、重みを最適化 |
| マルチチェーン拡張 | Avalanche, Polygon, Sui 等の追加 |
| 有料API統合 | Nansen, Arkham, Dune Analytics 等でオンチェーン分析強化 |
| アラート機能 | 特定条件（急騰、LP解除等）でリアルタイム通知 |
