# Cloud Storage運用

## 1. 用語まとめ

| 用語 | 意味 |
| --- | --- |
| Cloud Storage | ファイルなどのデータをオブジェクトとして保存するサービス |
| Bucket | オブジェクトを保存する入れ物。Bucket同士は入れ子にできない |
| Object | Cloud Storageへ保存する個々のデータ |
| Object data | 保存するデータ本体。Cloud Storageはファイル形式を解釈しない |
| Metadata | ファイル名、Content-Type、サイズなどのオブジェクト情報 |
| Object name | Bucket内でオブジェクトを識別する名前 |
| Generation | 同名オブジェクトの世代を識別する番号 |
| Prefix | Object nameの先頭部分。フォルダのような分類に使用する |
| Storage class | 保存料金や最低保存期間などを決める区分 |
| Standard Storage | 頻繁に使用するデータ向けのStorage class |
| Region | オブジェクトデータを保存する地理的な場所 |
| Uniform bucket-level access | オブジェクト単位のACLを無効にし、IAMでアクセスを統一する設定 |
| Public access prevention | `allUsers`などによる一般公開を防ぐ設定 |
| IAM | ユーザーやService Accountへ操作権限を付与する仕組み |
| Soft Delete | 削除したBucketやObjectを一定期間復元できる仕組み |
| Observability | リクエスト数、エラー率、転送量などを確認する画面 |
| Class A / Class B | 作成・一覧・取得などのAPI操作を分類した課金区分 |

## 2. 簡単な解説

Cloud Storageでは、すべてのデータをBucket内のObjectとして保存します。Object dataはCloud Storageにとって不透明なデータであるため、画像、PDF、Office文書、動画、音声、テキスト、圧縮ファイル、独自のバイナリ形式などを保存できます。

Objectは、データ本体とMetadataで構成されます。同じBucket内では、Object nameとGenerationの組み合わせで一つの世代を識別します。通常のBucketでは`/`もObject nameの一部であり、`tickets/チケットID/ファイル名`のような名前を使うと、フォルダに近い形で分類できます。

Bucket名は世界全体で一意です。Bucket作成時には保存先Regionを指定します。このドキュメントでは、Google Cloud Free Tierの対象である`us-west1`とStandard Storageを使用します。

Cloud StorageのFree Tierは、`us-west1`、`us-central1`、`us-east1`の合計利用量に対して、毎月次の範囲で適用されます。

| 対象 | 毎月の無料利用枠 |
| --- | --- |
| Standard Storage | 5 GB-months |
| Class A Operations | 5,000回 |
| Class B Operations | 50,000回 |
| 北米からのData Transfer | 100 GB。中国とオーストラリアは対象外 |

無料枠を超えた保存量、操作、データ転送には料金が発生します。Soft Delete中のデータも保存量として課金対象です。このドキュメントでは、誤削除へ備えるため7日間のSoft Deleteを使用します。

## 3. このプロジェクトでの用途

### 3.1 構成

| 項目 | 設定 |
| --- | --- |
| Project | `gcp-cloud-incident-platform` |
| Bucket | `gcp-cloud-incident-platform-ticket-attachments-888088780947` |
| Region | `us-west1` |
| Storage class | `STANDARD` |
| 用途 | チケットの添付ファイル保存 |
| アクセス制御 | Uniform bucket-level access |
| 公開設定 | Public access preventionを有効化 |
| 誤削除対策 | Soft Deleteを7日間有効化 |

Bucket名にはProject numberを含め、世界全体で一意になりやすくしています。既に使用されている場合は作成できないため、別の一意な名前で設計書とコマンドをまとめて変更します。

### 3.2 Object name

添付ファイルは次の形式で保存します。

```text
tickets/{ticket_id}/{attachment_id}-{安全化した元ファイル名}
```

例を次に示します。

```text
tickets/22222222-2222-2222-2222-222222222222/11111111-1111-1111-1111-111111111111-sample-attachment.pdf
```

`attachment_id`を含めることで同名ファイルの上書きを防ぎます。Object nameには個人情報や問い合わせ本文を入れません。

