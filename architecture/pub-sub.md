# Pub/Sub アーキテクチャ設計書

## 1. 簡易的なアーキテクチャとPub/Subの役割

このシステムでは **Many-to-one Pattern** を採用します。FastAPIなどのPublisherが、1つのTopic `incident-tickets` へチケット処理イベントを送ります。

Pub/SubはFastAPIとAI Workerをつなぐ仲介役です。チケット登録APIはAI処理の完了を待たずに応答できるため、それぞれの処理を分けて管理できます。

```text
ユーザー
  ↓ POST /tickets
FastAPI（Cloud Run / Publisher）
  ├─ Cloud SQLへチケットを queued で保存
  └─ ticket_idをPub/SubへPublish
                 ↓
       incident-tickets Topic
                 ↓
       Push Subscription
                 ↓ HTTPS + OIDC
AI Worker（Cloud Run / Subscriber）
  ├─ Cloud SQLからチケットを取得
  ├─ AI処理を実行
  └─ Cloud SQLを completed / failed に更新
```

Subscriptionは **Push方式** を使います。Pub/SubがCloud Run WorkerのHTTPSエンドポイントを呼び出すため、Worker側に常駐するPull処理は必要ありません。未使用時はCloud Runをスケールゼロにできます。

## 2. 用語まとめ

| 用語 | このシステムでの役割 |
| --- | --- |
| Publisher | FastAPIです。DB保存後にチケット処理イベントを送ります。 |
| Topic | `incident-tickets`です。Publisherからイベントを受け取ります。 |
| Schema | `incident-ticket-v1`です。Avro形式でメッセージを検証します。 |
| Subscription | `incident-tickets-worker`です。TopicとWorkerをつなぎます。 |
| Push Subscriber | Cloud Runの `incident-worker`です。HTTPSで通知を受け取ります。 |
| ACK | WorkerがHTTP `2xx`を返し、処理成功を知らせます。 |
| NACK | Workerが非`2xx`を返すかタイムアウトし、再配信の対象になります。 |
| Retry Policy | 一時的な障害時に指数バックオフで再配信します。 |
| Dead-letter Topic | `incident-tickets-dead-letter`です。繰り返し失敗した通知を隔離します。 |
| Service Account | Publisher、Worker、Push呼び出し元の実行IDです。 |
| OIDC | Pub/Subから非公開Workerを呼び出す認証方式です。 |
| CMEK | Cloud KMSで管理する暗号鍵です。必要な環境だけで使います。 |

## 3. アーキテクチャ

### 3.1 構成要素

| リソース | 名前 | 説明 |
| --- | --- | --- |
| Publisher | `incident-platform` | `POST /tickets`のDB保存後にPublishします。 |
| Publisher SA | `incident-platform-run` | Topicの`roles/pubsub.publisher`だけを付与します。 |
| Schema | `incident-ticket-v1` | チケット処理イベントの形式を検証します。 |
| Main Topic | `incident-tickets` | 通常のチケットイベントを保持します。 |
| Push Subscription | `incident-tickets-worker` | 認証付きPushでWorkerへ配信します。 |
| Worker | `incident-worker` | AI処理を行い、Cloud SQLを更新します。 |
| Worker SA | `incident-worker-run` | Cloud SQL、Vertex AI、Secretへアクセスします。 |
| Push Auth SA | `pubsub-push-invoker` | Workerを呼び出す権限を持ちます。 |
| Dead-letter Topic | `incident-tickets-dead-letter` | 配信に繰り返し失敗した通知を受け取ります。 |
| DLQ Subscription | `incident-tickets-dead-letter-monitor` | 障害調査用にDead-letter通知を保持します。 |

### 3.2 処理フロー

1. FastAPIがリクエスト内容を検証します。
2. Cloud SQLへチケットを`queued`で保存し、DBへ確定します。
3. Publisherが`ticket_id`を含むイベントをPublishします。
4. Pub/SubがSchemaを確認し、Topicへ保存します。
5. Push SubscriptionがOIDC認証付きでWorkerへ通知します。
6. Workerが`ticket_id`を使ってCloud SQLからチケットを取得します。
7. Workerが状態を`processing`へ変更し、AI処理を実行します。
8. 成功時は結果と`completed`をCloud SQLへ保存します。
9. WorkerがHTTP `2xx`を返すとACKになります。非`2xx`やタイムアウト時は再配信されます。
10. 配信失敗が約5回続くと、Dead-letter Topicへ転送されます。

