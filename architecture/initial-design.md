# Cloud-Native AI Incident & Support Triage System 基本設計書

## 1. 概要

ユーザーから送信された「問い合わせ・障害報告・サポートチケット」（以下、チケット）をクラウド上で受け取り、非同期で処理するシステムである。

AIがチケットの重要度、カテゴリ、要約を生成し、処理結果をデータベースへ保存する。

## 2. 処理例

### 2.1 ユーザー入力

| 項目 | 内容 |
| --- | --- |
| タイトル | ログインエラー |
| 問い合わせ内容 | ログインすると500エラーになります。30分前から発生しています。 |

### 2.2 AI出力

| 項目 | 内容 |
| --- | --- |
| `category` | `authentication` |
| `severity` | `high` |
| `summary` | ログイン処理で500エラーが継続発生 |

## 3. システム構成

### 3.1 使用技術

| 技術 | 用途 |
| --- | --- |
| FastAPI | APIの作成、および `/docs` でのAPI操作・確認 |
| Pydantic | データの構造化およびバリデーション |
| SQLAlchemy | PostgreSQLの操作・連携 |
| PostgreSQL | RDBMS（Relational Database Management System） |
| Docker | アプリケーションのコンテナ化 |

### 3.2 Google Cloudサービス

| サービス | 用途 |
| --- | --- |
| Cloud Run | FastAPIおよびAI Workerの実行 |
| Cloud SQL | PostgreSQLデータベースの提供 |
| Pub/Sub | チケットの非同期処理 |
| Secret Manager | AI APIで使用するシークレットの管理 |

## 4. システムワークフロー

### 4.1 全体ワークフロー

```text
ユーザー入力（自然言語）
  → FastAPI
  → Pub/Sub
  → AI処理
  → Pydantic
  → SQLAlchemy
  → Cloud SQL
  → FastAPI
  → ユーザー
```

### 4.2 チケット処理フロー

1. ユーザーがFastAPI（Cloud Run）の `POST /tickets` にチケットを送信する。
2. チケットを `status = queued` としてCloud SQLに登録する。
3. Pub/Subへチケット処理メッセージを発行する。
4. AI Worker（Cloud Run）がメッセージを受信する。
5. AI APIを呼び出し、重要度、カテゴリ、要約を生成する。
6. AIの出力をPydanticでバリデーションする。
7. SQLAlchemyを使用してCloud SQLのチケットを更新し、`status = completed` とする。
8. ユーザーが `GET /tickets/{id}` を実行し、処理結果を確認する。

### 4.3 `/docs` を使用した動作確認

FastAPIが提供する `/docs` から、次の順序で動作を確認する。

```text
POST /tickets
  ↓
GET /tickets/{id}
  ↓
結果確認
```

## 5. ステータス設計

チケットの処理状態は、次のいずれかとする。

| ステータス | 説明 |
| --- | --- |
| `queued` | 順番待ち |
| `processing` | 処理中 |
| `completed` | 処理完了 |
| `failed` | 処理失敗 |

## 6. データベース設計

### 6.1 チケット項目

| 項目名 | データ型 | 説明 |
| --- | --- | --- |
| `id` | `UUID` | データベース内の識別子 |
| `title` | `VARCHAR` | ユーザーが入力したタイトル |
| `raw_question` | `TEXT` | ユーザーから受け取った問い合わせ内容 |
| `summary` | `TEXT` | AIが問い合わせ内容を要約した文章 |
| `category` | `VARCHAR` | AIが判定した問題カテゴリ |
| `severity` | `VARCHAR` | AIが判定した問題の重要度 |
| `status` | `VARCHAR` | チケットの処理状態（`queued`、`processing`、`completed`、`failed`） |
| `created_at` | `TIMESTAMP` | 問い合わせを受け取った日時 |

## 7. API設計

### 7.1 エンドポイント一覧

| HTTPメソッド | エンドポイント | 用途 |
| --- | --- | --- |
| `POST` | `/tickets` | チケットの新規登録 |
| `GET` | `/tickets` | チケット一覧の取得 |
| `GET` | `/tickets/{id}` | 指定したチケットおよびAI処理結果の取得 |
| `GET` | `/health` | APIの稼働状態確認 |

### 7.2 チケット登録

#### リクエスト

`POST /tickets`

| 項目 | 説明 |
| --- | --- |
| `title` | チケットのタイトル |
| `raw_question` | 問い合わせ内容 |

#### 初期レスポンス

| 項目 | 説明 |
| --- | --- |
| `id` | 登録したチケットの識別子 |
| `status` | チケットの処理状態 |

### 7.3 AI処理結果の取得

`GET /tickets/{id}`

| 項目 | 説明 |
| --- | --- |
| `id` | チケットの識別子 |
| `title` | チケットのタイトル |
| `category` | AIが判定した問題カテゴリ |
| `severity` | AIが判定した問題の重要度 |
| `summary` | AIが生成した問い合わせ内容の要約 |
| `status` | チケットの処理状態 |

## 8. APIレスポンスの主要項目

| 項目 | 説明 |
| --- | --- |
| `title` | チケットのタイトル |
| `category` | 問題カテゴリ |
| `severity` | 問題の重要度 |
| `summary` | 問い合わせ内容の要約（description） |
