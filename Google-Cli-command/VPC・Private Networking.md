# VPC・Private Networking（Phase 5）

## 1. 用語集

| 用語 | 初学者向けの意味 |
| --- | --- |
| VPC（Virtual Private Cloud） | Google Cloud上に作る論理的に分離されたネットワーク。Subnet、Route、Firewallなどをまとめる土台 |
| Subnet | VPCの中でIPアドレスを払い出す範囲。VPCはグローバル、Subnetはリージョン単位 |
| IPアドレス | ネットワーク上の接続先を識別する番号 |
| Public IP | インターネットから到達できる可能性があるIPアドレス。IAMや認証とは別に、公開経路を持つ |
| Private IP | インターネットでは経路制御されない内部用IPアドレス。このPhaseではCloud SQLへの接続に使う |
| CIDR | IPアドレス範囲の表記。`10.20.0.0/24`は`10.20.0.0`から`10.20.0.255`までの256個を表す |
| RFC 1918 | Private IPとして予約された範囲。`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16` |
| Route | 宛先のIP範囲へ、どの経路で通信を送るかを決める規則 |
| Firewall | 通信を許可または拒否する規則。送信元、宛先、プロトコル、ポートなどで制御する |
| Ingress | サービスへ入ってくる通信。例：利用者からIncident APIへのHTTPリクエスト |
| Egress | サービスから外へ出ていく通信。例：Cloud RunからCloud SQLへのDB接続 |
| Direct VPC egress | Connectorを作らず、Cloud Runから直接VPCへ送信する方式。新規構成では推奨方式 |
| Serverless VPC Access Connector | Cloud Runなどのサーバーレス環境とVPCを中継する専用リソース。常時稼働コストと管理対象が増える |
| `private-ranges-only` | Private IP宛ての通信だけをVPCへ送るEgress設定。外部APIや通常のGoogle API通信はVPCへ送らない |
| `all-traffic` | Cloud Runの全送信通信をVPCへ送るEgress設定。インターネット接続には通常Cloud NATも必要 |
| Private Google Access | 外部IPを持たないVPCリソースがGoogle APIへ到達するためのSubnet設定 |
| Cloud NAT | Private IPしか持たないVPCリソースがインターネットへ送信するためのNAT。受信公開には使わない |
| Private Service Access（PSA） | 利用者のVPCと、Cloud SQLなどGoogle管理サービスのネットワークをPrivateに接続する仕組み |
| Allocated IP range | PSA先のGoogle管理サービスが使用するため、VPCで予約するIP範囲 |
| Service Networking API | PSA接続を作成・管理するAPI。`servicenetworking.googleapis.com` |
| VPC Peering | 2つのVPC間でPrivate IP通信を可能にする接続。PSAではGoogle管理側VPCとのPeeringが作られる |
| Cloud SQL connection name | `project:region:instance`形式の識別名。Private IPそのものではない |
| Unix socket接続 | `/cloudsql/...`を使う現在の接続方式。現在のCloud Run構成ではCloud SQL Auth Proxy経由のPublic IP接続 |
| TCP接続 | `Private IP:5432`へ直接接続する方式。Phase 5ではCloud RunからCloud SQLへこの方式を使う |
| Network tag | Direct VPC egressを使うCloud Run Revisionへ付けられるタグ。Firewallの対象指定に使える |
| Revision | Cloud Runの変更不能な実行設定の版。VPCやSecretを変更すると新Revisionが作られる |
| Rollback | 問題が起きたとき、Public IP接続や以前のCloud Run設定へ戻す操作 |

## 2. Phase 5で理解する全体像

### 2.1 現在の経路

```text
利用者
  ↓ HTTPS（Public）
Incident API（Cloud Run）
  ├─ Cloud SQL Auth Proxy / Unix socket → Cloud SQL Public IP
  └─ Pub/Sub → AI Worker（Cloud Run）
                         ├─ Cloud SQL Auth Proxy / Unix socket → Cloud SQL Public IP
                         └─ Vertex AI
```

現在の`DATABASE_URL`は`/cloudsql/gcp-cloud-incident-platform:asia-northeast1:incident-db`を使うUnixソケット向けです。Cloud RunにVPCを接続するだけでは、このURLはPrivate IP直接接続へ変わりません。

### 2.2 Phase 5完了後の経路

