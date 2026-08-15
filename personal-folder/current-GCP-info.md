# 現在のGCP設定情報

確認日時: 2026-08-15（JST）  
確認方法: `gcloud`の参照系コマンドのみ  
対象プロジェクト: `gcp-cloud-incident-platform`

> GCP上の設定変更、API登録、リソース作成・削除は行っていません。  
> パスワードやSecretの内容は記載していません。

## 1. 基本設定

| 項目 | 現在値 |
|---|---|
| アクティブアカウント | `adachiitsukiyishu@gmail.com` |
| プロジェクトID | `gcp-cloud-incident-platform` |
| プロジェクト番号 | `888088780947` |
| Cloud Run既定リージョン | `asia-northeast1` |

## 2. システム全体の稼働状況

| コンポーネント | 状態 | 現在の役割 |
|---|---|---|
| Incident API | Ready | チケットAPIとPub/Sub Publish |
| Pub/Sub | 設定済み | `ticket_id`をWorkerへ配信 |
| AI Worker | Ready | Geminiでチケットを解析 |
| Cloud SQL | RUNNABLE | チケットと解析結果を保存 |
| Vertex AI | API有効 | Geminiモデルを呼び出し |

確認できた処理経路は次のとおりです。

```text
Client → Incident API → Cloud SQL
                     → Pub/Sub → AI Worker → Vertex AI
                                           → Cloud SQL
```

## 3. Cloud Run

### 3.1 Incident API

| 項目 | 現在値 |
|---|---|
| サービス名 | `incident-platform` |
| 状態 | Ready |
| 現行リビジョン | `incident-platform-00004-v69` |
| トラフィック | 現行リビジョンへ100% |
| 公開URL | `https://incident-platform-888088780947.asia-northeast1.run.app` |
| Cloud Run URL | `https://incident-platform-yaz57no2da-an.a.run.app` |
| 認証 | `allUsers`に`roles/run.invoker` |
| サービスアカウント | `incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com` |
| タイムアウト | 300秒 |
| 最大インスタンス数 | 20 |
| Ingress | all |

環境変数は次のとおりです。

| 変数 | 現在値 |
|---|---|
| `APP_ENV` | `production` |
| `GOOGLE_CLOUD_PROJECT` | `gcp-cloud-incident-platform` |
| `PUBSUB_TOPIC` | `incident-tickets` |
| `DATABASE_URL` | Secret `incident-database-url` のversion 2 |

### 3.2 AI Worker

| 項目 | 現在値 |
|---|---|
| サービス名 | `incident-worker` |
| 状態 | Ready |
| 現行リビジョン | `incident-worker-00002-sgk` |
| トラフィック | 現行リビジョンへ100% |
| URL | `https://incident-worker-yaz57no2da-an.a.run.app` |
| 呼び出し元 | Pub/Sub Push専用IAM |
| サービスアカウント | `incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com` |
| 起動コマンド | `uvicorn incident_platform.worker:app --host 0.0.0.0 --port 8080` |
| タイムアウト | 600秒 |
| 最大インスタンス数 | 20 |
| Ingress | all |

環境変数は次のとおりです。

| 変数 | 現在値 |
|---|---|
| `APP_ENV` | `production` |
| `GOOGLE_CLOUD_PROJECT` | `gcp-cloud-incident-platform` |
| `GOOGLE_CLOUD_LOCATION` | `global` |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` |
| `DATABASE_URL` | Secret `incident-database-url` のlatest |

## 4. Cloud SQL

| 項目 | 現在値 |
|---|---|
| インスタンス名 | `incident-db` |
| 状態 | RUNNABLE |
| DBエンジン | PostgreSQL 17 |
| リージョン / ゾーン | `asia-northeast1` / `asia-northeast1-b` |
| 接続名 | `gcp-cloud-incident-platform:asia-northeast1:incident-db` |
| マシンタイプ | `db-f1-micro` |
| 可用性 | ZONAL |
| ストレージ | SSD 10 GB |
| 自動拡張 | 有効 |
| 起動設定 | ALWAYS |
| バックアップ | 無効 |
| Public IP | `35.200.23.77` |
| SSL設定 | 暗号化・非暗号化を許可 |

登録データベースは`incidents`と`postgres`です。  
登録ユーザーは`incident`と`postgres`です。パスワードは確認・記載していません。

## 5. Pub/Sub

### 5.1 Schema

| 項目 | 現在値 |
|---|---|
| Schema名 | `incident-ticket-v1` |
| 種類 | AVRO |
| Revision ID | `60b59c92` |

### 5.2 Topics

| Topic | Schema / 用途 | 保存リージョン | CMEK |
|---|---|---|---|
| `incident-tickets` | `incident-ticket-v1`、JSON | `asia-northeast1` | 未設定 |
| `incident-tickets-dead-letter` | 配信失敗メッセージ | `asia-northeast1` | 未設定 |

### 5.3 Subscriptions

#### `incident-tickets-worker`

| 項目 | 現在値 |
|---|---|
| 配信方式 | Push |
| Push先 | `https://incident-worker-yaz57no2da-an.a.run.app/pubsub/tickets` |
| OIDCサービスアカウント | `pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com` |
| OIDC Audience | `https://incident-worker-yaz57no2da-an.a.run.app` |
| Ack期限 | 600秒 |
| Retry | 最短10秒、最長600秒 |
| Dead Letter Topic | `incident-tickets-dead-letter` |
| 最大配信回数 | 5回 |
| メッセージ保持 | 7日 |
| Subscription期限 | なし |

#### `incident-tickets-dead-letter-monitor`

Dead Letter Topicを確認するPull Subscriptionです。メッセージ保持は7日、Subscription期限はありません。

