# Google Cloud IAM 学習・確認記録

## 1. この資料の目的

この資料は、Cloud Storage添付機能で使用するIAMを理解し、2026-08-18に確認した権限状況を記録するものです。

対象は次のとおりです。

| 項目 | 値 |
| --- | --- |
| Project | `gcp-cloud-incident-platform` |
| Bucket | `gcp-cloud-incident-platform-ticket-attachments-888088780947` |
| API Service Account | `incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com` |
| 確認ユーザー | `adachiitsukiyishu@gmail.com` |

## 2. IAMの基本

IAMは「誰が、どのResourceへ、何をできるか」を制御します。

```text
Principal
  ＋ Resource上のRole
  ＝ Roleに含まれるPermissionを利用可能
```

### 2.1 Principal

操作する主体です。

- Googleアカウント
- Service Account
- Googleグループ
- Google管理のService Agent

今回のAPIは、人間のアカウントではなく`incident-platform-run`としてGoogle Cloudへアクセスします。

### 2.2 Permission

1つの操作を表す最小単位です。

| Permission | 用途 |
| --- | --- |
| `storage.objects.create` | 添付ファイルを作成 |
| `storage.objects.get` | Object情報とファイルを取得 |
| `storage.objects.delete` | 添付ファイルを削除 |
| `storage.objects.list` | Objectを一覧表示 |
| `storage.objects.update` | Object情報を更新 |

PermissionをPrincipalへ直接付与せず、複数のPermissionをまとめたRoleを付与します。

### 2.3 Role

Permissionの集合です。

今回使用する`roles/storage.objectUser`は、Objectの作成、取得、更新、削除などを含むGoogle管理の事前定義Roleです。Bucket自体を作成・削除する管理権限は含みません。

### 2.4 IAM PolicyとBinding

IAM PolicyはResourceに設定されるアクセス制御情報です。BindingはRoleとPrincipalの組み合わせです。

```yaml
role: roles/storage.objectUser
members:
  - serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com
```

このBindingは「API Service AccountへStorage Object Userを付与する」という意味です。

### 2.5 Resourceと継承

IAMはProjectやBucketなどのResource単位で設定できます。

```text
Project
├─ Cloud SQL用Role: roles/cloudsql.client
└─ Bucket
   └─ 添付用Role: roles/storage.objectUser
```

Projectに付与した権限は、原則として配下Resourceへ継承されます。Bucketへ直接付与すると、Storage権限を対象Bucketへ限定できます。

### 2.6 最小権限

Principalへ必要なResourceの必要なRoleだけを付与する考え方です。

今回、API Service Accountへ`roles/storage.admin`をProject全体で付与せず、対象Bucketだけに`roles/storage.objectUser`を付与しています。

## 3. 確認結果

### 3.1 実行環境

| 確認項目 | 結果 |
| --- | --- |
| アクティブProject | `gcp-cloud-incident-platform` |
| gcloudアカウント | `adachiitsukiyishu@gmail.com` |
| ユーザーのProject Role | `roles/owner` |

`roles/owner`は非常に強い管理権限です。学習・管理用ユーザーとして利用していますが、アプリケーション実行には使用しません。

### 3.2 Bucketレベル

対象BucketのIAM Policyで、次を確認しました。

| Principal | Role | Condition |
| --- | --- | --- |
| `incident-platform-run@...` | `roles/storage.objectUser` | なし |

Bucket Policyには次のLegacy Roleも存在します。

- `roles/storage.legacyBucketOwner`
- `roles/storage.legacyBucketReader`
- `roles/storage.legacyObjectOwner`
- `roles/storage.legacyObjectReader`

これらはProjectのOwner、Editor、Viewerに対応する従来互換のBindingです。今回のAPI Service AccountがLegacy Roleを利用しているわけではありません。

### 3.3 Projectレベル

API Service Accountに対して、Projectレベルでは次を確認しました。

| Principal | Role |
| --- | --- |
| `incident-platform-run@...` | `roles/cloudsql.client` |

Storage権限はProjectレベルではなくBucketレベルです。したがって、対象外BucketへStorage権限を広げていません。