### 3.3 メッセージ設計

Pub/Subには問い合わせ本文を入れず、Cloud SQL上の識別子だけを送ります。これにより、個人情報を複数の場所へ保存することを避けます。

```json
{
  "schema_version": "1",
  "event_id": "イベントごとのUUID",
  "event_type": "ticket.created",
  "ticket_id": "Cloud SQLに保存したチケットUUID",
  "created_at": "2026-08-15T12:00:00Z"
}
```

Pub/Subはat-least-once配信のため、同じ通知が複数回届くことがあります。Workerはチケットの現在状態を確認し、`completed`のチケットを重複処理しません。

DB確定後にPublishが失敗した場合、Publisherは最大10秒間、指数バックオフで再試行します。最後まで失敗した場合は、チケットを`queued`のまま残し、APIはHTTP `503`を返します。

### 3.4 スキーマ

AvroとJSONエンコーディングを使います。Schemaはメッセージの`data`を検証します。Pub/Sub属性は検証の対象外です。

```json
{
  "type": "record",
  "name": "TicketQueued",
  "namespace": "incident_platform.events",
  "fields": [
    { "name": "schema_version", "type": "string", "default": "1" },
    { "name": "event_id", "type": "string" },
    { "name": "event_type", "type": "string" },
    { "name": "ticket_id", "type": "string" },
    { "name": "created_at", "type": "string" }
  ]
}
```

### 3.5 Subscription方式

| 方式 | 採否 | 理由 |
| --- | --- | --- |
| Push | 採用 | HTTPSリクエストでCloud Runを起動でき、常駐処理が不要です。 |
| Pull | 不採用 | 常駐Subscriberが必要です。CLIでの一時確認にだけ使います。 |
| BigQuery / Cloud Storage | 不採用 | 今回は分析や保存ではなく、Workerで処理するためです。 |

### 3.6 IAM方針

- `incident-platform-run`には、Main Topicの`roles/pubsub.publisher`だけを付与します。
- `pubsub-push-invoker`には、Workerの`roles/run.invoker`を付与します。
- `incident-worker-run`には、`roles/cloudsql.client`、`roles/aiplatform.user`、必要なSecretの`roles/secretmanager.secretAccessor`を付与します。
- Pub/Sub Service Agentには、OIDCトークン作成用の`roles/iam.serviceAccountTokenCreator`を付与します。
- Dead-letter処理用に、Pub/Sub Service AgentへDLQ TopicのPublisher権限とMain SubscriptionのSubscriber権限を付与します。
- アプリケーション用Service AccountへOwnerやEditorは付与しません。

### 3.7 再試行とエラー処理

- ACK deadlineは`600秒`です。
- Retryは`10秒`から`600秒`の指数バックオフです。
- Maximum delivery attemptsは`5回`です。回数はPub/Subによる概算値です。
- Message retentionは`7日`です。
- Workerは一時障害時に非`2xx`を返します。処理済みまたは成功時は`2xx`を返します。

### 3.8 暗号化方針

- 通信にはHTTPSを使います。
- 保存メッセージはGoogle管理鍵で暗号化されます。
- 規制や組織要件がある場合だけCMEKへ切り替えます。
- CMEKを使う場合は、Main TopicとDead-letter Topicの両方へ設定します。

## 4. 設定 gcloud CLI command

以下のコマンドはWindows PowerShell向けです。上から一つずつ実行してください。名前はすべて直接指定しているため、PowerShellを再起動しても空変数によるエラーは発生しません。

既に存在するリソースを作成すると`ALREADY_EXISTS`になります。「初回のみ」と書かれた作成コマンドは、リソースがない場合だけ実行してください。

既存の`scripts/gcloud-bootstrap.ps1`と`scripts/gcloud-bootstrap.sh`は、SchemaなしのTopicとPull Subscriptionを作成します。更新するまではPub/Sub部分を実行しません。

### 4.1 プロジェクトとAPI

作業するプロジェクトを選びます。

```powershell
gcloud config set project gcp-cloud-incident-platform
```

Pub/Sub APIを有効にします。

```powershell
gcloud services enable pubsub.googleapis.com
```