## 6. IAMとサービスアカウント

| 対象 | Principal | Role |
|---|---|---|
| プロジェクト | `incident-worker-run@...` | `roles/aiplatform.user` |
| プロジェクト | `incident-worker-run@...` | `roles/cloudsql.client` |
| プロジェクト | `incident-platform-run@...` | `roles/cloudsql.client` |
| プロジェクト | Pub/Sub Service Agent | `roles/iam.serviceAccountTokenCreator` |
| Topic `incident-tickets` | `incident-platform-run@...` | `roles/pubsub.publisher` |
| Dead Letter Topic | Pub/Sub Service Agent | `roles/pubsub.publisher` |
| Worker Subscription | Pub/Sub Service Agent | `roles/pubsub.subscriber` |
| Cloud Run Worker | `pubsub-push-invoker@...` | `roles/run.invoker` |
| Secret | API / Workerの各SA | `roles/secretmanager.secretAccessor` |

登録済みの用途別サービスアカウントは次のとおりです。

- `incident-platform-run`: Incident API用
- `incident-worker-run`: AI Worker用
- `pubsub-push-invoker`: Pub/Sub Push認証用
- `888088780947-compute`: Default Compute用

すべて有効です。

## 7. Secret Manager

| 項目 | 現在値 |
|---|---|
| Secret名 | `incident-database-url` |
| Replication | automatic |
| 有効Version | 1、2 |
| API参照Version | 2 |
| Worker参照Version | latest |

Secretの実データは読み取っていません。

## 8. 有効なAPI

現在有効なAPIは次の32件です。

- `aiplatform.googleapis.com`
- `analyticshub.googleapis.com`
- `artifactregistry.googleapis.com`
- `bigquery.googleapis.com`
- `bigqueryconnection.googleapis.com`
- `bigquerydatapolicy.googleapis.com`
- `bigquerydatatransfer.googleapis.com`
- `bigquerymigration.googleapis.com`
- `bigqueryreservation.googleapis.com`
- `bigquerystorage.googleapis.com`
- `cloudapis.googleapis.com`
- `cloudbuild.googleapis.com`
- `cloudtrace.googleapis.com`
- `containerregistry.googleapis.com`
- `dataform.googleapis.com`
- `dataplex.googleapis.com`
- `datastore.googleapis.com`
- `iam.googleapis.com`
- `iamcredentials.googleapis.com`
- `logging.googleapis.com`
- `monitoring.googleapis.com`
- `pubsub.googleapis.com`
- `run.googleapis.com`
- `secretmanager.googleapis.com`
- `servicemanagement.googleapis.com`
- `serviceusage.googleapis.com`
- `sql-component.googleapis.com`
- `sqladmin.googleapis.com`
- `storage-api.googleapis.com`
- `storage-component.googleapis.com`
- `storage.googleapis.com`
- `telemetry.googleapis.com`

`cloudkms.googleapis.com`は有効化されていません。現在のPub/Sub TopicにもCMEKは設定されていません。

## 9. Buildとデプロイ

| 対象 | 最新Build ID | 結果 |
|---|---|---|
| Incident API | `6a64729f-56c1-42a8-bb08-ef6d939ae43e` | SUCCESS |
| AI Worker | `8ed82fd5-29c0-42fb-b0fd-747bf8e779e1` | SUCCESS |

どちらもCloud Buildによるソースデプロイで、Artifact Registryの`cloud-run-source-deploy`へコンテナが保存されています。

## 10. 実行状況

Cloud Loggingで次の成功を確認しました。時刻はUTCです。

| 時刻 | サービス | リクエスト | 結果 |
|---|---|---|---|
| 2026-08-15 09:52:37 | Incident API | `POST /tickets` | HTTP 201 |
| 2026-08-15 09:52:38 | AI Worker | `POST /pubsub/tickets` | HTTP 204 |
| 2026-08-15 09:53:10 | Incident API | チケット取得 | HTTP 200 |
| 2026-08-15 09:51:54 | Incident API | `/docs`、`/openapi.json` | HTTP 200 |

このログから、チケット登録、Pub/Sub Push、Worker処理、結果取得まで動作したことを確認できます。

現行リビジョンを対象に直近12時間の`ERROR`以上を確認した結果、該当ログはありませんでした。

過去のリビジョンには、Cloud SQL停止中、DBパスワード不一致、localhost接続による起動失敗が記録されています。現在はいずれも修正済みで、現行リビジョンはReadyです。

## 11. 現在の注意点

- Cloud SQLは`ALWAYS`のため常時稼働します。
- Cloud SQLの自動バックアップは無効です。
- Cloud SQLはPublic IPを持ちます。
- Incident APIはインターネットへ公開されています。
- AI WorkerはPub/SubのOIDC認証経由で呼び出します。
- Pub/SubのCMEK設定は未実施です。

## 12. 主な確認コマンド

今回使用したコマンドは、すべて参照系です。

```powershell
gcloud config list
gcloud auth list
gcloud services list --enabled
gcloud run services list --region=asia-northeast1
gcloud run services describe SERVICE --region=asia-northeast1
gcloud run revisions list --region=asia-northeast1
gcloud sql instances describe incident-db
gcloud sql databases list --instance=incident-db
gcloud sql users list --instance=incident-db
gcloud pubsub schemas describe incident-ticket-v1
gcloud pubsub topics list
gcloud pubsub subscriptions list
gcloud iam service-accounts list
gcloud projects get-iam-policy gcp-cloud-incident-platform
gcloud secrets describe incident-database-url
gcloud secrets versions list incident-database-url
gcloud builds list --region=asia-northeast1
gcloud logging read FILTER
```