```text
利用者
  ↓ HTTPS（Publicのまま）
Incident API（Cloud Run）
  ↓ Direct VPC egress（private-ranges-only）
incident-subnet-asia-northeast1（10.20.0.0/24）
  ↓ Private Service Access
Cloud SQL Private IP（10.30.0.0/24から割り当て）

Pub/Sub
  ↓ OIDC認証付きPush
AI Worker（Cloud Run）
  ├─ Direct VPC egress → Cloud SQL Private IP:5432
  └─ 通常の送信経路 → Vertex AI
```

VPC接続はEgressの設定です。Incident APIへのIngressを非公開にする設定ではありません。Incident APIは利用者向けに公開を維持し、WorkerはPub/SubのOIDC認証を維持します。

`private-ranges-only`を採用するため、Cloud SQLのPrivate IP宛て通信だけがVPCへ流れます。Vertex AI、Pub/Sub、その他の外部APIへの通信は従来の経路を使うため、このPhaseではCloud NATを作りません。

## 3. このプロジェクトで使う固定値

この手順ではPowerShell変数や環境変数を使わず、対象をすべてコマンドへ明記します。

| 項目 | 固定値 |
| --- | --- |
| Project ID | `gcp-cloud-incident-platform` |
| Project number | `888088780947` |
| Region | `asia-northeast1` |
| Incident API | `incident-platform` |
| AI Worker | `incident-worker` |
| Cloud SQL | `incident-db` |
| 新規VPC | `incident-vpc` |
| 新規Subnet | `incident-subnet-asia-northeast1` |
| Subnet CIDR | `10.20.0.0/24` |
| PSA予約範囲名 | `incident-cloudsql-private-range` |
| PSA CIDR | `10.30.0.0/24` |
| Private接続用Secret | `incident-database-url-private` |
| API用Service Account | `incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com` |
| Worker用Service Account | `incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com` |

`10.20.0.0/24`と`10.30.0.0/24`は、既存`default` VPCの`asia-northeast1` Subnetである`10.146.0.0/20`とは重複しません。Direct VPC egressのSubnetは`/26`以上が必要で、`/24`はその条件を満たします。

## 4. 実行ルールと重要な注意

- 以下はWindows PowerShell向けです。
- この環境では`gcloud.ps1`が実行ポリシーで拒否されるため、`gcloud.cmd`を使います。
- 1つのコードブロックには1つの操作だけを記載しています。
- 作成コマンドは初回だけ実行します。成功後に同じ`create`コマンドを再実行すると「既に存在する」エラーになります。
- 変更コマンドの前後で、直後に記載した確認コマンドを実行します。
- Cloud SQLへPrivate IPを追加すると、後からPrivate IP設定そのものを解除できません。Public IPは再度有効化できます。
- Cloud SQLへのPrivate IP追加時には再起動と短時間の停止が発生します。
- Secretの実値、DBパスワード、接続URLをターミナル履歴、Markdown、Gitへ記録しません。
- Phase 5の作業中はCloud SQLのPublic IPを残し、Private接続の動作確認後に無効化します。
- `--set-secrets`は既存Secret設定を置き換えるため、この手順では既存設定を保持する`--update-secrets`を使います。

## 5. Phase 5のタスク一覧

1. 操作対象、権限、有効API、既存CIDRを確認する。
2. Service Networking APIを有効化する。
3. Custom mode VPCとSubnetを作成する。
4. Cloud SQL用のPrivate Service Accessを作成する。
5. Cloud SQLを起動し、バックアップを取得する。
6. Cloud SQLへPrivate IPを追加する。Public IPは一時的に残す。
7. Private TCP接続用のSecretを作成する。
8. Cloud Run APIとWorkerへDirect VPC egressとPrivate DB接続を設定する。
9. API、DB、Pub/Sub、Worker、Vertex AIの一連の動作を確認する。
10. Cloud SQLのPublic IPを無効化し、Private経路だけで動くことを確認する。
11. 必要に応じてWorkerのIngressを`internal`へ制限する。
12. CIDR、通信経路、エラー、復旧方法、採用理由を記録する。

## 6. 変更前の確認コマンド

### 6.1 アクティブアカウント

```powershell
gcloud.cmd auth list `
  --filter="status:ACTIVE" `
  --format="value(account)"
```

- 役割：現在操作に使われるGoogleアカウントを確認する。
- 期待される結果：`adachiitsukiyishu@gmail.com`が表示される。

### 6.2 対象Project

```powershell
gcloud.cmd config get-value project
```

- 役割：誤ったProjectへの操作を防ぐ。
- 期待される結果：`gcp-cloud-incident-platform`が表示される。

### 6.3 Cloud Runの既定Region

