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
