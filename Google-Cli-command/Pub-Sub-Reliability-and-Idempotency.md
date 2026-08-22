# Pub/Sub Reliability and Idempotency（Phase 6）

この文書は、Google Cloud学習計画のPhase 6「Pub/Sub信頼性・冪等性」を実施するための手順です。Phase 5のVPC・Private Networking完了後の構成を前提にします。

> **実施状況：2026-08-22完了** — Retry、DLQ、障害復旧、強い冪等性、再処理、Cloud Run更新、ラボ後片付けまで確認済みです。

Windows PowerShellで、コマンドを上から一つずつ実行します。各コードブロックは一操作だけにし、PowerShell変数は使いません。障害実験は本番用`incident-tickets-worker`を変更せず、専用のラボTopicとSubscriptionで行います。

## 1. 用語集

| 用語 | 意味 | このシステムでの扱い |
| --- | --- | --- |
| Event | システム内で起きた事実を表すデータ | `ticket.created`でチケット作成を通知する |
| Message | Pub/Subが配送するデータ単位 | EventをJSONにして送る |
| Publisher | MessageをTopicへ送る側 | Cloud Runの`incident-platform` |
| Topic | PublisherがMessageを送る宛先 | `incident-tickets` |
| Subscription | TopicのMessageをどのように配送するかを定義するリソース | `incident-tickets-worker` |
| Subscriber | Messageを受け取って処理する側 | Cloud Runの`incident-worker` |
| Push Subscription | Pub/SubがSubscriberのHTTPS URLを呼び出す方式 | Workerの`POST /pubsub/tickets`を呼ぶ |
| ACK | Messageの処理成功をPub/Subへ知らせること | PushではHTTP `102`、`200`、`201`、`202`、`204`がACKになる |
| NACK | Messageを再配信対象にする応答 | PushではACK以外のHTTP statusまたはtimeoutが該当する |
| Ack deadline | SubscriberがACKを返すまでPub/Subが待つ時間 | 現在の本番Subscriptionは600秒 |
| Retry | ACKされなかったMessageを再配信すること | 現在は10～600秒の指数バックオフ |
| Exponential backoff | 失敗が続くほど再試行間隔を長くする方式 | 障害中の連続呼び出しを抑える |
| Push backoff | Push失敗率に応じてPub/Subが配送速度を自動調整する仕組み | Retry Policyとは別に自動適用される |
| Dead-letter Topic | 一定回数処理できなかったMessageの隔離先 | `incident-tickets-dead-letter` |
| DLQ | Dead Letter Queueの略称 | Dead-letter Topicと監視用Subscriptionをまとめて指すことが多い |
| Delivery attempt | Pub/SubがMessageの配送を試みた回数 | DLQの最大回数は厳密値ではなくbest effort |
| At-least-once | Messageを1回以上配送する保証 | 同じMessageが複数回届く可能性がある |
| Exactly-once | ACK済みMessageの再配信を防ぐ機能 | Pub/SubではPullのみ対応し、現在のPush構成では使えない |
| Idempotency（冪等性） | 同じ処理を複数回実行しても結果が壊れない性質 | 重複MessageでもAI処理やDB更新を二重実行しないようにする |
| `event_id` | 論理Eventを一意に識別するID | `processed_events`へ保存し、重複判定に使う |
| `message_id` | Pub/SubがPublishごとに付けるID | 同じEventを再Publishすると別の`message_id`になることがある |
| Ordering key | 関連Messageの順序制御に使うKey | 現在は単一の`ticket.created`だけなので未使用 |
| Poison message | 何度再試行しても処理できないMessage | 不正なIDや恒久的な入力エラーをDLQへ隔離する |
| Re-publish | MessageをTopicへもう一度Publishすること | 原因修正後の再処理に使う |
| Replay | 保存済みMessageを過去時点から再配送すること | SnapshotやSeekを使う方式。今回の基本手順では使わない |
| Outbox Pattern | DB更新とPublish予定を同じTransactionで保存し、後から確実にPublishする設計 | `queued`のまま通知されない問題の推奨対策 |
| State transition | `queued`→`processing`→`completed`などの状態遷移 | 同時実行でも正しい順序になるよう原子的に更新する |
| Race condition | 複数処理の実行順によって結果が変わる問題 | 同時重複配信が両方とも`queued`を読む場合に起きる |
| OIDC | Pub/Subが署名付きTokenでWorkerを呼び出す認証方式 | `pubsub-push-invoker`を使用する |
| Schema | Messageの必須項目と型を検証する定義 | Avroの`incident-ticket-v1`をJSON encodingで使用する |
| Runbook | 障害確認・復旧・再処理の運用手順 | Phase 6ではDLQ再処理手順を作る |

## 2. Phase 6で解決する課題

現在の基本経路は動作しています。

```text
Incident API
  ├─ Cloud SQLへqueuedで保存
  └─ incident-ticketsへPublish
                     ↓
          incident-tickets-worker
                     ↓ HTTPS + OIDC
             Incident Worker
              ├─ 成功：204 ACK
              └─ 失敗：非2xxまたはtimeout
                         ↓ Retry
                    約5回失敗
                         ↓
          incident-tickets-dead-letter
```