```powershell
gcloud.cmd config get-value run/region
```

- 役割：Cloud Runの操作先Regionを確認する。
- 期待される結果：`asia-northeast1`が表示される。

### 6.4 Phase 5で使うAPI

```powershell
gcloud.cmd services list `
  --enabled `
  --project=gcp-cloud-incident-platform `
  --filter="name:(compute.googleapis.com OR servicenetworking.googleapis.com OR run.googleapis.com OR sqladmin.googleapis.com)" `
  --format="table(name)"
```

- 役割：Compute Engine、Service Networking、Cloud Run、Cloud SQL Admin APIの有効状態を確認する。
- 期待される結果：作業開始前はService Networking APIがなくてもよい。7.1実行後は4つすべてが表示される。

### 6.5 既存VPC

```powershell
gcloud.cmd compute networks list `
  --project=gcp-cloud-incident-platform `
  --format="table(name,subnetMode,routingConfig.routingMode,description)"
```

- 役割：同名VPCがないことと既存ネットワークを確認する。
- 期待される結果：作業前は`default`のみで、`incident-vpc`は存在しない。

### 6.6 既存SubnetとCIDR

```powershell
gcloud.cmd compute networks subnets list `
  --project=gcp-cloud-incident-platform `
  --regions=asia-northeast1 `
  --format="table(name,network.basename(),region.basename(),ipCidrRange,stackType,privateIpGoogleAccess)"
```

- 役割：新しいCIDRと重複するSubnetがないことを確認する。
- 期待される結果：`10.20.0.0/24`および`10.30.0.0/24`と重複する範囲がない。

### 6.7 既存のPSA予約範囲

```powershell
gcloud.cmd compute addresses list `
  --global `
  --project=gcp-cloud-incident-platform `
  --filter="purpose=VPC_PEERING" `
  --format="table(name,address,prefixLength,purpose,status,network.basename())"
```

- 役割：同名の予約範囲とCIDR重複がないことを確認する。
- 期待される結果：作業前は`incident-cloudsql-private-range`が存在しない。

### 6.8 Cloud SQLの状態とIP設定

```powershell
gcloud.cmd sql instances describe incident-db `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,state,region,connectionName,ipAddresses,settings.activationPolicy,settings.ipConfiguration)"
```

- 役割：起動状態、Public IP、Private IP、接続先VPCを確認する。
- 期待される結果：Private IP追加前は`type: PRIVATE`と`privateNetwork`がない。

### 6.9 Incident APIのVPC設定

```powershell
gcloud.cmd run services describe incident-platform `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(metadata.name,status.conditions,spec.template.metadata.annotations)"
```

- 役割：APIの現在のVPC、Cloud SQL socket、Egress設定を確認する。
- 期待される結果：作業前はCloud SQL instance annotationはあるが、Direct VPC egress設定はない。

### 6.10 WorkerのVPC設定

```powershell
gcloud.cmd run services describe incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(metadata.name,status.conditions,spec.template.metadata.annotations)"
```

- 役割：Workerの現在のVPC、Cloud SQL socket、Egress設定を確認する。
- 期待される結果：作業前はCloud SQL instance annotationはあるが、Direct VPC egress設定はない。

## 7. VPCとPrivate Service Accessを作る

### 7.1 Service Networking APIを有効化

```powershell
gcloud.cmd services enable servicenetworking.googleapis.com `
  --project=gcp-cloud-incident-platform
```

- 役割：Cloud SQL用Private Service Accessを作成できるようにする。
- 期待される結果：処理が正常終了し、APIがEnabledになる。

確認：

```powershell
gcloud.cmd services list `
  --enabled `
  --project=gcp-cloud-incident-platform `
  --filter="name:servicenetworking.googleapis.com" `
  --format="value(name)"
```

- 役割：API有効化の反映を確認する。
- 期待される結果：`servicenetworking.googleapis.com`を含むサービス名が表示される。

### 7.2 Custom mode VPCを作成

```powershell
gcloud.cmd compute networks create incident-vpc `
  --project=gcp-cloud-incident-platform `
  --subnet-mode=custom `
  --bgp-routing-mode=regional `
  --description="Phase 5 private network for the incident platform"
```

- 役割：このシステム専用のVPCを作成する。
- 期待される結果：`Created`が表示される。

確認：