Pub/Sub TopicやSecretなどResource単位で付与したRoleは、Project IAM Policyの結果には表示されません。それぞれのResource Policyを別途確認します。

### 3.4 Storage Object Userの内容

Role詳細から、添付機能に必要な次のPermissionを確認しました。

- `storage.objects.create`
- `storage.objects.get`
- `storage.objects.delete`
- `storage.objects.list`
- `storage.objects.update`
- `storage.objects.restore`

このRoleにはFolder、Managed Folder、Multipart UploadなどのPermissionも含まれます。現在はGoogle管理Roleの保守性を優先しています。さらに厳密に限定する場合はCustom Roleを検討します。

### 3.5 Policy Troubleshooter

次の3操作を確認しました。

| Permission | Allow | Deny | 最終結果 |
| --- | --- | --- | --- |
| `storage.objects.create` | Granted | Not denied | `CAN_ACCESS` |
| `storage.objects.get` | Granted | Not denied | `CAN_ACCESS` |
| `storage.objects.delete` | Granted | Not denied | `CAN_ACCESS` |

許可の根拠は、対象Bucketの`roles/storage.objectUser`です。Deny Policyによる拒否もありません。

初回確認時に`policytroubleshooter.googleapis.com`を有効化しました。

## 4. 現在の評価

### 良い点

- API専用Service Accountを使用している
- Storage権限を対象Bucketへ限定している
- `roles/storage.admin`をAPIへ付与していない
- 作成、取得、削除の実効権限を確認できた
- IAM Conditionなしで構成が単純である
- Deny Policyによる予期しない拒否がない

### 今後確認する点

- 権限削除による403と復旧実験
- Data Access監査ログの確認
- Default Compute Service Accountの`roles/editor`が必要か
- Legacy Roleと基本Roleの利用範囲
- Custom Roleが必要か

Default Compute Service Accountの`roles/editor`は広い権限です。今回の添付API用Service Accountとは別ですが、Phase 3の最小権限確認対象として記録します。変更する場合は依存処理を確認してから行います。

## 5. 再確認コマンド

gcloud CLIコマンドは人間が実行します。

### 5.1 Projectとアカウント

```powershell
gcloud config get-value project
gcloud auth list --filter=status:ACTIVE --format="value(account)"
```

### 5.2 Bucket IAM Policy

```powershell
gcloud storage buckets get-iam-policy `
  gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --format=yaml
```

`gcloud storage buckets get-iam-policy`は`--filter`を受け付けないため、PowerShellで絞り込みます。

```powershell
$policy = gcloud storage buckets get-iam-policy `
  gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --format=json | ConvertFrom-Json

$policy.bindings |
  Where-Object {
    $_.members -contains "serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com"
  } |
  Select-Object role, members, condition |
  Format-List
```

### 5.3 Project IAM Policy

```powershell
gcloud projects get-iam-policy gcp-cloud-incident-platform `
  --flatten="bindings[].members" `
  --filter="bindings.members:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --format="table(bindings.role,bindings.members,bindings.condition)"
```

### 5.4 Role内Permission

```powershell
gcloud iam roles describe roles/storage.objectUser `
  --format="yaml(name,title,description,includedPermissions)"
```

### 5.5 実効権限

```powershell
$resource = "//storage.googleapis.com/projects/_/buckets/gcp-cloud-incident-platform-ticket-attachments-888088780947"
$principal = "incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com"
```

```powershell
gcloud policy-intelligence troubleshoot-policy iam "$resource" `
  --principal-email="$principal" `
  --permission="storage.objects.create"

gcloud policy-intelligence troubleshoot-policy iam "$resource" `
  --principal-email="$principal" `
  --permission="storage.objects.get"

gcloud policy-intelligence troubleshoot-policy iam "$resource" `
  --principal-email="$principal" `
  --permission="storage.objects.delete"
```

`overallAccessState: CAN_ACCESS`を確認します。

## 6. Consoleでの確認場所

### Bucketの権限

```text
Cloud Storage
  → バケット
  → gcp-cloud-incident-platform-ticket-attachments-888088780947
  → 権限
```

`incident-platform-run`で絞り込み、`Storage オブジェクト ユーザー`が付与されていることを確認します。`allUsers`と`allAuthenticatedUsers`が存在しないことも確認します。

### Projectの権限

```text
IAM と管理
  → IAM