Cloud Run APIを有効にします。

```powershell
gcloud services enable run.googleapis.com
```

IAM APIを有効にします。

```powershell
gcloud services enable iam.googleapis.com
```

### 4.2 スキーマの定義・検証・作成

PowerShellでJSONを安全に扱うため、Avro定義をファイルへ保存します。

Schemaファイルを作成します。

```powershell
@'
{
  "type": "record",
  "name": "TicketQueued",
  "namespace": "incident_platform.events",
  "fields": [
    { "name": "schema_version", "type": "string", "default": "1" },
    { "name": "event_id", "type": "string" },
    { "name": "event_type", "type": "string" },
    { "name": "ticket_id", "type": "string" },
    { "name": "created_at", "type": "string" }
  ]
}
'@ | Set-Content -Path .\incident-ticket-v1.avsc -Encoding ascii
```

Schemaの文法を検証します。

```powershell
gcloud pubsub schemas validate-schema `
  --type=avro `
  --definition-file=.\incident-ticket-v1.avsc
```

初回のみSchemaを作成します。

```powershell
gcloud pubsub schemas create incident-ticket-v1 `
  --type=avro `
  --definition-file=.\incident-ticket-v1.avsc
```

### 4.3 Topicの作成とスキーマのアタッチ

初回のみMain Topicを作ります。

```powershell
gcloud pubsub topics create incident-tickets `
  --schema=incident-ticket-v1 `
  --message-encoding=json `
  --message-storage-policy-allowed-regions=asia-northeast1
```

初回のみDead-letterを作ります。

```powershell
gcloud pubsub topics create incident-tickets-dead-letter `
  --message-storage-policy-allowed-regions=asia-northeast1
```

既存TopicへSchemaを設定します。

```powershell
gcloud pubsub topics update incident-tickets `
  --schema=incident-ticket-v1 `
  --message-encoding=json
```

新規作成時はSchemaを設定済みのため、最後の更新コマンドは省略できます。

### 4.4 Publisher権限

FastAPIはGoogle CloudのApplication Default Credentialsを使ってPublishします。Service Account鍵ファイルは作成しません。

Publisher権限を付与します。

```powershell
gcloud pubsub topics add-iam-policy-binding incident-tickets `
  --member="serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/pubsub.publisher"
```

アプリケーションは `projects/gcp-cloud-incident-platform/topics/incident-tickets`へ、DB確定後にPublishします。

### 4.5 WorkerとPush認証用Service Account

既存Service Accountの作成は省略してください。このプロジェクトでは両方とも作成済みです。

Worker SAを確認します。

```powershell
gcloud iam service-accounts describe incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com
```

未作成時だけWorker SAを作ります。

```powershell
gcloud iam service-accounts create incident-worker-run `
  --display-name="Incident AI Worker"
```

Push SAを確認します。

```powershell
gcloud iam service-accounts describe pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com
```

未作成時だけPush SAを作ります。

```powershell
gcloud iam service-accounts create pubsub-push-invoker `
  --display-name="Pub/Sub Push Invoker"
```

Push SAを操作可能にします。

```powershell
gcloud iam service-accounts add-iam-policy-binding pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com `
  --member="user:adachiitsukiyishu@gmail.com" `
  --role="roles/iam.serviceAccountUser"
```

WorkerへDB接続権限を付けます。

```powershell
gcloud projects add-iam-policy-binding gcp-cloud-incident-platform `
  --member="serviceAccount:incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/cloudsql.client" `
  --condition=None
```

WorkerへSecret権限を付けます。

```powershell
gcloud secrets add-iam-policy-binding incident-database-url `
  --member="serviceAccount:incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

WorkerへVertex権限を付けます。

```powershell
gcloud projects add-iam-policy-binding gcp-cloud-incident-platform `
  --member="serviceAccount:incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/aiplatform.user" `
  --condition=None
```

Pub/SubへToken権限を付けます。

```powershell
gcloud projects add-iam-policy-binding gcp-cloud-incident-platform `
  --member="serviceAccount:service-888088780947@gcp-sa-pubsub.iam.gserviceaccount.com" `
  --role="roles/iam.serviceAccountTokenCreator" `
  --condition=None
```

### 4.6 Cloud Run Workerの前提