```powershell
gcloud.cmd compute networks describe incident-vpc `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,autoCreateSubnetworks,routingConfig.routingMode)"
```

- 役割：VPC名、Custom mode、Regional routingを確認する。
- 期待される結果：`autoCreateSubnetworks: false`、`routingMode: REGIONAL`が表示される。

### 7.3 Cloud Run用Subnetを作成

```powershell
gcloud.cmd compute networks subnets create incident-subnet-asia-northeast1 `
  --project=gcp-cloud-incident-platform `
  --network=incident-vpc `
  --region=asia-northeast1 `
  --range=10.20.0.0/24 `
  --stack-type=IPV4_ONLY `
  --enable-private-ip-google-access
```

- 役割：Cloud Run Direct VPC egressがIPを受け取るSubnetを作成する。
- 期待される結果：`Created`が表示される。

確認：

```powershell
gcloud.cmd compute networks subnets describe incident-subnet-asia-northeast1 `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(name,network,region,ipCidrRange,stackType,privateIpGoogleAccess)"
```

- 役割：Subnetの所属VPC、Region、CIDR、Google API到達設定を確認する。
- 期待される結果：`10.20.0.0/24`、`IPV4_ONLY`、`privateIpGoogleAccess: true`が表示される。

### 7.4 Cloud SQL用Private IP範囲を予約

```powershell
gcloud.cmd compute addresses create incident-cloudsql-private-range `
  --project=gcp-cloud-incident-platform `
  --global `
  --purpose=VPC_PEERING `
  --addresses=10.30.0.0 `
  --prefix-length=24 `
  --network=incident-vpc `
  --description="Private Service Access range for Cloud SQL"
```

- 役割：Google管理側のCloud SQLネットワークが使うPrivate IP範囲を予約する。
- 期待される結果：`Created`が表示される。

確認：

```powershell
gcloud.cmd compute addresses describe incident-cloudsql-private-range `
  --project=gcp-cloud-incident-platform `
  --global `
  --format="yaml(name,address,prefixLength,purpose,status,network)"
```

- 役割：予約範囲、Prefix、用途、所属VPCを確認する。
- 期待される結果：`10.30.0.0`、`24`、`VPC_PEERING`が表示される。

### 7.5 Private Service Access接続を作成

```powershell
gcloud.cmd services vpc-peerings connect `
  --project=gcp-cloud-incident-platform `
  --service=servicenetworking.googleapis.com `
  --ranges=incident-cloudsql-private-range `
  --network=incident-vpc
```

- 役割：`incident-vpc`とGoogle管理サービス側ネットワークをPrivate接続する。
- 期待される結果：長時間Operationが正常終了し、Peeringが作成される。

確認：

```powershell
gcloud.cmd services vpc-peerings list `
  --project=gcp-cloud-incident-platform `
  --network=incident-vpc `
  --format="table(network,peering,service,ranges,state)"
```

- 役割：PSAのPeeringと予約範囲を確認する。
- 期待される結果：Service NetworkingとのPeeringが`ACTIVE`として表示される。

## 8. Cloud SQLへPrivate IPを追加する

### 8.1 Cloud SQLを起動

```powershell
gcloud.cmd sql instances patch incident-db `
  --project=gcp-cloud-incident-platform `
  --activation-policy=always
```

- 役割：停止中の場合にCloud SQLを起動し、バックアップと接続テストを可能にする。
- 期待される結果：更新Operationが正常終了する。

確認：

```powershell
gcloud.cmd sql instances describe incident-db `
  --project=gcp-cloud-incident-platform `
  --format="value(state)"
```

- 役割：Cloud SQLの起動完了を確認する。
- 期待される結果：`RUNNABLE`が表示される。

### 8.2 変更前バックアップを作成

```powershell
gcloud.cmd sql backups create `
  --project=gcp-cloud-incident-platform `
  --instance=incident-db `
  --description="before-phase5-private-ip-2026-08-21"
```

- 役割：Private IP追加前の復旧点を作る。
- 期待される結果：バックアップ作成Operationが正常終了する。

確認：

```powershell
gcloud.cmd sql backups list `
  --project=gcp-cloud-incident-platform `
  --instance=incident-db `
  --sort-by="~endTime" `
  --limit=5 `
  --format="table(id,status,type,endTime,description)"
```

- 役割：変更前バックアップの完了状態を確認する。
- 期待される結果：説明が`before-phase5-private-ip-2026-08-21`、状態が`SUCCESSFUL`の行が表示される。

### 8.3 Private IPを追加し、Public IPは残す

```powershell
gcloud.cmd beta sql instances patch incident-db `
  --project=gcp-cloud-incident-platform `
  --network=projects/gcp-cloud-incident-platform/global/networks/incident-vpc `
  --assign-ip
```