```

Principalで`incident-platform-run`を検索し、ProjectレベルのRoleを確認します。Bucketへ直接付与したRoleは、Bucketの権限画面でも確認します。

### Roleの内容

```text
IAM と管理
  → ロール
  → Storage Object User
```

Roleに含まれるPermissionと説明を確認します。

### 実効権限

```text
IAM と管理
  → Policy Troubleshooter
  → Manual
```

Principal、Bucket、Permissionを入力し、Grantedになった理由を確認します。

## 7. Phase 3との対応

### 完了

- Principal、Role、Permission、Resourceの確認
- Bucket単位の`roles/storage.objectUser`付与
- 作成、取得、削除Permissionの確認
- Policy Troubleshooterによる実効権限確認
- 添付の登録、取得、削除テスト
- 認証情報をGitへ保存しない構成

### 未完了

- 権限削除による403発生実験
- 権限復旧の再現
- Data Access監査ログの確認

ローカルDockerは人間のADCを使用するため、API Service Accountの403実験にはCloud Run環境またはService Accountの権限を直接評価できる手順を使用します。

## 8. 参照資料

- [Cloud StorageのIAM](https://docs.cloud.google.com/storage/docs/access-control/iam?hl=ja)
- [Bucket IAM Policyの管理](https://docs.cloud.google.com/storage/docs/access-control/using-iam-permissions?hl=ja)
- [Cloud Storage IAM Role](https://docs.cloud.google.com/storage/docs/access-control/iam-roles?hl=ja)
- [Cloud Storage IAM Permission](https://docs.cloud.google.com/storage/docs/access-control/iam-permissions?hl=ja)
- [Policy Troubleshooter](https://docs.cloud.google.com/policy-intelligence/docs/troubleshoot-access?hl=ja)
- [Resourceの完全名](https://docs.cloud.google.com/iam/docs/full-resource-names?hl=ja)
- [Data Access監査ログの設定](https://docs.cloud.google.com/logging/docs/audit/configure-data-access?hl=ja)
- [Cloud Storage監査ログ](https://docs.cloud.google.com/storage/docs/audit-logging?hl=ja)
- [Service Accountの権限借用](https://docs.cloud.google.com/iam/docs/service-account-impersonation?hl=ja)

## 9. Phase 3未完了事項の詳細

### 9.1 未完了事項

| 項目 | 目的 | 完了条件 |
| --- | --- | --- |
| 403・復旧実験 | IAM不足時の挙動を理解 | 拒否、原因特定、復旧を再現 |
| Data Access監査ログ | Object操作を追跡 | 成功・失敗ログを確認 |
| 過剰Roleの棚卸し | 最小権限を確認 | 必要性と対応方針を記録 |

権限削除はGoogle Cloudへ変更を加えます。人間が実行し、削除直後に復旧できる状態で行います。

## 10. Data Access監査ログの準備

### 10.1 目的

Cloud StorageのObject作成、取得、削除はData Access監査ログの対象です。Data Access監査ログは通常無効で、明示的に有効化する必要があります。

ログ量に応じてCloud Logging料金が発生する可能性があります。実験後に継続利用するか判断します。

### 10.2 Consoleで有効化

```text
IAM と管理
  → 監査ログ
  → Google Cloud Storage
  → Permission types
```

次を有効化して保存します。

- Data Read: Object取得を記録
- Data Write: Object作成・削除を記録

Data Accessログを閲覧できない場合は、閲覧者に`roles/logging.privateLogViewer`が必要です。

### 10.3 設定確認

Project IAM Policyの`auditConfigs`を確認します。

```powershell
gcloud projects get-iam-policy gcp-cloud-incident-platform `
  --format="yaml(auditConfigs)"
```

`storage.googleapis.com`に`DATA_READ`と`DATA_WRITE`が表示されることを確認します。親OrganizationやFolderで設定されている場合は、Projectの出力だけでは全体を確認できない場合があります。

## 11. 403・復旧実験

### 11.1 前提条件