`incident-worker`は次の条件でデプロイします。

- 非公開のCloud Runサービスにします。
- `POST /pubsub/tickets`を使います。
- 実行Service Accountは`incident-worker-run`です。
- Cloud SQLと`incident-database-url` Secretを設定します。
- Geminiは`gemini-2.5-flash-lite`を`global`から呼び出します。
- リクエストタイムアウトは`600秒`です。

Worker URLを確認します。

```powershell
gcloud run services describe incident-worker `
  --region=asia-northeast1 `
  --format="value(status.url)"
```

Push SAへInvokerを付けます。

```powershell
gcloud run services add-iam-policy-binding incident-worker `
  --region=asia-northeast1 `
  --member="serviceAccount:pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/run.invoker"
```

### 4.7 Push SubscriptionとDead-letter設定

このプロジェクトのWorker URLは`https://incident-worker-yaz57no2da-an.a.run.app`です。Workerを作り直した場合は、4.6で表示されたURLへ読み替えてください。

初回のみPush Subscriptionを作ります。

```powershell
gcloud pubsub subscriptions create incident-tickets-worker `
  --topic=incident-tickets `
  --push-endpoint="https://incident-worker-yaz57no2da-an.a.run.app/pubsub/tickets" `
  --push-auth-service-account="pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --push-auth-token-audience="https://incident-worker-yaz57no2da-an.a.run.app" `
  --ack-deadline=600 `
  --min-retry-delay=10s `
  --max-retry-delay=600s `
  --dead-letter-topic=incident-tickets-dead-letter `
  --max-delivery-attempts=5 `
  --message-retention-duration=7d `
  --expiration-period=never
```

初回のみDLQ Subscriptionを作ります。

```powershell
gcloud pubsub subscriptions create incident-tickets-dead-letter-monitor `
  --topic=incident-tickets-dead-letter `
  --message-retention-duration=7d `
  --expiration-period=never
```

Pub/SubへDLQ送信権限を付けます。

```powershell
gcloud pubsub topics add-iam-policy-binding incident-tickets-dead-letter `
  --member="serviceAccount:service-888088780947@gcp-sa-pubsub.iam.gserviceaccount.com" `
  --role="roles/pubsub.publisher"
```

Pub/Subへ再配信権限を付けます。

```powershell
gcloud pubsub subscriptions add-iam-policy-binding incident-tickets-worker `
  --member="serviceAccount:service-888088780947@gcp-sa-pubsub.iam.gserviceaccount.com" `
  --role="roles/pubsub.subscriber"
```

### 4.8 スキーマとPublishの動作確認

PowerShellによるJSON引用符の変換を避けるため、`--flags-file`を使います。

テストメッセージを保存します。

```powershell
@'
--message: >-
  {"schema_version":"1","event_id":"11111111-1111-1111-1111-111111111111","event_type":"ticket.created","ticket_id":"22222222-2222-2222-2222-222222222222","created_at":"2026-08-15T12:00:00Z"}
'@ | Set-Content -Path .\pubsub-message-flags.yaml -Encoding ascii
```

メッセージ形式を検証します。

```powershell
gcloud pubsub schemas validate-message `
  --schema-name=incident-ticket-v1 `
  --message-encoding=json `
  --flags-file=.\pubsub-message-flags.yaml
```

テスト通知をPublishします。

```powershell
gcloud pubsub topics publish incident-tickets `
  --flags-file=.\pubsub-message-flags.yaml
```

テスト用`ticket_id`はCloud SQLに存在しないため、WorkerのDB処理は404になります。このPublishはSchemaと配信経路の確認用です。

### 4.9 Pull方式での一時確認

Push Subscriptionとは別に、一時的なPull Subscriptionを作ります。確認が終わったら削除します。

初回のみDebug Subscriptionを作ります。

```powershell
gcloud pubsub subscriptions create incident-tickets-debug `
  --topic=incident-tickets `
  --expiration-period=1d
```

Debug用通知をPublishします。

```powershell
gcloud pubsub topics publish incident-tickets `
  --flags-file=.\pubsub-message-flags.yaml
```

通知を受信してACKします。

```powershell
gcloud pubsub subscriptions pull incident-tickets-debug `
  --limit=10 `
  --auto-ack