- 役割：既存Cloud SQLへPrivate IPを追加する。`--assign-ip`により検証中はPublic IPも維持する。
- 期待される結果：再起動を伴う更新Operationが正常終了する。

確認：

```powershell
gcloud.cmd sql instances describe incident-db `
  --project=gcp-cloud-incident-platform `
  --format="yaml(state,ipAddresses,settings.ipConfiguration.privateNetwork,settings.ipConfiguration.ipv4Enabled)"
```

- 役割：Private IPとPublic IPの両方、および接続VPCを確認する。
- 期待される結果：`type: PRIVATE`と`type: PRIMARY`があり、`privateNetwork`が`incident-vpc`を指す。

> 既存Cloud SQLインスタンスには、作成済みPSAの個別range名を`--allocated-ip-range-name`で後付けできません。このVPCにはPSA範囲を1つだけ接続し、Cloud SQLがその範囲を使用する構成にしています。

## 9. Private TCP接続用Secretを作る

### 9.1 Secretコンテナを作成

```powershell
gcloud.cmd secrets create incident-database-url-private `
  --project=gcp-cloud-incident-platform `
  --replication-policy=automatic
```

- 役割：Private IP用`DATABASE_URL`を保存するSecretを作る。
- 期待される結果：Secretが作成されたことを示すメッセージが表示される。

確認：

```powershell
gcloud.cmd secrets describe incident-database-url-private `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,replication)"
```

- 役割：Secret名とReplication設定を確認する。
- 期待される結果：`incident-database-url-private`とAutomatic replicationが表示される。

### 9.2 Incident APIへSecret参照権限を付与

```powershell
gcloud.cmd secrets add-iam-policy-binding incident-database-url-private `
  --project=gcp-cloud-incident-platform `
  --member="serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

- 役割：APIのService Accountだけが新しいDB接続Secretを参照できるようにする。
- 期待される結果：IAM policyが更新されたことを示すメッセージが表示される。

### 9.3 WorkerへSecret参照権限を付与

```powershell
gcloud.cmd secrets add-iam-policy-binding incident-database-url-private `
  --project=gcp-cloud-incident-platform `
  --member="serviceAccount:incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

- 役割：WorkerのService Accountだけが新しいDB接続Secretを参照できるようにする。
- 期待される結果：IAM policyが更新されたことを示すメッセージが表示される。

確認：

```powershell
gcloud.cmd secrets get-iam-policy incident-database-url-private `
  --project=gcp-cloud-incident-platform `
  --format="table(bindings.role,bindings.members)"
```

- 役割：APIとWorkerに`roles/secretmanager.secretAccessor`が付いていることを確認する。
- 期待される結果：両方のService Accountが表示される。

### 9.4 Secret値を準備

8.3の確認コマンドで表示されたPrivate IPと、既存`incident` DBユーザーのパスワードを使い、次の形式の1行をUTF-8テキストとして保存します。

```text
postgresql+psycopg://incident:URLエンコード済みパスワード@確認したPrivate-IP:5432/incidents?sslmode=require
```

保存先は次の固定パスです。

```text
C:\Users\ITSUKI\AppData\Local\Temp\incident-database-url-private.txt
```

パスワード中の`@`、`:`、`/`、`?`、`#`、`%`などはURLエンコードが必要です。このファイルをProjectフォルダー内へ作成しないでください。

### 9.5 Secret versionを追加

```powershell
gcloud.cmd secrets versions add incident-database-url-private `
  --project=gcp-cloud-incident-platform `
  --data-file="C:\Users\ITSUKI\AppData\Local\Temp\incident-database-url-private.txt"
```

- 役割：Private接続URLをSecret Managerへ保存する。
- 期待される結果：新しいVersion番号が作成される。Secretの実値は出力されない。

確認：

```powershell
gcloud.cmd secrets versions list incident-database-url-private `
  --project=gcp-cloud-incident-platform `
  --format="table(name,state,createTime)"
```

- 役割：Secret versionが有効であることを、実値を表示せず確認する。
- 期待される結果：`ENABLED`のVersionが1つ以上表示される。

Secret登録後、ローカル一時ファイルを削除します。

```powershell
Remove-Item -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\incident-database-url-private.txt"
```

- 役割：ローカルに残ったDB接続情報を削除する。
- 期待される結果：コマンドが正常終了し、対象ファイルがなくなる。

## 10. Cloud RunをPrivate DB接続へ切り替える

### 10.1 Incident APIへDirect VPC egressとPrivate Secretを設定