Phase 6開始時の課題と完了結果は次のとおりです。

| 課題 | 開始時の状態 | 完了結果 |
| --- | --- | --- |
| 再配信とDLQを実測していない | 設定のみ完了 | 専用ラボで非2xx、Retry、DLQ到達を確認済み |
| 順次重複 | `completed`だけで判定 | 同一`event_id`の再配送で副作用が増えないことを確認済み |
| 同時重複 | Race conditionの可能性あり | Ticket行ロックと`event_id`主キーで直列化し確認済み |
| `event_id`処理履歴 | DBへ保存していない | `processed_events`とMigration `0003`をCloud SQLへ適用済み |
| Publish最終失敗 | Ticketが`queued`のまま残る | Phase 6では監査付き再Publishを採用し、Outboxは将来改善と決定 |
| DLQ再処理 | 手順と回数制限がない | 原因確認、再Publish、成功確認、ACKのRunbookを確認済み |

## 3. Phase 6のタスク一覧

1. 現在のTopic、Schema、Push、OIDC、Retry、DLQをCLIで説明できるようにする。
2. 専用ラボTopicとSubscriptionを作成する。
3. 存在しない`ticket_id`で非`2xx`、Retry、DLQ到達を再現する。
4. Push endpoint障害を安全に模擬し、復旧後の配送を確認する。
5. 同じ`event_id`の重複配信を確認する。
6. `event_id`処理履歴と同時重複対策を実装する。
7. DLQの安全な再Publish手順を作る。
8. DB確定後のPublish失敗に対してOutbox採用可否を決定する。
9. コマンド、Message trace、失敗原因、復旧結果を記録する。

## 4. 作業ルール

- `--project=gcp-cloud-incident-platform`を毎回指定する。
- 本番用`incident-tickets-worker`のPush設定は変更しない。
- ラボ用Resource名には`incident-tickets-reliability-lab`を使う。
- 実際のTicket IDが必要な箇所は、APIの結果から手動でコピーしてコマンドへ直接書く。
- DLQ Messageは、原因修正と再処理成功を確認する前にACKしない。
- 個人情報を含む本文をPub/Sub Messageやログへ入れない。
- `event_id`と`message_id`を混同しない。
- Push SubscriptionではExactly-onceを有効化できないため、Worker側の冪等性を必須とする。

## 5. 作業前確認

### 5.1 アカウントとプロジェクト

```powershell
gcloud.cmd config list `
  --format="yaml(core.account,core.project)"
```

- 役割：操作主体と既定Projectを確認する。
- 期待される結果：`adachiitsukiyishu@gmail.com`と`gcp-cloud-incident-platform`が表示される。

### 5.2 Pub/Sub API

```powershell
gcloud.cmd services list `
  --enabled `
  --project=gcp-cloud-incident-platform `
  --filter="name:pubsub.googleapis.com" `
  --format="value(name)"
```

- 役割：Pub/Sub APIが使用可能か確認する。
- 期待される結果：`pubsub.googleapis.com`を含むService名が表示される。

### 5.3 Schema

```powershell
gcloud.cmd pubsub schemas describe incident-ticket-v1 `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,type)"
```

- 役割：Message検証に使うSchemaを確認する。
- 期待される結果：Schema名と`type: AVRO`が表示される。

### 5.4 Main Topic

```powershell
gcloud.cmd pubsub topics describe incident-tickets `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,schemaSettings)"
```

- 役割：本番TopicとSchemaの関連付けを確認する。
- 期待される結果：`incident-ticket-v1`と`encoding: JSON`が表示される。

### 5.5 Push Subscription

```powershell
gcloud.cmd pubsub subscriptions describe incident-tickets-worker `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,topic,ackDeadlineSeconds,messageRetentionDuration,retryPolicy,deadLetterPolicy,pushConfig)"
```

- 役割：Push、OIDC、Retry、DLQの現在値を確認する。
- 期待される結果：ACK deadline 600秒、Retry 10～600秒、最大配送回数5回、Worker URL、Push SAが表示される。

### 5.6 DLQ Subscription

```powershell
gcloud.cmd pubsub subscriptions describe incident-tickets-dead-letter-monitor `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,topic,messageRetentionDuration)"
```

- 役割：Dead-letter Messageの保持先を確認する。
- 期待される結果：`incident-tickets-dead-letter`を購読するSubscriptionが表示される。

### 5.7 Worker

```powershell
gcloud.cmd run services describe incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(status.url,status.conditions,spec.template.spec.timeoutSeconds)"
```

- 役割：Push先URL、Ready状態、request timeoutを確認する。
- 期待される結果：Worker URL、`Ready: True`、timeout 600秒が表示される。

### 5.8 ラボResource名の重複確認

```powershell
gcloud.cmd pubsub topics list `
  --project=gcp-cloud-incident-platform `
  --filter="name:(incident-tickets-reliability-lab OR incident-tickets-reliability-lab-dead-letter)" `
  --format="value(name)"
```