```

Debug Subscriptionを削除します。

```powershell
gcloud pubsub subscriptions delete incident-tickets-debug
```

### 4.10 CMEKを使用する場合のみ

通常はGoogle管理鍵を使います。規制や組織要件でCMEKが必要な場合だけ、以下を一つずつ実行します。Cloud KMSには追加料金が発生します。

Cloud KMS APIを有効にします。

```powershell
gcloud services enable cloudkms.googleapis.com
```

初回のみKey Ringを作ります。

```powershell
gcloud kms keyrings create incident-pubsub `
  --location=asia-northeast1
```

初回のみ暗号鍵を作ります。

```powershell
gcloud kms keys create pubsub-messages `
  --location=asia-northeast1 `
  --keyring=incident-pubsub `
  --purpose=encryption
```

Pub/Subへ暗号鍵権限を付けます。

```powershell
gcloud kms keys add-iam-policy-binding pubsub-messages `
  --location=asia-northeast1 `
  --keyring=incident-pubsub `
  --member="serviceAccount:service-888088780947@gcp-sa-pubsub.iam.gserviceaccount.com" `
  --role="roles/cloudkms.cryptoKeyEncrypterDecrypter"
```

Main Topicへ暗号鍵を設定します。

```powershell
gcloud pubsub topics update incident-tickets `
  --topic-encryption-key="projects/gcp-cloud-incident-platform/locations/asia-northeast1/keyRings/incident-pubsub/cryptoKeys/pubsub-messages"
```

Dead-letterへ暗号鍵を設定します。

```powershell
gcloud pubsub topics update incident-tickets-dead-letter `
  --topic-encryption-key="projects/gcp-cloud-incident-platform/locations/asia-northeast1/keyRings/incident-pubsub/cryptoKeys/pubsub-messages"
```

### 4.11 設定確認

最後に、作成したリソースを一つずつ確認します。

Schemaを確認します。

```powershell
gcloud pubsub schemas describe incident-ticket-v1
```

Main Topicを確認します。

```powershell
gcloud pubsub topics describe incident-tickets
```

Push Subscriptionを確認します。

```powershell
gcloud pubsub subscriptions describe incident-tickets-worker
```

DLQ Subscriptionを確認します。

```powershell
gcloud pubsub subscriptions describe incident-tickets-dead-letter-monitor
```

### 4.12 Pub/Sub Emulatorの導入

Pub/Sub EmulatorをGoogle Cloud CLIへ追加します。Composeでは公式Emulatorイメージを使うため、この操作はCLIで直接起動して学習する場合だけ実行します。

```powershell
gcloud components install pubsub-emulator
```

### 4.13 Pub/Sub Emulatorの起動

ローカル専用プロジェクト名を指定してEmulatorを起動します。実在するGoogle Cloudプロジェクトは使用しません。

```powershell
gcloud beta emulators pubsub start `
  --project=local-project `
  --host-port=127.0.0.1:8085
```

### 4.14 Pub/Sub Emulatorの接続設定確認

Emulatorを起動したまま別のPowerShellで、必要な環境変数を表示します。

```powershell
gcloud beta emulators pubsub env-init
```

Composeでは`PUBSUB_EMULATOR_HOST=pubsub:8085`を設定します。TopicとPush SubscriptionはPythonクライアントで自動作成します。Emulatorは`gcloud pubsub`コマンドに対応しないため、Topic作成には使用しません。

## 参考資料

- [gcloud Pub/Subリファレンス](https://docs.cloud.google.com/sdk/gcloud/reference/pubsub)
- [Pub/Sub IAMアクセス制御](https://docs.cloud.google.com/pubsub/docs/access-control?hl=ja)
- [スキーマとTopicの関連付け](https://docs.cloud.google.com/pubsub/docs/associate-schema-topic)
- [Push Subscription認証](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions)
- [Cloud RunとPub/Sub](https://docs.cloud.google.com/run/docs/tutorials/pubsub)
- [Dead-letter Topic](https://docs.cloud.google.com/pubsub/docs/dead-letter-topics)
- [Retry Policy](https://docs.cloud.google.com/pubsub/docs/subscription-retry-policy)
- [メッセージ暗号化](https://docs.cloud.google.com/pubsub/docs/encryption?hl=ja)
- [Pub/Sub Emulator](https://docs.cloud.google.com/pubsub/docs/emulator)