```powershell
gcloud.cmd run services update incident-platform `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --network=incident-vpc `
  --subnet=incident-subnet-asia-northeast1 `
  --vpc-egress=private-ranges-only `
  --update-secrets=DATABASE_URL=incident-database-url-private:latest
```

- 役割：APIのPrivate IP宛て通信をVPCへ送り、DB接続先をCloud SQL Private IPへ変更する。
- 期待される結果：新RevisionがReadyになり、トラフィックが新Revisionへ移る。

確認：

```powershell
gcloud.cmd run services describe incident-platform `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(status.conditions,status.latestReadyRevisionName,status.traffic,spec.template.metadata.annotations,spec.template.spec.containers[0].env)"
```

- 役割：Revision、VPC、Egress、Secret参照を確認する。
- 期待される結果：Readyが`True`で、`incident-vpc`、Subnet、`private-ranges-only`、Private Secret参照が表示される。

### 10.2 WorkerへDirect VPC egressとPrivate Secretを設定

```powershell
gcloud.cmd run services update incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --network=incident-vpc `
  --subnet=incident-subnet-asia-northeast1 `
  --vpc-egress=private-ranges-only `
  --update-secrets=DATABASE_URL=incident-database-url-private:latest
```

- 役割：WorkerのPrivate IP宛て通信をVPCへ送り、DB接続先をCloud SQL Private IPへ変更する。
- 期待される結果：新RevisionがReadyになり、トラフィックが新Revisionへ移る。

確認：

```powershell
gcloud.cmd run services describe incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(status.conditions,status.latestReadyRevisionName,status.traffic,spec.template.metadata.annotations,spec.template.spec.containers[0].env)"
```

- 役割：Revision、VPC、Egress、Secret参照を確認する。
- 期待される結果：Readyが`True`で、`incident-vpc`、Subnet、`private-ranges-only`、Private Secret参照が表示される。

## 11. 疎通と障害の確認

### 11.1 APIのDB読み取り

```powershell
Invoke-RestMethod -Method Get -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets"
```

- 役割：APIからCloud SQLへ接続し、既存Ticketを読み取れることを確認する。
- 期待される結果：HTTP 200相当でTicket一覧が返る。接続失敗時はHTTP 500になる。

### 11.2 APIからTicketを作成

```powershell
Invoke-RestMethod -Method Post -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets" -ContentType "application/json" -Body '{"title":"Phase 5 private network test","raw_question":"Private経路でDB保存と非同期処理を確認します。"}'
```

- 役割：DB書き込み、Pub/Sub Publish、Worker処理を開始する。
- 期待される結果：HTTP 201相当でTicket IDと`queued`が返る。

### 11.3 APIログ

```powershell
gcloud.cmd run services logs read incident-platform `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --limit=30
```

- 役割：Private DB切替後のAPI起動エラー、接続エラー、HTTP結果を確認する。
- 期待される結果：新RevisionでDB接続エラーがなく、テストリクエストが成功している。

### 11.4 Workerログ

```powershell
gcloud.cmd run services logs read incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --limit=30
```

- 役割：Pub/Sub Push、Vertex AI呼び出し、Cloud SQL更新の結果を確認する。
- 期待される結果：テストTicketが処理され、DB接続やVertex AI到達エラーがない。

### 11.5 VPCのRoute

```powershell
gcloud.cmd compute routes list `
  --project=gcp-cloud-incident-platform `
  --filter="network:incident-vpc" `
  --format="table(name,network.basename(),destRange,nextHopGateway.basename(),priority)"
```

- 役割：Subnet routeとデフォルトRouteを確認する。
- 期待される結果：`10.20.0.0/24`のSubnet routeと`0.0.0.0/0`のデフォルトRouteが表示される。

### 11.6 VPCのFirewall

```powershell
gcloud.cmd compute firewall-rules list `
  --project=gcp-cloud-incident-platform `
  --filter="network:incident-vpc" `
  --format="table(name,direction,priority,sourceRanges,destinationRanges,disabled)"
```

- 役割：明示的なFirewall ruleの有無を確認する。
- 期待される結果：追加していなければ空になる。VPCには暗黙のEgress許可とIngress拒否がある。

この構成ではCloud SQLのPrivate IPへTCP接続するためのIngress Firewall ruleを利用者VPC側へ追加しません。将来Egress deny ruleを作る場合は、Cloud RunのNetwork tagとTCP 5432の許可を設計してから追加します。

## 12. Public IPを無効化してPrivate経路を証明する

11章のAPI、Worker、Vertex AI、DB更新がすべて成功した後だけ実行します。

```powershell
gcloud.cmd beta sql instances patch incident-db `
  --project=gcp-cloud-incident-platform `
  --no-assign-ip