- 役割：これから作るラボTopicが既に存在しないか確認する。
- 期待される結果：初回は何も表示されない。

```powershell
gcloud.cmd pubsub subscriptions list `
  --project=gcp-cloud-incident-platform `
  --filter="name:(incident-tickets-reliability-lab-worker OR incident-tickets-reliability-lab-dead-letter-monitor)" `
  --format="value(name)"
```

- 役割：これから作るラボSubscriptionが既に存在しないか確認する。
- 期待される結果：初回は何も表示されない。

## 6. 正常系の基準を確認する

### 6.1 Ticketを作成

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets" `
  -ContentType "application/json" `
  -Body '{"title":"Phase 6 baseline","raw_question":"Pub/Sub正常系の基準を確認します。"}'
```

- 役割：本番経路でAPI→DB→Pub/Sub→Workerを開始する。
- 期待される結果：HTTP 201相当で実際のTicket IDと`queued`が返る。Ticket IDを記録する。

### 6.2 Ticket結果を確認

次のURLにある`ここに実際のTicket-ID`を、6.1で返ったUUIDへ手動で置き換えてから実行します。

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets/ここに実際のTicket-ID"
```

- 役割：非同期Worker処理の結果を確認する。
- 期待される結果：数秒後に`status: completed`とAI分析結果が返る。

### 6.3 WorkerのPushログ

```powershell
gcloud.cmd logging read `
  'resource.type="cloud_run_revision" AND resource.labels.service_name="incident-worker" AND httpRequest.requestMethod="POST" AND httpRequest.requestUrl:"/pubsub/tickets"' `
  --project=gcp-cloud-incident-platform `
  --freshness=1h `
  --limit=20 `
  --format="table(timestamp,httpRequest.status,httpRequest.latency,resource.labels.revision_name)"
```

- 役割：Push要求の時刻、HTTP status、latencyを確認する。
- 期待される結果：正常処理はHTTP `204`として表示される。

## 7. 障害実験専用ラボを作る

### 7.1 ラボMain Topic

```powershell
gcloud.cmd pubsub topics create incident-tickets-reliability-lab `
  --project=gcp-cloud-incident-platform `
  --schema=incident-ticket-v1 `
  --message-encoding=json `
  --message-storage-policy-allowed-regions=asia-northeast1
```

- 役割：本番Topicへ影響しない障害実験用Topicを作る。
- 期待される結果：Topic作成成功とSchema設定が表示される。

### 7.2 ラボDead-letter Topic

```powershell
gcloud.cmd pubsub topics create incident-tickets-reliability-lab-dead-letter `
  --project=gcp-cloud-incident-platform `
  --message-storage-policy-allowed-regions=asia-northeast1
```

- 役割：ラボで処理できないMessageの隔離先を作る。
- 期待される結果：Dead-letter Topicの作成成功が表示される。

### 7.3 ラボDLQ監視Subscription

```powershell
gcloud.cmd pubsub subscriptions create incident-tickets-reliability-lab-dead-letter-monitor `
  --project=gcp-cloud-incident-platform `
  --topic=incident-tickets-reliability-lab-dead-letter `
  --message-retention-duration=1d `
  --expiration-period=1d
```

- 役割：Dead-letter Topicへ届いたMessageを失わず確認できるようにする。
- 期待される結果：Pull Subscriptionの作成成功が表示される。

### 7.4 ラボPush Subscription

ラボでは結果を早く観察するため、ACK deadlineを30秒、Retryを10～30秒にします。

```powershell
gcloud.cmd pubsub subscriptions create incident-tickets-reliability-lab-worker `
  --project=gcp-cloud-incident-platform `
  --topic=incident-tickets-reliability-lab `
  --push-endpoint="https://incident-worker-yaz57no2da-an.a.run.app/pubsub/tickets" `
  --push-auth-service-account="pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --push-auth-token-audience="https://incident-worker-yaz57no2da-an.a.run.app" `
  --ack-deadline=30 `
  --min-retry-delay=10s `
  --max-retry-delay=30s `
  --dead-letter-topic=incident-tickets-reliability-lab-dead-letter `
  --max-delivery-attempts=5 `
  --message-retention-duration=1d `
  --expiration-period=1d
```

- 役割：本番Workerへ認証付きPushし、失敗MessageをラボDLQへ送る。
- 期待される結果：Push Subscriptionの作成成功が表示される。

### 7.5 Pub/Sub Service AgentへDLQ Publish権限

```powershell
gcloud.cmd pubsub topics add-iam-policy-binding incident-tickets-reliability-lab-dead-letter `
  --project=gcp-cloud-incident-platform `
  --member="serviceAccount:service-888088780947@gcp-sa-pubsub.iam.gserviceaccount.com" `
  --role="roles/pubsub.publisher"
```

- 役割：Pub/Subが失敗MessageをラボDLQへPublishできるようにする。
- 期待される結果：IAM policy更新成功が表示される。