- 現在の添付機能がCloud RunへDeploy済み
- Cloud RunのAPIが`incident-platform-run`を使用
- Data Write監査ログが有効
- 復旧コマンドを別のメモへ用意
- 実験中に他の利用者が添付操作をしない

ローカルDockerは人間のADCを使用するため、この実験には使用しません。

Cloud RunのService Accountを確認します。

```powershell
gcloud run services describe incident-platform `
  --region=asia-northeast1 `
  --format="value(spec.template.spec.serviceAccountName)"
```

次が返ることを確認します。

```text
incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com
```

### 11.2 現在のPolicyを保存

```powershell
$backupPath = Join-Path $env:TEMP "attachment-bucket-iam-before-phase3.json"

gcloud storage buckets get-iam-policy `
  gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --format=json > $backupPath

Get-Item -LiteralPath $backupPath
```

Policy全体を戻す`set-iam-policy`は、他の同時変更を上書きする可能性があります。復旧には対象Bindingだけを追加する方法を使用し、保存ファイルは比較用にします。

### 11.3 正常状態を記録

Policy Troubleshooterで現在の許可を確認します。

```powershell
$resource = "//storage.googleapis.com/projects/_/buckets/gcp-cloud-incident-platform-ticket-attachments-888088780947"
$principal = "incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com"

gcloud policy-intelligence troubleshoot-policy iam "$resource" `
  --principal-email="$principal" `
  --permission="storage.objects.create"
```

`overallAccessState: CAN_ACCESS`を記録します。

### 11.4 Bucket Roleを一時削除

次のコマンドはIAMを変更します。人間が実行します。

```powershell
gcloud storage buckets remove-iam-policy-binding `
  gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --member="serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/storage.objectUser"
```

削除後、Policy Troubleshooterを再実行します。

```powershell
gcloud policy-intelligence troubleshoot-policy iam "$resource" `
  --principal-email="$principal" `
  --permission="storage.objects.create"
```

`CAN_ACCESS`ではなくなったことを確認します。

### 11.5 拒否を発生させる

Cloud Runの`/docs`を使用します。

1. `POST /tickets`で実験用Ticketを作成
2. `POST /tickets/{ticket_id}/attachments/uploads`を実行
3. 実行時刻、HTTP Status、Response bodyを記録

Cloud Storage内部ではPermission Denied、HTTP `403`が発生します。現在のAPIはStorage例外を変換するため、利用者には次が返ります。

```text
HTTP 503
{"detail":"Attachment storage unavailable"}
```

つまり、Phase 3で確認する403はCloud Storage側の拒否であり、API外部応答は503です。

### 11.6 拒否ログを確認

```text
Logging
  → ログ エクスプローラ
```

次のQueryを実行します。

```text
logName="projects/gcp-cloud-incident-platform/logs/cloudaudit.googleapis.com%2Fdata_access"
resource.type="gcs_bucket"
resource.labels.bucket_name="gcp-cloud-incident-platform-ticket-attachments-888088780947"
protoPayload.authenticationInfo.principalEmail="incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com"
protoPayload.status.code=7
```

`status.code=7`は`PERMISSION_DENIED`です。次を記録します。

- `timestamp`
- `authenticationInfo.principalEmail`
- `methodName`
- `resourceName`
- `status.code`
- `status.message`

ログ反映には時間がかかる場合があります。

### 11.7 Roleを復旧

拒否確認後、直ちに実行します。

```powershell
gcloud storage buckets add-iam-policy-binding `
  gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --member="serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/storage.objectUser"
```

### 11.8 復旧を確認

次の3点を確認します。

1. Bucket PolicyにBindingが戻った
2. Policy Troubleshooterが`CAN_ACCESS`
3. 添付アップロードURL発行がHTTP `201`

```powershell
$policy = gcloud storage buckets get-iam-policy `
  gs://gcp-cloud-incident-platform-ticket-attachments-888088780947 `
  --format=json | ConvertFrom-Json

$policy.bindings |
  Where-Object {
    $_.members -contains "serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com"
  } |
  Select-Object role, members, condition |
  Format-List

gcloud policy-intelligence troubleshoot-policy iam "$resource" `
  --principal-email="$principal" `
  --permission="storage.objects.create"
