# GCP Cloud Incident Platform

問い合わせ・障害報告・サポートチケットを受け取るシステムです。ローカル開発に加え、Cloud Run、Cloud SQL、Pub/Sub、Vertex AIを使った非同期処理をGoogle Cloud上で実行します。

設計と現在のGCP設定は、次の資料を参照してください。

- [初期設計](architecture/initial-design.md)
- [Pub/Subアーキテクチャ](architecture/pub-sub.md)
- [現在のGCP設定](personal-folder/current-GCP-info.md)

## アーキテクチャ

```text
ユーザー
  ↓ POST /tickets
Incident API（Cloud Run）
  ├─ Cloud SQLへ保存
  └─ ticket_idをPub/SubへPublish
                 ↓
          AI Worker（Cloud Run）
            ├─ Vertex AIを呼び出す
            └─ Cloud SQLを更新
```

| GCPサービス | 用途 |
| --- | --- |
| Cloud Run | Incident APIとAI Workerを実行 |
| Cloud SQL | チケット情報を保存 |
| Pub/Sub | APIからWorkerへ処理を配信 |
| Vertex AI | Geminiモデルを呼び出す |
| Secret Manager | DB接続情報を管理 |
| Cloud Build | ソースからコンテナをビルド |
| Artifact Registry | ビルドしたコンテナを保存 |

AI Workerは一般公開せず、Pub/SubのOIDC認証を使って呼び出します。Pub/Subは最大5回まで再配信し、処理できない通知をDead Letter Topicへ送ります。

## Cloud Run

- API: <https://incident-platform-888088780947.asia-northeast1.run.app>
- APIドキュメント: <https://incident-platform-888088780947.asia-northeast1.run.app/docs>
- ヘルスチェック: <https://incident-platform-888088780947.asia-northeast1.run.app/health>

## ローカルセットアップ

前提条件：

- Python 3.11
- uv
- Git

PowerShellで次を実行します。

```powershell
docker compose up -d db
.\scripts\setup.ps1
uv run uvicorn incident_platform.main:app --reload --port 8080
```

起動後は以下を確認できます。

- APIドキュメント: <http://localhost:8080/docs>
- ヘルスチェック: <http://localhost:8080/health>

利用できるAPI：

| メソッド | エンドポイント | 内容 |
| --- | --- | --- |
| `POST` | `/tickets` | チケットを保存し、`ticket_id`をPub/SubへPublish |
| `GET` | `/tickets` | チケット一覧を新しい順で取得 |
| `GET` | `/tickets/{id}` | IDを指定してチケットを取得 |
| `GET` | `/health` | APIの稼働確認 |

## `/docs` での動作確認

1. ブラウザで <http://localhost:8080/docs> を開く。
2. `POST /tickets` を開き、「Try it out」を押す。
3. Request bodyへ次のように入力し、「Execute」を押す。

```json
{
  "title": "ログインエラー",
  "raw_question": "ログインすると500エラーになります。"
}
```

4. Response bodyに表示された実際の `id` をコピーする。

```json
{
  "id": "ここに実際のUUIDが表示されます",
  "status": "queued"
}
```

5. `GET /tickets/{ticket_id}` を開き、「Try it out」を押す。
6. `ticket_id` にコピーした `id` を貼り付け、「Execute」を押す。
7. Response bodyに登録内容が表示されることを確認する。

`3fa85f64-5717-4562-b3fc-2c963f66afa6` など、画面に最初から表示されるサンプルUUIDでは登録データを取得できません。必ず `POST /tickets` のResponse bodyに返された `id` を使用してください。

登録済みチケットとIDの一覧は、`GET /tickets` の「Execute」から確認できます。

## Cloud Runでの動作確認

1. <https://incident-platform-888088780947.asia-northeast1.run.app/docs> を開く。
2. `POST /tickets`を実行し、Response bodyの`id`をコピーする。
3. 数秒待ってから`GET /tickets/{ticket_id}`へ`id`を入力する。
4. HTTP `200`で登録内容を取得できることを確認する。

APIとWorkerのリクエストは、次のコマンドで確認できます。