### 7.6 Pub/Sub Service AgentへSubscription権限

```powershell
gcloud.cmd pubsub subscriptions add-iam-policy-binding incident-tickets-reliability-lab-worker `
  --project=gcp-cloud-incident-platform `
  --member="serviceAccount:service-888088780947@gcp-sa-pubsub.iam.gserviceaccount.com" `
  --role="roles/pubsub.subscriber"
```

- 役割：Pub/Subが配送回数を追跡し、Dead-letter転送できるようにする。
- 期待される結果：IAM policy更新成功が表示される。

### 7.7 ラボ設定確認

```powershell
gcloud.cmd pubsub subscriptions describe incident-tickets-reliability-lab-worker `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,topic,ackDeadlineSeconds,retryPolicy,deadLetterPolicy,pushConfig)"
```

- 役割：ラボのPush、Retry、DLQ設定をまとめて確認する。
- 期待される結果：Worker URL、OIDC SA、10～30秒Retry、最大5回、ラボDLQが表示される。

## 8. 非2xx、Retry、DLQを再現する

存在しない`ticket_id`を持つSchema-valid Messageを送ります。WorkerはHTTP 404を返し、Pub/Subは再配信後にDLQへ転送します。

### 8.1 Poison message用flags file

```powershell
Set-Content `
  -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\phase6-poison-event.yaml" `
  -Encoding ascii `
  -Value @('--message: >-','  {"schema_version":"1","event_id":"60000000-0000-4000-8000-000000000001","event_type":"ticket.created","ticket_id":"60000000-0000-4000-8000-000000000099","created_at":"2026-08-22T03:00:00Z"}')
```

- 役割：PowerShellの引用符変換を避けて、固定のPoison messageを保存する。
- 期待される結果：エラーなく1つのYAMLファイルが作成される。

### 8.2 MessageのSchema検証

```powershell
gcloud.cmd pubsub schemas validate-message `
  --project=gcp-cloud-incident-platform `
  --schema-name=incident-ticket-v1 `
  --message-encoding=json `
  --flags-file="C:\Users\ITSUKI\AppData\Local\Temp\phase6-poison-event.yaml"
```

- 役割：Publish前にMessage形式を検証する。
- 期待される結果：`Message is valid.`が表示される。

### 8.3 ラボTopicへPublish

```powershell
gcloud.cmd pubsub topics publish incident-tickets-reliability-lab `
  --project=gcp-cloud-incident-platform `
  --flags-file="C:\Users\ITSUKI\AppData\Local\Temp\phase6-poison-event.yaml"
```

- 役割：処理不能なMessageをラボ経路へ送る。
- 期待される結果：Publishされた`messageIds`が表示される。

### 8.4 Workerの失敗ログ

```powershell
gcloud.cmd logging read `
  'resource.type="cloud_run_revision" AND resource.labels.service_name="incident-worker" AND httpRequest.requestMethod="POST" AND httpRequest.requestUrl:"/pubsub/tickets" AND httpRequest.status=404' `
  --project=gcp-cloud-incident-platform `
  --freshness=1h `
  --limit=20 `
  --format="table(timestamp,httpRequest.status,httpRequest.latency,resource.labels.revision_name)"
```

- 役割：同じ失敗要求が再配信された時系列を確認する。
- 期待される結果：同じ実験時間帯に複数のHTTP 404が表示される。

### 8.5 DLQ到達確認

```powershell
gcloud.cmd pubsub subscriptions pull incident-tickets-reliability-lab-dead-letter-monitor `
  --project=gcp-cloud-incident-platform `
  --limit=5 `
  --format=json
```

- 役割：再試行後にMessageがDLQへ転送されたか確認する。
- 期待される結果：数分以内にMessageが表示される。空の場合は時間を置いて同じ確認を再実行する。この時点では`--auto-ack`を付けない。

## 9. Worker到達不能を安全に模擬する

本番Workerを停止せず、ラボSubscriptionだけを存在しないPathへ向けます。これは実際のプロセス停止ではなく、Push endpoint障害の安全な代替実験です。

### 9.1 ラボPush endpointを存在しないPathへ変更

```powershell
gcloud.cmd pubsub subscriptions modify-push-config incident-tickets-reliability-lab-worker `
  --project=gcp-cloud-incident-platform `
  --push-endpoint="https://incident-worker-yaz57no2da-an.a.run.app/phase6-unavailable" `
  --push-auth-service-account="pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --push-auth-token-audience="https://incident-worker-yaz57no2da-an.a.run.app"
```

- 役割：ラボだけでPush endpoint障害を模擬する。
- 期待される結果：Subscription更新成功が表示される。

### 9.2 2つ目の障害Message用flags file

```powershell
Set-Content `
  -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\phase6-unavailable-event.yaml" `
  -Encoding ascii `
  -Value @('--message: >-','  {"schema_version":"1","event_id":"60000000-0000-4000-8000-000000000002","event_type":"ticket.created","ticket_id":"60000000-0000-4000-8000-000000000098","created_at":"2026-08-22T03:10:00Z"}')
```