```

- 役割：Cloud SQLのPublic IPを無効化し、Private IPだけにする。
- 期待される結果：再起動を伴う更新Operationが正常終了する。

確認：

```powershell
gcloud.cmd sql instances describe incident-db `
  --project=gcp-cloud-incident-platform `
  --format="yaml(state,ipAddresses,settings.ipConfiguration.privateNetwork,settings.ipConfiguration.ipv4Enabled)"
```

- 役割：Public IPがなく、Private IPだけが残ったことを確認する。
- 期待される結果：`type: PRIVATE`があり、`type: PRIMARY`がなく、`ipv4Enabled: false`になる。

その後、11.1から11.4をもう一度実行します。Public IPが存在しない状態で一連の処理が成功すれば、Cloud RunからCloud SQLへのPrivate経路を実証できます。

## 13. Cloud SQL Unix socket設定の後片付け

Private TCP接続とPublic IP無効化後の動作確認が完了した場合だけ実行します。現在の`DATABASE_URL`はTCP接続なので、旧Unix socket mountは不要です。

### 13.1 APIから旧Cloud SQL socket設定を削除

```powershell
gcloud.cmd run services update incident-platform `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --clear-cloudsql-instances
```

- 役割：API Revisionから未使用の`/cloudsql` socket mountを削除する。
- 期待される結果：新RevisionがReadyになり、Cloud SQL instance annotationがなくなる。

### 13.2 Workerから旧Cloud SQL socket設定を削除

```powershell
gcloud.cmd run services update incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --clear-cloudsql-instances
```

- 役割：Worker Revisionから未使用の`/cloudsql` socket mountを削除する。
- 期待される結果：新RevisionがReadyになり、Cloud SQL instance annotationがなくなる。

## 14. Worker Ingressの追加検証

Direct VPC egressは送信経路の設定であり、Ingress設定とは別です。同じProjectのPub/Sub PushはCloud Runの内部送信元として扱えるため、DBのPrivate化が完了した後にWorkerを`internal`へ制限できます。

```powershell
gcloud.cmd run services update incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --ingress=internal
```

- 役割：WorkerへのIngressを内部Google Cloudリソースに制限する。OIDC認証も引き続き必要。
- 期待される結果：新RevisionがReadyになる。

確認：

```powershell
gcloud.cmd run services describe incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --format="yaml(metadata.annotations,status.conditions,status.traffic)"
```

- 役割：Ingress設定とRevisionのReady状態を確認する。
- 期待される結果：Ingressが`internal`で、Readyが`True`になる。

11.2と11.4を再実行し、Pub/Sub Pushが成功することを確認します。失敗する場合は15.3ですぐ`all`へ戻します。

Incident APIは利用者向け公開APIのため、このPhaseではIngressを`all`のまま維持します。APIをPrivate化するには、利用者の接続方法、Load Balancer、IAP、VPNなどを別途設計する必要があります。

## 15. Rollback

### 15.1 Cloud SQLのPublic IPを再度有効化

```powershell
gcloud.cmd beta sql instances patch incident-db `
  --project=gcp-cloud-incident-platform `
  --assign-ip
```

- 役割：Private接続で復旧できない場合にPublic IPを再作成する。
- 期待される結果：Public IPが割り当てられる。以前と同じIPになる保証はない。

### 15.2 APIを旧Unix socket接続へ戻す

13.1を実行済みの場合は、Cloud SQL socket設定も同時に戻します。

```powershell
gcloud.cmd run services update incident-platform `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --clear-network `
  --update-secrets=DATABASE_URL=incident-database-url:2 `
  --add-cloudsql-instances=gcp-cloud-incident-platform:asia-northeast1:incident-db
```

- 役割：APIをVPCから外し、既存Public IP＋Unix socket接続へ戻す。
- 期待される結果：新RevisionがReadyになり、既存Ticketを取得できる。

### 15.3 Workerを旧Unix socket接続へ戻す

```powershell
gcloud.cmd run services update incident-worker `
  --project=gcp-cloud-incident-platform `
  --region=asia-northeast1 `
  --clear-network `
  --ingress=all `
  --update-secrets=DATABASE_URL=incident-database-url:latest `
  --add-cloudsql-instances=gcp-cloud-incident-platform:asia-northeast1:incident-db