```powershell
gcloud run services logs read incident-platform --region=asia-northeast1 --limit=20
gcloud run services logs read incident-worker --region=asia-northeast1 --limit=20
```

## Docker Compose

Docker Desktopを起動し、状態を確認します。

```powershell
docker desktop status
```

`running`と表示されたら、プロジェクトフォルダで次を実行します。PostgreSQL、Pub/Sub Emulator、Worker、APIが起動し、TopicとPush Subscriptionが自動作成されます。

```powershell
docker compose up --build
```

バックグラウンドで起動する場合は、次を実行します。

```powershell
docker compose up --build -d
```

| サービス | URL・ポート |
| --- | --- |
| API | <http://localhost:8080> |
| Worker | <http://localhost:8081> |
| Pub/Sub Emulator | `localhost:8085` |
| PostgreSQL | `localhost:5432` |

起動状態は次のコマンドで確認します。

```powershell
docker compose ps
```

APIドキュメントの`POST /tickets`を実行後、`GET /tickets/{ticket_id}`で`status`が`completed`になることを確認します。ローカルWorkerはVertex AIを呼び出さず、固定の分析結果を保存します。

ログを確認する場合は、次を実行します。

```powershell
docker compose logs -f api worker pubsub
```

停止時は次を実行します。PostgreSQLのデータは保持されます。

```powershell
docker compose down
```

ローカルデータを削除する場合は、次を実行します。

```powershell
docker compose down --volumes
```

## GCPへのデプロイ

以下は、Cloud SQL、Secret、Pub/Sub、IAMが設定済みの環境を更新するコマンドです。初回のPub/Sub設定は[Pub/Subアーキテクチャ](architecture/pub-sub.md)を参照してください。

Incident APIをデプロイします。

```powershell
gcloud run deploy incident-platform `
  --source . `
  --region=asia-northeast1 `
  --service-account=incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com `
  --add-cloudsql-instances=gcp-cloud-incident-platform:asia-northeast1:incident-db `
  --set-secrets=DATABASE_URL=incident-database-url:2 `
  --set-env-vars=APP_ENV=production,GOOGLE_CLOUD_PROJECT=gcp-cloud-incident-platform,PUBSUB_TOPIC=incident-tickets `
  --allow-unauthenticated
```

AI Workerをデプロイします。

```powershell
gcloud run deploy incident-worker `
  --source . `
  --region=asia-northeast1 `
  --service-account=incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com `
  --add-cloudsql-instances=gcp-cloud-incident-platform:asia-northeast1:incident-db `
  --set-secrets=DATABASE_URL=incident-database-url:latest `
  --set-env-vars=APP_ENV=production,GOOGLE_CLOUD_PROJECT=gcp-cloud-incident-platform,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-2.5-flash-lite `
  --command=uvicorn `
  --args=incident_platform.worker:app,--host,0.0.0.0,--port,8080 `
  --timeout=600 `
  --no-allow-unauthenticated
```

## 環境変数

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL接続先 |
| `GOOGLE_CLOUD_PROJECT` | Vertex AIとPub/Subのプロジェクト |
| `GOOGLE_CLOUD_LOCATION` | Geminiの呼び出し場所 |
| `GEMINI_MODEL` | 使用するGeminiモデル |
| `PUBSUB_TOPIC` | Publish先のTopic |

`.env`やSecretの実値はGitへ登録しないでください。

## GCPトラブルシューティング

Cloud Runの状態を確認します。

```powershell
gcloud run services describe incident-platform --region=asia-northeast1
gcloud run services describe incident-worker --region=asia-northeast1
```

Pub/Subの配信設定を確認します。

```powershell
gcloud pubsub subscriptions describe incident-tickets-worker
gcloud pubsub subscriptions describe incident-tickets-dead-letter-monitor
```

Cloud SQLの稼働状態を確認します。

```powershell
gcloud sql instances describe incident-db --format="value(state)"
```

## 開発用コマンド

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`.env.example` を `.env` にコピーし、ローカル固有値を設定してください。`.env` と認証情報はGit管理対象外です。