- 役割：先のPoison messageと区別できるEventを作る。
- 期待される結果：エラーなくYAMLファイルが作成される。

### 9.3 MessageをPublish

```powershell
gcloud.cmd pubsub topics publish incident-tickets-reliability-lab `
  --project=gcp-cloud-incident-platform `
  --flags-file="C:\Users\ITSUKI\AppData\Local\Temp\phase6-unavailable-event.yaml"
```

- 役割：到達不能Pathへ配送されるMessageを送る。
- 期待される結果：Publishされた`messageIds`が表示される。

### 9.4 到達不能Pathのログ

```powershell
gcloud.cmd logging read `
  'resource.type="cloud_run_revision" AND resource.labels.service_name="incident-worker" AND httpRequest.requestUrl:"/phase6-unavailable"' `
  --project=gcp-cloud-incident-platform `
  --freshness=1h `
  --limit=20 `
  --format="table(timestamp,httpRequest.status,httpRequest.latency)"
```

- 役割：Pub/Subが失敗Pathへ再配信したことを確認する。
- 期待される結果：複数の非2xx応答が時系列で表示される。

### 9.5 正しいPush endpointへ復旧

```powershell
gcloud.cmd pubsub subscriptions modify-push-config incident-tickets-reliability-lab-worker `
  --project=gcp-cloud-incident-platform `
  --push-endpoint="https://incident-worker-yaz57no2da-an.a.run.app/pubsub/tickets" `
  --push-auth-service-account="pubsub-push-invoker@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --push-auth-token-audience="https://incident-worker-yaz57no2da-an.a.run.app"
```

- 役割：ラボPush経路を正常状態へ戻す。
- 期待される結果：Subscription更新成功が表示される。

### 9.6 復旧確認

```powershell
gcloud.cmd pubsub subscriptions describe incident-tickets-reliability-lab-worker `
  --project=gcp-cloud-incident-platform `
  --format="yaml(pushConfig.pushEndpoint,pushConfig.oidcToken)"
```

- 役割：誤ったPathが残っていないことを確認する。
- 期待される結果：Push endpointが`/pubsub/tickets`で終わり、OIDC SAとaudienceが表示される。

## 10. 現在の冪等性を確認する

### 10.1 既存の単体テスト

```powershell
uv run pytest tests/test_worker.py::test_worker_acks_completed_ticket -q
```

- 役割：完了済みTicketへ同じEventが順次届いてもAI処理が1回だけになることを確認する。
- 期待される結果：`1 passed`が表示される。

### 10.2 AI障害時の単体テスト

```powershell
uv run pytest tests/test_worker.py::test_worker_returns_500_and_rolls_back -q
```

- 役割：AI障害時にHTTP 500を返し、DBを`queued`へ戻す現在の動作を確認する。
- 期待される結果：`1 passed`が表示される。

### 10.3 手動重複テスト用Ticketを作成

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets" `
  -ContentType "application/json" `
  -Body '{"title":"Phase 6 duplicate test","raw_question":"同一event_idの順次重複を確認します。"}'
```

- 役割：重複配信の対象となるTicketを作る。
- 期待される結果：Ticket IDと`queued`が返る。Ticket IDを記録し、`completed`になるまで待つ。

### 10.4 重複Event用flags file

下の`ここに実際のTicket-ID`を10.3のUUIDへ手動で置き換えてから実行します。

```powershell
Set-Content `
  -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\phase6-duplicate-event.yaml" `
  -Encoding ascii `
  -Value @('--message: >-','  {"schema_version":"1","event_id":"60000000-0000-4000-8000-000000000003","event_type":"ticket.created","ticket_id":"ここに実際のTicket-ID","created_at":"2026-08-22T03:20:00Z"}')
```

- 役割：同じ`event_id`を繰り返しPublishするためのMessageを作る。
- 期待される結果：実際のUUIDを含むYAMLファイルが作成される。

### 10.5 重複EventのSchema検証

```powershell
gcloud.cmd pubsub schemas validate-message `
  --project=gcp-cloud-incident-platform `
  --schema-name=incident-ticket-v1 `
  --message-encoding=json `
  --flags-file="C:\Users\ITSUKI\AppData\Local\Temp\phase6-duplicate-event.yaml"
```

- 役割：Ticket ID置換後のMessage形式を確認する。
- 期待される結果：`Message is valid.`が表示される。

### 10.6 1回目のPublish

```powershell
gcloud.cmd pubsub topics publish incident-tickets-reliability-lab `
  --project=gcp-cloud-incident-platform `
  --flags-file="C:\Users\ITSUKI\AppData\Local\Temp\phase6-duplicate-event.yaml"
```

- 役割：同一Eventの1回目を送る。
- 期待される結果：`messageIds`が1つ表示される。

### 10.7 2回目のPublish

```powershell
gcloud.cmd pubsub topics publish incident-tickets-reliability-lab `
  --project=gcp-cloud-incident-platform `
  --flags-file="C:\Users\ITSUKI\AppData\Local\Temp\phase6-duplicate-event.yaml"
```