### 3.3 アプリケーション設計

Cloud Storageはあらゆる形式を保存できます。API側では安全性のため、ファイルサイズ、Content-Type、ファイル名、必要に応じたマルウェア検査を行います。

Cloud SQLにはObject dataを保存せず、次の情報を保存します。

- `attachment_id`
- `ticket_id`
- `bucket_name`
- `object_name`
- `original_filename`
- `content_type`
- `size`
- `generation`
- `created_at`

`incident-platform-run`には、対象Bucket内のObjectを作成、取得、更新、削除する`roles/storage.objectUser`を付与します。Bucket自体の管理権限は付与しません。Objectは公開せず、添付ファイルの取得は認証済みAPIまたは有効期限付きURLを使用します。

現在のCloud Runは`asia-northeast1`、Cloud Storageは`us-west1`です。リージョン間通信になるため、東京からの利用では遅延が増え、無料枠とは別にデータ転送料金が発生する可能性があります。また、添付ファイルの保存場所は米国になります。

## 4. gcloud CLI command

以下はWindows PowerShell向けです。上から一つずつ実行します。シェル変数や置換用変数は使用していません。

PowerShellの実行ポリシーで`gcloud.ps1`が拒否される場合は、`gcloud`を`gcloud.cmd`へ読み替えます。

### 4.1 認証とProject設定

現在の認証アカウントを確認します。

```powershell
gcloud auth list
```

操作対象のProjectを設定します。

```powershell
gcloud config set project gcp-cloud-incident-platform
```

Cloud Storage APIを有効にします。

```powershell
gcloud services enable storage.googleapis.com `
  --project=gcp-cloud-incident-platform
```

### 4.2 Bucketの作成と確認

Project内のBucketを一覧表示します。

```powershell
gcloud storage buckets list `
  --project=gcp-cloud-incident-platform
```

添付ファイル用Bucketを作成します。初回のみ実行します。

```powershell
gcloud storage buckets create gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --project=gcp-cloud-incident-platform `
  --location=us-west1 `
  --default-storage-class=STANDARD `
  --uniform-bucket-level-access `
  --public-access-prevention `
  --soft-delete-duration=7d
```

BucketのRegion、Storage class、アクセス設定、Soft Deleteを確認します。

```powershell
gcloud storage buckets describe gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --format=yaml
```

### 4.3 Service Accountへ権限を付与

API用Service Accountへ、対象Bucket内のObjectを操作する権限を付与します。初回のみ実行します。

```powershell
gcloud storage buckets add-iam-policy-binding gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --member="serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/storage.objectUser"
```

BucketのIAM Policyを確認します。

```powershell
gcloud storage buckets get-iam-policy gs://gcp-cloud-incident-platform-ticket-attachments-888088780947
```

### 4.4 Objectをアップロード

Projectフォルダにある`sample-attachment.pdf`をテスト用Objectとしてアップロードします。`--if-generation-match=0`により、同じObject nameが存在する場合は上書きしません。

```powershell
gcloud storage cp .\sample-attachment.pdf `
  gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/22222222-2222-2222-2222-222222222222/11111111-1111-1111-1111-111111111111-sample-attachment.pdf `
  --content-type=application/pdf `
  --custom-metadata="ticket-id=22222222-2222-2222-2222-222222222222,original-filename=sample-attachment.pdf" `
  --if-generation-match=0
```

保存する形式を変える場合は、ローカルファイル名、Object name、Content-Typeをその形式に合わせます。Cloud Storage側に拡張子の制限はありません。

### 4.5 Objectを確認

指定チケットのObjectを一覧表示します。

```powershell
gcloud storage ls "gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/22222222-2222-2222-2222-222222222222/**" `
  --long
```

ObjectのMetadataとGenerationを確認します。

```powershell
gcloud storage objects describe gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/22222222-2222-2222-2222-222222222222/11111111-1111-1111-1111-111111111111-sample-attachment.pdf
```

既存Metadataを残したまま、アップロード元を追加または更新します。