```

復旧後の成功操作も、Data Write監査ログでPrincipal、Method、Resourceを確認します。

## 12. 過剰Roleの棚卸し

### 12.1 API Service Account

確認済みの構成です。

| Scope | Role | 判断 |
| --- | --- | --- |
| Project | `roles/cloudsql.client` | DB接続に必要 |
| Bucket | `roles/storage.objectUser` | 添付操作に必要 |
| Pub/Sub Topic | `roles/pubsub.publisher` | Publishに必要 |
| Secret | `roles/secretmanager.secretAccessor` | DB Secret取得に必要 |

Resource単位のRoleはProject Policyに表示されないため、それぞれのResourceで確認します。

### 12.2 Default Compute Service Account

Project Policyで`roles/editor`が確認されています。今回のAPIとWorkerは専用Service Accountを使うため、直接の実行Identityではありません。

削除前にCloud Buildなどが利用していないか確認し、次を記録します。

- 使用中のServiceまたはBuildがあるか
- `roles/editor`が必要な理由
- より限定したRoleへ置換できるか
- 変更時の復旧方法

依存関係が不明な状態では削除しません。

### 12.3 Legacy Storage Role

Bucket PolicyにProject Owner、Editor、Viewer向けのLegacy Roleがあります。API Service Accountはこれらを使用していません。

Phase 3では次を記録します。

- Legacy BindingのPrincipal
- Project基本Roleとの関係
- Public Principalではないこと
- 削除判断は別作業とすること

## 13. Phase 3実施結果

### 13.1 対象

| 項目 | 内容 |
| --- | --- |
| 実施日 | 2026-08-18 |
| 実施者 | `adachiitsukiyishu@gmail.com` |
| Project | `gcp-cloud-incident-platform` |
| Bucket | `gcp-cloud-incident-platform-ticket-attachments-888088780947` |
| Principal | `incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com` |
| Cloud Run Revision | `incident-platform-00005-4kv` |

### 13.2 実施内容と目的

| 実施内容 | 目的 | 結果 |
| --- | --- | --- |
| Data Accessログを有効化 | Object操作を追跡する | `DATA_READ`と`DATA_WRITE`を有効化 |
| Bucket Roleを一時削除 | 最小権限と拒否時の挙動を確認する | Cloud Run APIがHTTP `503`を返した |
| Bucket Roleを復旧 | IAM変更を安全に元へ戻せることを確認する | `roles/storage.objectUser`を復旧 |
| Policy Troubleshooterを実行 | 実効権限と付与元を確認する | `CAN_ACCESS`を確認 |
| Cloud Run APIを再実行 | 復旧後の業務機能を確認する | アップロードURL発行がHTTP `201` |
| 過剰Roleを棚卸し | 最小権限化の候補を把握する | 即時削除せず対応方針を記録 |

IAMでは、PrincipalにRoleを付与し、Roleに含まれるPermissionでResourceへの操作可否が決まります。今回はBucketだけに付与したRoleを外し、APIの失敗と復旧を再現することで、この関係を確認しました。

### 13.3 権限削除と拒否結果

変更前は、API Service AccountにBucket単位で`roles/storage.objectUser`が付与されていました。このRoleには`storage.objects.create`など、添付Objectの操作に必要なPermissionが含まれます。

Roleを一時削除した後、Cloud Runの次のEndpointを実行しました。

```text
POST /tickets/{ticket_id}/attachments/uploads
```

確認結果は次のとおりです。

| 項目 | 結果 |
| --- | --- |
| 実行環境 | Cloud Run |
| API応答 | HTTP `503` |
| Response body | `{"detail":"Attachment storage unavailable"}` |
| 発生時刻 | 2026-08-18 12:16:26～29 UTC |
| Cloud Runログ | `run.googleapis.com/requests`で2件確認 |
| Cloud Storage拒否ログ | 未取得 |
| `status.code=7` | 未確認 |

APIはStorage例外を利用者向けのHTTP `503`へ変換します。そのため、Cloud Runログの503を今回の拒否動作の代替証跡としました。ただし、Cloud Storage内部の`PERMISSION_DENIED`を示す`status.code=7`は取得できていないため、未完了課題として残します。

### 13.4 権限復旧結果

拒否確認後、同じPrincipalへ`roles/storage.objectUser`を再付与しました。

| 確認項目 | 結果 |
| --- | --- |
| Bucket Policy | 対象Bindingを確認 |
| Binding Condition | なし |
| `storage.objects.create` | Roleに含まれる |
| Allow判定 | `ALLOW_ACCESS_STATE_GRANTED` |
| Deny判定 | `DENY_ACCESS_STATE_NOT_DENIED` |
| 最終判定 | `overallAccessState: CAN_ACCESS` |
| API動作 | HTTP `201` |

Policy Troubleshooterでは、`roles/storage.objectUser`のBindingにPrincipalが一致し、このRoleが`storage.objects.create`を含むため許可されたことを確認しました。復旧後にAPIがHTTP `201`を返したため、IAM設定だけでなく実際の機能も正常へ戻ったと判断しました。

### 13.5 Data Access監査ログ

Project IAM Policyでは、次の設定を確認しました。

```yaml
auditConfigs:
- auditLogConfigs:
  - logType: DATA_READ
  - logType: DATA_WRITE
  service: allServices