- 役割：同じ`event_id`と`ticket_id`をもう一度送る。
- 期待される結果：別のPub/Sub `message_id`が表示されても、Ticket結果は変わらない。

### 10.8 Ticket結果

次のURLにある`ここに実際のTicket-ID`を10.3のUUIDへ手動で置き換えます。

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets/ここに実際のTicket-ID"
```

- 役割：順次重複で結果が壊れていないことを確認する。
- 期待される結果：`completed`のまま、同じ分析結果が返る。

> 強い冪等性の実装、Cloud SQLへのMigration適用、Workerの再Deploy、重複Eventの再確認まで完了しました。

## 11. 強い冪等性を実装する

gcloudだけではアプリケーションの冪等性を作れません。次のコードとDB変更が必要です。

### 11.1 推奨するDB処理履歴

`processed_events`テーブルへ、少なくとも次を保存します。

| 列 | 用途 |
| --- | --- |
| `event_id` | Primary KeyまたはUnique制約で同一Eventを拒否する |
| `event_type` | Event種別を記録する |
| `ticket_id` | 対象Ticketを追跡する |
| `status` | `processing`、`completed`、`failed`を記録する |
| `attempt_count` | 再処理回数を制限する |
| `first_received_at` | 最初に受信した時刻を記録する |
| `completed_at` | 正常終了時刻を記録する |
| `last_error` | 秘密情報を含めず失敗分類を記録する |

Workerでは、Unique制約とTransactionを使い、同じ`event_id`の副作用を1回に制限します。`completed`だけを見る方式ではなく、同時実行と処理途中のcrashも考慮します。

### 11.2 Migration内容確認

Migrationは`0003_add_processed_events.py`として作成済みです。重複するRevisionを作らず、適用前に内容を確認します。

```powershell
Get-Content -LiteralPath ".\migrations\versions\0003_add_processed_events.py"
```

- 役割：作成済みの`processed_events`追加Migrationを確認する。
- 期待される結果：`event_id`主キー、Ticket外部キー、状態、試行回数、受信・完了時刻、最終エラーの列が表示される。

### 11.3 ローカルMigration適用

```powershell
uv run alembic upgrade head
```

- 役割：ローカルDBを最新Schemaへ更新する。
- 期待される結果：Migrationが成功し、Alembicのheadが新Revisionになる。

### 11.4 Phase 6テスト

```powershell
uv run pytest `
  tests/test_publisher.py `
  tests/test_worker.py `
  tests/test_tickets.py `
  -q
```

- 役割：Publish、重複、失敗rollback、Ticket作成をまとめて確認する。
- 期待される結果：全テストが成功する。

### 11.5 Ruff

```powershell
uv run ruff check .
```

- 役割：実装の静的検査を行う。
- 期待される結果：`All checks passed!`が表示される。

### 11.6 Format確認

```powershell
uv run ruff format --check .
```

- 役割：Pythonコードのformat差分がないか確認する。
- 期待される結果：すべてのファイルが既にformat済みと表示される。

## 12. Outboxと安全な再処理

### 12.1 現在の問題

APIはTicketをDBへcommitした後にPublishします。PublishのRetryが最後まで失敗すると、HTTP 503を返しますがTicketは`queued`のまま残ります。通知が存在しないため、WorkerはそのTicketを自動処理できません。

### 12.2 推奨方針

| 段階 | 対応 |
| --- | --- |
| Phase 6最低条件 | `queued` Ticketを監査付きで再Publishする管理手順を作る |
| 推奨実装 | TicketとOutbox行を同一DB Transactionで保存する |
| Dispatcher | 未送信OutboxをPublishし、成功した行へ送信時刻を記録する |
| 再試行 | 回数、次回時刻、最後のエラーを記録する |
| Poison対策 | 上限回数を超えたOutboxを停止し、人が原因を確認する |

Phase 6では監査付き再Publish手順を採用しました。Outbox Patternは、Publish最終失敗を自動回復するための将来改善として残します。

### 12.3 DLQ再Publishの判断条件

次のすべてを満たした場合だけ再Publishします。

1. 失敗原因を特定して修正済みである。
2. 対象Ticketがまだ再処理可能な状態である。
3. 同じ`event_id`の処理履歴を確認した。
4. 再処理回数と理由を記録した。
5. 再Publish後の成功確認方法がある。

練習では、修正したflags fileをラボTopicへ再Publishします。本番Topicへの手動Publishは、監査付き管理コマンドを実装するまで行いません。

```powershell
gcloud.cmd pubsub topics publish incident-tickets-reliability-lab `
  --project=gcp-cloud-incident-platform `
  --flags-file="C:\Users\ITSUKI\AppData\Local\Temp\phase6-duplicate-event.yaml"