```powershell
gcloud storage objects update gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/22222222-2222-2222-2222-222222222222/11111111-1111-1111-1111-111111111111-sample-attachment.pdf `
  --update-custom-metadata="upload-source=manual-test"
```

### 4.6 Objectをダウンロード

添付ファイルをProjectフォルダへダウンロードします。

```powershell
gcloud storage cp gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/22222222-2222-2222-2222-222222222222/11111111-1111-1111-1111-111111111111-sample-attachment.pdf `
  .\downloaded-sample-attachment.pdf
```

### 4.7 Objectの削除と復元

テスト用Objectを削除します。7日間はSoft Delete状態で保持されます。

```powershell
gcloud storage rm gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/22222222-2222-2222-2222-222222222222/11111111-1111-1111-1111-111111111111-sample-attachment.pdf
```

Soft Delete状態のObjectを一覧表示します。

```powershell
gcloud storage objects list gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --soft-deleted
```

同名Objectの最新のSoft Delete世代を復元します。

```powershell
gcloud storage restore gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/22222222-2222-2222-2222-222222222222/11111111-1111-1111-1111-111111111111-sample-attachment.pdf
```

### 4.8 使用量と動作を確認

Bucket内の現在の合計保存量を確認します。Object数が多い場合はCloud Monitoringを使用します。

```powershell
gcloud storage du gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --summarize `
  --readable-sizes
```

Objectごとの名前、サイズ、Content-Type、作成時刻、Generationを確認します。

```powershell
gcloud storage objects list gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --raw `
  --format="table(name,size,contentType,timeCreated,generation)"
```

直近7日間のCloud Storage監査ログを確認します。

```powershell
gcloud logging read 'resource.type="gcs_bucket" AND resource.labels.bucket_name="gcp-cloud-incident-platform-ticket-attachments-888088780947"' `
  --project=gcp-cloud-incident-platform `
  --freshness=7d `
  --limit=50 `
  --format="table(timestamp,protoPayload.methodName,protoPayload.authenticationInfo.principalEmail,protoPayload.status.message)"
```

Objectの読み取りや書き込みを監査ログへ記録するには、Data Access監査ログの設定が別途必要です。Data AccessログはLogging料金の対象になる場合があります。

リクエスト数、`4xx`、`5xx`、帯域幅は、次のCloud Storage Monitoring画面で確認します。

```text
https://console.cloud.google.com/storage/monitoring?project=gcp-cloud-incident-platform
```

個別Bucketでは、Cloud ConsoleのBucket詳細にある「Observability」タブを使用します。

### 4.9 Bucketを削除

空のBucketを削除します。添付ファイル機能を廃止する場合だけ実行します。

```powershell
gcloud storage buckets delete gs://gcp-cloud-incident-platform-ticket-attachments-888088780947
```

Objectが残っている場合は削除できません。BucketとObjectを削除すると、Soft Delete期間後に復元できなくなります。

## 5. 運用時の確認項目

- 保存量、Class A、Class B、Data Transferが無料枠を超えていないか
- `4xx`が増えていないか
- `5xx`が増えていないか
- API用Service Account以外へ不要な権限を付与していないか
- `allUsers`や`allAuthenticatedUsers`へ権限を付与していないか
- Content-Type、ファイルサイズ、Object nameをAPI側で検証しているか
- Cloud SQLのObject情報とCloud StorageのObjectが一致しているか
- Soft Delete中の保存量を含めて料金を確認しているか
- 米国への保存とリージョン間通信が要件を満たすか

## 6. 参照資料