```

`allServices`はCloud Storageにも適用されます。有効化操作は2026-08-18 11:37:46 UTC、拒否テストは同日12:16 UTCであり、有効化は拒否テストより約39分前でした。

| 項目 | 結果 |
| --- | --- |
| Data Read設定 | 有効 |
| Data Write設定 | 有効 |
| `_Default` Sink | Data Accessを除外していない |
| Cloud Storage拒否ログ | 検索したが未取得 |
| 代替証跡 | Cloud RunのHTTP `503`ログ |
| 継続判断 | 現在は有効のまま。最終判断は未実施 |

Data AccessログはObjectの読取りや作成を「誰が、いつ、何に対して行ったか」確認するために使います。一方で、ログ量に応じた料金が発生する可能性があるため、継続利用は必要性とログ量を基に判断します。

### 13.6 過剰Roleの棚卸し結果

#### Default Compute Service Account

| 項目 | 結果 |
| --- | --- |
| Service Account | `888088780947-compute@developer.gserviceaccount.com` |
| Project Role | `roles/editor` |
| Cloud Build既定SA | 同じService Account |
| Cloud Build Trigger | なし |
| Compute Engine VM | なし |
| 判断 | 現時点ではRoleを維持 |

`roles/editor`は広い権限を持つため、最小権限の観点では縮小候補です。ただし、現在はCloud Buildの既定Service Accountであり、Cloud RunのソースDeployに影響する可能性があります。専用のCloud Build Service Accountへ移行し、必要なRoleを確認するまでは削除しません。

棚卸し中にCompute Engine APIを有効化しましたが、VMは作成されていません。

#### Legacy Storage Role

| Role | Principal |
| --- | --- |
| `roles/storage.legacyBucketOwner` | Project Owner、Editor |
| `roles/storage.legacyBucketReader` | Project Viewer |
| `roles/storage.legacyObjectOwner` | Project Owner、Editor |
| `roles/storage.legacyObjectReader` | Project Viewer |

Bucket作成時のConvenience ValueによるBindingです。API Service Accountはこれらではなく`roles/storage.objectUser`を使用しています。

| セキュリティ設定 | 結果 |
| --- | --- |
| `allUsers` | なし |
| `allAuthenticatedUsers` | なし |
| Public Access Prevention | `enforced` |
| Uniform Bucket-Level Access | 有効 |
| Legacy Roleの判断 | 今回は維持し、削除判断は別作業 |

### 13.7 結論と残課題

IAM Roleの削除によるAPI失敗、Roleの復旧、Policy Troubleshooterの許可判定、APIの正常復旧まで再現できました。これにより、Bucket単位の最小権限とIAM変更時の復旧手順を確認しました。

残課題は次のとおりです。

- Cloud Storage側の拒否ログと`status.code=7`を取得できなかった原因を調査する
- 正常なObject操作のData Read、Data Writeログを確認する
- Data Accessログを継続利用するか、料金と必要性を基に決定する
- Cloud Build専用Service Accountへの移行後、Default Compute SAの`roles/editor`縮小を検討する
- Legacy Storage Roleの削除影響を別作業で確認する