```

- 役割：原因修正済みEventをラボで再処理する。
- 期待される結果：`messageIds`が表示され、WorkerログがHTTP 204になる。

### 12.4 再処理成功後にDLQをACK

```powershell
gcloud.cmd pubsub subscriptions pull incident-tickets-reliability-lab-dead-letter-monitor `
  --project=gcp-cloud-incident-platform `
  --limit=10 `
  --auto-ack `
  --format=json
```

- 役割：再処理済みのラボDLQ Messageを確認してACKする。
- 期待される結果：取得したMessageが表示され、同じMessageが監視Subscriptionへ再配信されなくなる。

## 13. 実装後のCloud Run更新

コード、Migration、テストの確認が終わった後だけ実行します。

### 13.1 Incident API

OutboxまたはPublisher処理を変更した場合に更新します。

```powershell
gcloud.cmd run deploy incident-platform `
  --project=gcp-cloud-incident-platform `
  --source . `
  --region=asia-northeast1 `
  --service-account=incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com `
  --network=incident-vpc `
  --subnet=incident-subnet-asia-northeast1 `
  --vpc-egress=private-ranges-only `
  --clear-cloudsql-instances `
  --set-secrets=DATABASE_URL=incident-database-url-private:latest `
  --set-env-vars=APP_ENV=production,GOOGLE_CLOUD_PROJECT=gcp-cloud-incident-platform,PUBSUB_TOPIC=incident-tickets,ATTACHMENT_BUCKET=gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --ingress=all `
  --allow-unauthenticated
```

- 役割：Phase 6のAPI変更を現在のPrivate構成を維持してdeployする。
- 期待される結果：新RevisionがReadyになり、API URLへのtrafficが新Revisionへ移る。

### 13.2 Incident Worker

```powershell
gcloud.cmd run deploy incident-worker `
  --project=gcp-cloud-incident-platform `
  --source . `
  --region=asia-northeast1 `
  --service-account=incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com `
  --network=incident-vpc `
  --subnet=incident-subnet-asia-northeast1 `
  --vpc-egress=private-ranges-only `
  --clear-cloudsql-instances `
  --set-secrets=DATABASE_URL=incident-database-url-private:latest `
  --set-env-vars=APP_ENV=production,GOOGLE_CLOUD_PROJECT=gcp-cloud-incident-platform,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-2.5-flash-lite `
  --command=uvicorn `
  --args=incident_platform.worker:app,--host,0.0.0.0,--port,8080 `
  --timeout=600 `
  --ingress=internal `
  --no-allow-unauthenticated
```

- 役割：冪等性を追加したWorkerをPrivate構成と内部Ingressを維持してdeployする。
- 期待される結果：新RevisionがReadyになり、Pub/Sub OIDC Pushを受け取れる。

### 13.3 APIのReady確認

```powershell
gcloud.cmd run services describe incident-platform `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(status.latestReadyRevisionName,status.conditions,status.traffic)"
```

- 役割：APIの新Revisionとtrafficを確認する。
- 期待される結果：Readyが`True`で、新Revisionへtrafficが割り当てられる。

### 13.4 WorkerのReady確認

```powershell
gcloud.cmd run services describe incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(status.latestReadyRevisionName,status.conditions,status.traffic)"
```

- 役割：Workerの新RevisionがPushを受けられる状態か確認する。
- 期待される結果：Readyが`True`で、新Revisionへtrafficが割り当てられる。

## 14. ラボの後片付け

DLQ確認、再処理、記録がすべて終わった後に実行します。

### 14.1 ラボPush Subscription削除

```powershell
gcloud.cmd pubsub subscriptions delete incident-tickets-reliability-lab-worker `
  --project=gcp-cloud-incident-platform `
  --quiet
```

- 役割：ラボからWorkerへのPushを停止する。
- 期待される結果：Subscription削除成功が表示される。

### 14.2 ラボDLQ監視Subscription削除

```powershell
gcloud.cmd pubsub subscriptions delete incident-tickets-reliability-lab-dead-letter-monitor `
  --project=gcp-cloud-incident-platform `
  --quiet
```

- 役割：ラボDLQの監視Subscriptionを削除する。
- 期待される結果：Subscription削除成功が表示される。

### 14.3 ラボMain Topic削除

```powershell
gcloud.cmd pubsub topics delete incident-tickets-reliability-lab `
  --project=gcp-cloud-incident-platform `
  --quiet
```

- 役割：障害実験用Main Topicを削除する。
- 期待される結果：Topic削除成功が表示される。

### 14.4 ラボDead-letter Topic削除

```powershell
gcloud.cmd pubsub topics delete incident-tickets-reliability-lab-dead-letter `
  --project=gcp-cloud-incident-platform `
  --quiet
```

- 役割：障害実験用Dead-letter Topicを削除する。
- 期待される結果：Topic削除成功が表示される。

### 14.5 一時ファイル削除

```powershell
Remove-Item `
  -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\phase6-poison-event.yaml"
```

- 役割：Poison messageの一時ファイルを削除する。
- 期待される結果：ファイルが削除される。

```powershell
Remove-Item `
  -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\phase6-unavailable-event.yaml"
```