- [Cloud Storageをgcloud CLIで確認する](https://docs.cloud.google.com/storage/docs/discover-object-storage-gcloud?hl=ja)
- [Cloud StorageのBucket](https://docs.cloud.google.com/storage/docs/buckets?hl=ja)
- [Cloud StorageのObject](https://docs.cloud.google.com/storage/docs/objects?hl=ja)
- [Cloud Storageのモニタリングデータへアクセスする](https://docs.cloud.google.com/storage/docs/access-monitoring?hl=ja)
- [Cloud Storageのモニタリング概要](https://docs.cloud.google.com/storage/docs/monitoring?hl=ja)
- [Bucketのロケーション](https://docs.cloud.google.com/storage/docs/bucket-locations?hl=ja)
- [Cloud StorageのIAMロール](https://docs.cloud.google.com/storage/docs/access-control/iam-roles?hl=ja)
- [Cloud StorageのSoft Delete](https://docs.cloud.google.com/storage/docs/soft-delete?hl=ja)
- [Google Cloud Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features?hl=ja)
- [Cloud Storageの料金](https://cloud.google.com/storage/pricing?hl=ja)
- [gcloud storageリファレンス](https://docs.cloud.google.com/sdk/gcloud/reference/storage)

## 7. 添付APIの手動動作確認

`sample-attachment.pdf`を使用し、登録、アップロード、取得、削除を確認します。複数ファイルは事前にZIPへまとめます。

### 7.1 ローカルADCを準備

Pub/Sub Emulatorが認証用ポート`8085`と競合する場合だけ、一時停止します。

```powershell
docker compose stop pubsub
```

ADCを作成します。このgcloudコマンドは人間が実行します。

```powershell
gcloud auth application-default login
```

ADCとComposeを確認します。

```powershell
Test-Path "$env:APPDATA\gcloud\application_default_credentials.json"
docker compose up --build -d
docker compose ps
```

`Test-Path`が`True`、APIが起動状態であることを確認します。

### 7.2 チケットとアップロードURLを作成

`http://localhost:8080/docs`で`POST /tickets`を実行し、返された`id`を`ticket_id`として控えます。

ファイルサイズを確認します。

```powershell
$filePath = (Resolve-Path ".\sample-attachment.pdf").Path
$size = (Get-Item -LiteralPath $filePath).Length
$size
```

`POST /tickets/{ticket_id}/attachments/uploads`へ次を入力します。`size`は実際の値に置き換えます。

```json
{
  "filename": "sample-attachment.pdf",
  "content_type": "application/pdf",
  "size": 14123
}
```

HTTP `201`を確認し、実際の`id`を`attachment_id`、`upload_url`を送信先として控えます。API仕様欄の`"string"`ではなく、Server responseの値を使用します。

### 7.3 Cloud Storageへアップロード

```powershell
$uploadUrl = "実際のupload_url"
curl.exe --fail-with-body -X PUT `
  -H "Content-Type: application/pdf" `
  -H "Content-Length: $size" `
  --upload-file "$filePath" `
  "$uploadUrl"
```

`POST /tickets/{ticket_id}/attachments/{attachment_id}/complete`を実行し、`status`が`ready`であることを確認します。

`GET /tickets/{ticket_id}/attachments`で、ファイル名、Content-Type、サイズ、`ready`を確認します。

### 7.4 Objectとダウンロードを確認

```powershell
$ticketId = "実際のticket_id"
$attachmentId = "実際のattachment_id"
$apiBase = "http://localhost:8080"

gcloud storage ls `
  "gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/$ticketId/**" `
  --long

curl.exe --fail-with-body `
  "$apiBase/tickets/$ticketId/attachments/$attachmentId" `
  --output ".\manual-test-download.pdf"

Get-FileHash ".\sample-attachment.pdf"
Get-FileHash ".\manual-test-download.pdf"
```

Cloud StorageにObjectが存在し、2つのHashが一致することを確認します。

### 7.5 添付を削除

`DELETE /tickets/{ticket_id}/attachments/{attachment_id}`を実行し、HTTP `204`を確認します。

```powershell
curl.exe "$apiBase/tickets/$ticketId/attachments"
gcloud storage ls `
  "gs://gcp-cloud-incident-platform-ticket-attachments-888088780947/tickets/$ticketId/**" `
  --long
```

API一覧と通常のObject一覧から対象が消えていることを確認します。Soft Delete期間中は復元可能です。

### 7.6 確認実績

2026-08-18にPDFで登録、Cloud Storage保存、APIダウンロード、Hash一致、削除を確認済みです。