```

- 役割：WorkerをVPCから外し、IngressとDB接続をPhase 5前へ戻す。
- 期待される結果：新RevisionがReadyになり、Pub/Sub Push処理が成功する。

> Cloud SQLへ追加済みのPrivate IP設定自体は解除できません。RollbackはPublic IPと旧Cloud Run接続を復旧する操作です。Cloud SQLが`incident-vpc`を使用している間は、VPC、PSA接続、予約範囲を削除しないでください。

## 16. よくあるエラーと確認先

| 症状 | 主な原因 | 最初に確認するコマンド |
| --- | --- | --- |
| `gcloud.ps1 cannot be loaded` | PowerShell execution policy | `gcloud.cmd --version` |
| Service Networking APIの`SERVICE_DISABLED` | API未有効 | 7.1のAPI有効化と確認 |
| VPCまたはSubnetの`already exists` | 作成コマンドを再実行した | 6.5、6.6の一覧 |
| IP range overlap | SubnetまたはPSA CIDRが既存範囲と重複 | 6.6、6.7の一覧 |
| PSA接続が失敗 | API反映待ち、予約範囲名違い、権限不足 | 7.1、7.4、7.5の確認 |
| Cloud SQL patchが失敗 | PSA未完成、VPC名違い、別Operation実行中 | 7.5と8.3の確認 |
| Cloud Run RevisionがReadyにならない | Secret権限、接続URL、Private IP、Subnet設定の誤り | 9.3、10.1、10.2の確認とログ |
| `password authentication failed` | Private SecretとCloud SQLユーザーのパスワード不一致 | Secretの実値を表示せず、作成元情報を再確認 |
| `connection refused`またはtimeout | Cloud SQL停止、IP/port誤り、VPC/PSA未接続 | 8.1、8.3、7.5の確認 |
| APIは成功するがWorkerが失敗 | Worker Secret、Pub/Sub Push、Vertex AI到達性の問題 | 10.2、11.4 |
| Workerを`internal`にするとPush失敗 | Pub/SubとCloud RunのProject/URL/Ingress条件不一致 | 15.3で`all`へ戻す |
| 外部APIへ到達できない | `all-traffic`を選びCloud NATがない | `private-ranges-only`へ戻す |

## 17. Direct VPC egressとConnectorの比較

| 観点 | Direct VPC egress | Serverless VPC Access Connector |
| --- | --- | --- |
| 中継リソース | 不要 | Connectorが必要 |
| 管理対象 | 少ない | ConnectorのInstance、CIDR、Scaling管理が必要 |
| Scale to zero | Cloud Runと同様 | Connector側の最小Instanceコストが残る |
| Network tag | Cloud Run Revisionへ直接設定可能 | Connector側のFirewall設計が中心 |
| このプロジェクトでの判断 | 採用 | 比較対象。作成しない |

このプロジェクトではDirect VPC egressを採用します。そのため、`vpcaccess.googleapis.com`の有効化やConnector作成はPhase 5の必須操作に含めません。

## 18. Phase 5の完了判定

- `incident-vpc`と`incident-subnet-asia-northeast1`の役割とCIDRを説明できる。
- `10.20.0.0/24`と`10.30.0.0/24`の用途の違いを説明できる。
- PSAが必要な理由と、通常のSubnetとの違いを説明できる。
- APIとWorkerのDirect VPC egressが`private-ranges-only`になっている。
- Cloud SQLにPrivate IPがあり、Public IPなしでもAPIからTicketを読み書きできる。
- Pub/Sub Push、Worker、Vertex AI、DB更新がPrivate化後も成功する。
- Public IP、Private IP、Unix socket、TCP直接接続の違いを説明できる。
- Cloud NATを作らなかった理由を説明できる。
- 失敗時にPublic IPと旧SecretへRollbackできる。
- CIDR表、通信経路、コマンド、失敗原因、復旧結果、方式選定理由を記録している。

## 19. 公式資料

- [VPC overview](https://cloud.google.com/vpc/docs/overview)
- [Cloud Run Direct VPC egress](https://cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Direct VPC egressとConnectorの比較](https://cloud.google.com/run/docs/configuring/connecting-vpc)
- [Cloud SQL for PostgreSQLのPrivate IP設定](https://cloud.google.com/sql/docs/postgres/configure-private-ip)
- [Cloud RunからCloud SQLへ接続](https://cloud.google.com/sql/docs/postgres/connect-run)
- [Private Service Access](https://cloud.google.com/vpc/docs/private-services-access)