- 役割：到達不能実験の一時ファイルを削除する。
- 期待される結果：ファイルが削除される。

```powershell
Remove-Item `
  -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\phase6-duplicate-event.yaml"
```

- 役割：重複実験の一時ファイルを削除する。
- 期待される結果：ファイルが削除される。

### 14.6 本番Resource確認

```powershell
gcloud.cmd pubsub subscriptions describe incident-tickets-worker `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,retryPolicy,deadLetterPolicy,pushConfig)"
```

- 役割：後片付けが本番Subscriptionへ影響していないことを確認する。
- 期待される結果：本番Worker URL、Retry、DLQ設定が変更前と同じ値で表示される。

## 15. よくあるエラー

| 症状 | 主な原因 | 対応 |
| --- | --- | --- |
| JSONが`INVALID_JSON_AVRO_MESSAGE` | PowerShellで引用符が変換された | `--message`直渡しを避け、手順の`--flags-file`を使う |
| `ALREADY_EXISTS` | ラボ作成コマンドを再実行した | 5.8の一覧で残っているResourceを確認する |
| PushがHTTP 401/403 | OIDC SA、audience、`roles/run.invoker`の誤り | Push設定とWorker IAMを確認する |
| 失敗してもDLQへ移らない | Pub/Sub Service AgentのPublisher/Subscriber権限不足 | 7.5と7.6を確認する |
| DLQ pullが空 | Retry継続中、DLQ monitor作成前、権限反映待ち | 数分待ち、7.3、7.5、7.6を確認する |
| 404が再配信される | Pushでは400系もNACK扱い | 恒久エラーをACKして記録する設計をPhase 6で判断する |
| 重複でAIが2回動く | Migration未適用、旧Worker稼働中、または行ロック不成立 | Migration適用とWorker Revisionを確認し、PostgreSQL上で同時配送を再試験する |
| Ticketが`queued`のまま | DB commit後にPublishが最終失敗した | Outboxまたは監査付き再Publishを実装する |
| `Remove-Item`が失敗 | 対象ファイルが既にない | `Test-Path -LiteralPath`で存在を確認し、存在するファイルだけ削除する |

## 16. Phase 6の完了判定

- [x] At-least-once、ACK/NACK、Retry、Push backoff、DLQを説明できる。
- [x] 非2xxからRetry、DLQ到達までの時系列を記録した。
- [x] 本番Resourceを変更せず、ラボで障害と復旧を再現した。
- [x] 同じ`event_id`の順次・同時配送で、業務上の副作用を1回に制限した。
- [x] `event_id`の処理履歴、再処理回数、最終結果をDBで追跡できる。
- [x] DLQ Messageを原因修正後だけ安全に再処理できる。
- [x] Publish最終失敗には監査付き再Publishを採用し、Outboxを将来改善とした。
- [x] Poison messageの無限再処理を防ぐ上限と停止条件を確認した。
- [x] `pytest`、Ruff、正常系API、Pub/Sub Push、Worker、DB更新が成功した。
- [x] ラボResourceと一時ファイルを削除し、本番Subscriptionが元のままであることを確認した。

## 17. 実施結果

| 確認項目 | 結果 |
| --- | --- |
| 正常経路 | API→Cloud SQL→Pub/Sub→Worker→Vertex AI→DB更新が成功 |
| Retry・DLQ | 非2xxの再配信と、最大配送回数後のDLQ到達を確認 |
| 障害復旧 | 到達不能なPush endpointから正常Pathへ戻した後の配送成功を確認 |
| 冪等性 | `processed_events`、Ticket行ロック、Transactionで重複副作用を防止 |
| 失敗と再試行 | `failed`、`attempt_count`、`last_error`を記録し、同一Eventの再試行成功を確認 |
| Cloud Run | Migration適用後にAPIとWorkerを更新し、Readyと本番経路を確認 |
| 再処理 | 原因修正、履歴確認、再Publish、成功確認、DLQ ACKの順序を確認 |
| 後片付け | ラボResourceと一時ファイルを削除し、本番Subscription設定を維持 |
| 品質確認 | `pytest`、Ruff、format確認が成功 |

Phase 6は完了です。残る改善候補は、DB確定後のPublish最終失敗を自動回復するOutbox Patternの実装です。

## 18. 参考資料

- [Subscriptionの概要](https://cloud.google.com/pubsub/docs/subscription-overview)
- [Push Subscription](https://cloud.google.com/pubsub/docs/push)
- [Dead-letter Topic](https://cloud.google.com/pubsub/docs/dead-letter-topics)
- [Subscription Retry Policy](https://cloud.google.com/pubsub/docs/subscription-retry-policy)
- [Exactly-once Delivery](https://cloud.google.com/pubsub/docs/exactly-once-delivery)
- [Message Ordering](https://cloud.google.com/pubsub/docs/ordering)
- [ReplayとSeek](https://cloud.google.com/pubsub/docs/replay-overview)
- [gcloud Pub/Subリファレンス](https://cloud.google.com/sdk/gcloud/reference/pubsub)
