# Cloud SQL Migration（Phase 4）

## 1. 目的

Cloud SQL for PostgreSQLの既存スキーマをAlembic管理へ移し、今後のDB構造変更を履歴として安全に適用・確認できる状態にする。

今回の作業では、アプリ起動時の`Base.metadata.create_all()`に依存していた既存DBについて、次を実施した。

- Alembicの導入
- 初期Migrationの作成
- Cloud SQLのバックアップ取得と自動バックアップ有効化
- 実DBと初期Migrationの構造比較
- 既存DBを`stamp`でAlembic管理へ移行
- Migration状態とスキーマ差分の確認

## 2. 対象環境

| 項目 | 値 |
|---|---|
| GCPプロジェクト | `gcp-cloud-incident-platform` |
| Cloud SQLインスタンス | `incident-db` |
| データベース | `incidents` |
| DBユーザー（アプリ） | `incident` |
| DBユーザー（管理） | `postgres` |
| Cloud SQL DBバージョン | PostgreSQL 17.10（設定値は`POSTGRES_17`） |
| リージョン | `asia-northeast1` |
| ゾーン | `asia-northeast1-b` |
| 可用性 | ZONAL |
| 接続方式 | Public IP + Cloud SQL Auth Proxy |
| ローカルpsql | PostgreSQL 17.11 |
| Alembic | 1.19.1 |

確認時点でCloud SQLは`RUNNABLE`、Activation Policyは`ALWAYS`だった。

## 3. Alembicの構成

主なファイルは次のとおり。

| ファイル | 役割 |
|---|---|
| `alembic.ini` | Migrationディレクトリやログなどの基本設定 |
| `migrations/env.py` | DB接続、SQLAlchemyモデル、Alembic実行環境の設定 |
| `migrations/script.py.mako` | 新しいRevisionファイルのテンプレート |
| `migrations/versions/` | Migration履歴の保存先 |
| `migrations/versions/0001_initial_schema.py` | 初期スキーマを表すRevision |

`migrations/env.py`は、アプリと同じ`DATABASE_URL`を使用し、`Base.metadata`を自動生成・比較対象としている。

```python
target_metadata = Base.metadata
```

型変更も検出するため、オンライン・オフラインの両方で`compare_type=True`を設定している。

## 4. 初期Migration

初期Revisionは次のとおり。

```text
Revision ID: 0001_initial
Parent: base
Head: 0001_initial
```

確認コマンド：

```powershell
uv run alembic heads
uv run alembic history --verbose
uv run alembic show 0001_initial
```

実際にDBへ適用せず、生成されるDDLを確認する場合：

```powershell
uv run alembic upgrade 0001_initial --sql
```

### 4.1 `tickets`テーブル

| カラム | PostgreSQL型 | NULL | 制約・用途 |
|---|---|---|---|
| `id` | `uuid` | 不可 | 主キー |
| `title` | `varchar(255)` | 不可 | タイトル |
| `raw_question` | `text` | 不可 | 問い合わせ本文 |
| `summary` | `text` | 可 | AI要約 |
| `category` | `varchar(100)` | 可 | 分類 |
| `severity` | `varchar(50)` | 可 | 重大度 |
| `status` | `varchar(20)` | 不可 | 処理状態 |
| `created_at` | `timestamp with time zone` | 不可 | 作成日時 |

制約・インデックス：

- `tickets_pkey`: `PRIMARY KEY (id)`

### 4.2 `attachments`テーブル

| カラム | PostgreSQL型 | NULL | 制約・用途 |
|---|---|---|---|
| `id` | `uuid` | 不可 | 主キー |
| `ticket_id` | `uuid` | 不可 | `tickets.id`への外部キー |
| `bucket_name` | `varchar(255)` | 不可 | Cloud Storageバケット |
| `object_name` | `varchar(1024)` | 不可 | オブジェクト名、UNIQUE |
| `original_filename` | `varchar(255)` | 不可 | 元ファイル名 |
| `content_type` | `varchar(255)` | 不可 | MIMEタイプ |
| `size` | `bigint` | 不可 | ファイルサイズ |
| `generation` | `bigint` | 可 | Cloud Storage generation |
| `created_at` | `timestamp with time zone` | 不可 | 作成日時 |

制約・インデックス：

- `attachments_pkey`: `PRIMARY KEY (id)`
- `attachments_object_name_key`: `UNIQUE (object_name)`
- `attachments_ticket_id_fkey`: `FOREIGN KEY (ticket_id) REFERENCES tickets(id)`
- `ix_attachments_ticket_id`: `ticket_id`のB-treeインデックス

## 5. Cloud SQLバックアップ

### 5.1 設定確認

```powershell
gcloud sql instances describe incident-db `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,state,settings.backupConfiguration)"
```

確認結果：

| 項目 | 結果 |
|---|---|
| Backup Tier | STANDARD |
| 自動バックアップ | 有効 |
| 開始時刻 | `18:00 UTC`（日本時間03:00） |
| 保持数 | 7 |

### 5.2 オンデマンドバックアップ

Migration前に次のバックアップを取得した。

```text
ID: 1787104554863
TYPE: ON_DEMAND
STATUS: SUCCESSFUL
DESCRIPTION: before-alembic-baseline-2026-08-19
```

作成コマンド：

```powershell
gcloud sql backups create `
  --instance=incident-db `
  --project=gcp-cloud-incident-platform `
  --description="before-alembic-baseline-2026-08-19"
```

一覧確認：

```powershell
gcloud sql backups list `
  --instance=incident-db `
  --project=gcp-cloud-incident-platform `
  --sort-by="~endTime"
```

Migrationなどの変更作業は、対象データを含むバックアップが`SUCCESSFUL`になってから行う。

## 6. Cloud SQLへの接続

### 6.1 `gcloud sql connect`を使う方法

```powershell
gcloud sql connect incident-db `
  --project=gcp-cloud-incident-platform `
  --user=postgres `
  --database=incidents
```

このコマンドはCloud SQL Auth Proxyを一時起動し、ローカルの`psql`を接続する。

### 6.2 Proxyを継続起動する方法

Alembicから接続する場合は、Proxyを継続起動する。

```powershell
$proxyPath = Join-Path $env:LOCALAPPDATA `
  "Google\Cloud SDK\google-cloud-sdk\bin\cloud-sql-proxy.exe"

& $proxyPath `
  --address 127.0.0.1 `
  --port 5433 `
  gcp-cloud-incident-platform:asia-northeast1:incident-db
```

接続確認：

```powershell
Test-NetConnection 127.0.0.1 -Port 5433
```

`TcpTestSucceeded : True`なら利用可能。

### 6.3 Proxyへ直接psql接続

```powershell
psql `
  -h 127.0.0.1 `
  -p 5433 `
  -U postgres `
  -d incidents `
  -W
```

## 7. 実DBのスキーマ確認

### 7.1 psqlメタコマンド

```sql
\dt public.*
\d+ public.tickets
\d+ public.attachments
\di+ public.*
```

終了：

```sql
\q
```

### 7.2 テーブル一覧

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

### 7.3 カラム一覧

```sql
SELECT
    table_name,
    ordinal_position,
    column_name,
    data_type,
    udt_name,
    character_maximum_length,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

### 7.4 制約一覧

```sql
SELECT
    cls.relname AS table_name,
    con.conname AS constraint_name,
    con.contype AS type,
    pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint AS con
JOIN pg_class AS cls
    ON cls.oid = con.conrelid
JOIN pg_namespace AS nsp
    ON nsp.oid = cls.relnamespace
WHERE nsp.nspname = 'public'
ORDER BY cls.relname, con.conname;
```

### 7.5 インデックス一覧

```sql
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

### 7.6 確認結果

実DBには`attachments`と`tickets`が存在した。確認時点の件数は次のとおり。

| テーブル | 件数 |
|---|---:|
| `tickets` | 9 |
| `attachments` | 1 |

Alembicの比較APIで、実DBと`Base.metadata`を比較した結果：

```text
Schema differences: 0
```

初期Migrationと実DBのカラム、型、NULL可否、主キー、外部キー、UNIQUE制約、インデックスは一致していた。

## 8. 既存DBをAlembic管理へ移行

### 8.1 なぜ`upgrade`ではなく`stamp`か

既存DBには`create_all()`によってテーブルが作成済みだった。その状態で`alembic upgrade head`を実行すると、同じテーブルを再作成しようとして失敗する。

実DBと初期Migrationが完全に一致することを確認したうえで、`stamp`を使用する。

`stamp`はMigrationのDDLを実行せず、`alembic_version`テーブルへ「このRevisionまで適用済み」と記録する。

### 8.2 Stamp前の状態

確認SQL：

```sql
SELECT to_regclass('public.alembic_version');
```

確認結果：

```text
NULL
```

つまり、テーブルは存在するがAlembic管理情報は存在しなかった。

### 8.3 Proxy用DATABASE_URLの準備

Secret Managerの`incident-database-url`はCloud RunのUnixソケット向けURLであり、ローカル環境ではそのまま利用できない。パスワードを表示せず、Proxy向けTCP URLへ変換する。

```powershell
$cloudRunDatabaseUrl = gcloud secrets versions access latest `
  --secret=incident-database-url `
  --project=gcp-cloud-incident-platform

$env:CLOUD_RUN_DATABASE_URL = $cloudRunDatabaseUrl

$pythonCode = @'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["CLOUD_RUN_DATABASE_URL"])
proxy_url = url.set(host="127.0.0.1", port=5433, query={})
print(proxy_url.render_as_string(hide_password=False))
'@

$env:DATABASE_URL = ($pythonCode | uv run python -).Trim()
```

接続URLやパスワードはコンソールへ表示しない。

### 8.4 Stamp前確認

```powershell
uv run alembic heads
uv run alembic current
```

Stamp前は次の状態だった。

```text
heads: 0001_initial (head)
current: Revisionなし
```

### 8.5 Stamp実行

```powershell
uv run alembic stamp 0001_initial
```

実行は成功した。

### 8.6 Stamp後確認

```powershell
uv run alembic current --check-heads
uv run alembic check
```

確認はすべて成功した。正常時の出力は次のとおり。

```text
0001_initial (head)
No new upgrade operations detected.
```

DBから直接確認する場合：

```sql
SELECT version_num
FROM alembic_version;
```

結果：

```text
0001_initial
```

### 8.7 接続情報の削除

```powershell
Remove-Item Env:DATABASE_URL
Remove-Item Env:CLOUD_RUN_DATABASE_URL
$cloudRunDatabaseUrl = $null
$pythonCode = $null
```

## 9. 今後のMigration手順

モデルを変更したら、次の順で作業する。

### 9.1 新しいRevisionを自動生成

```powershell
uv run alembic revision --autogenerate -m "変更内容"
```

自動生成されたファイルは必ずレビューする。Alembicの自動生成結果が常に意図どおりとは限らない。

### 9.2 差分確認

```powershell
uv run alembic history --verbose
uv run alembic show head
uv run alembic upgrade head --sql
```

### 9.3 バックアップ

Cloud SQLへ適用する前にオンデマンドバックアップを作成し、`SUCCESSFUL`を確認する。

### 9.4 Upgrade

```powershell
uv run alembic upgrade head
```

### 9.5 状態確認

```powershell
uv run alembic current --check-heads
uv run alembic check
```

### 9.6 Downgrade

```powershell
uv run alembic downgrade -1
```

本番DBでのDowngradeはデータ消失を伴う場合がある。Migrationファイルの`downgrade()`とバックアップを確認してから実行する。

## 10. 発生した問題と原因

### 10.1 `psql`が見つからない

症状：

```text
Psql client not found
```

原因：PostgreSQLはインストール済みだったが、次のパスが環境変数`Path`へ反映されていなかった。

```text
C:\Program Files\PostgreSQL\17\bin
```

確認：

```powershell
psql --version
where.exe psql
```

### 10.2 `\.\cloud-sql-proxy.exe`が見つからない

`\.\`は現在のディレクトリを表す。ProxyはCloud SDK配下にあるため、フルパスまたは`$proxyPath`で実行する必要があった。

### 10.3 ポート`5433`を利用できない

症状：

```text
Only one usage of each socket address is normally permitted
```

確認したところ、既存の`cloud-sql-proxy`がすでに`5433`を使用していた。新しいProxyを起動せず、その接続を再利用した。

確認コマンド：

```powershell
$connection = Get-NetTCPConnection -LocalPort 5433 -State Listen
$connection | Select-Object LocalAddress, LocalPort, OwningProcess
Get-Process -Id $connection.OwningProcess
```

### 10.4 `postgres`のパスワードが不明

Cloud SQL for PostgreSQLでは、初期`postgres`ユーザーにパスワードが未設定の場合がある。管理用`postgres`だけパスワードを設定した。

```powershell
gcloud sql users set-password postgres `
  --instance=incident-db `
  --project=gcp-cloud-incident-platform `
  --prompt-for-password
```

アプリ用`incident`ユーザーのパスワードを変更すると、Secret ManagerとCloud Runの接続設定更新が必要になるため、目的なく変更しない。

### 10.5 Cloud SQLとSecret Managerの認証情報が不一致

症状：

```text
password authentication failed for user "incident"
```

Proxyは正常で、Secret Managerの`incident-database-url`を使った接続だけが失敗した。このため、Cloud SQLのアプリ用`incident`ユーザーのパスワードを、Cloud Runが参照している既存Secretの値へ同期した。

共有管理者`postgres`のパスワードやSecretの内容は変更していない。同期後、既存Secretを使った接続に成功した。

## 11. 用語集

| 用語 | 意味 |
|---|---|
| Migration | DBスキーマの変更を順序付きで管理・適用する仕組み |
| Alembic | SQLAlchemy向けのMigrationツール |
| Revision | 1回分のDB変更を表す識別子付きファイル |
| Head | 現在のMigration履歴で最も新しいRevision |
| Base | Migration履歴の開始地点。何も適用していない状態 |
| Upgrade | 新しいRevisionへ進める操作 |
| Downgrade | 以前のRevisionへ戻す操作 |
| Stamp | DDLを実行せず、DBの適用済みRevisionだけを記録する操作 |
| Autogenerate | SQLAlchemy Metadataと実DBを比較してMigration候補を生成する機能 |
| Metadata | SQLAlchemyが保持するテーブル、カラム、制約などの定義情報 |
| `alembic_version` | DBに現在適用済みのRevisionを記録するAlembic管理テーブル |
| Baseline | 既存DBをMigration管理へ取り込む際の基準Revision |
| DDL | `CREATE TABLE`や`ALTER TABLE`など、DB構造を変更するSQL |
| Schema Drift | モデル、Migration履歴、実DBの構造が一致しなくなること |
| Transaction | 複数のDB操作を一つの処理単位として成功・失敗させる仕組み |
| Connection Pool | DB接続を再利用し、接続作成コストを抑える仕組み |
| `pool_pre_ping` | 使用前に接続の生存確認を行うSQLAlchemy設定 |
| Cloud SQL Auth Proxy | IAM認証を利用してCloud SQLへの安全な接続経路を作るProxy |
| Backup | DBを特定時点の状態へ復元するための保存データ |
| PITR | Point-in-Time Recovery。指定した時刻へDBを復元する機能 |
| RPO | どの時点までのデータ損失を許容するかという目標 |
| RTO | 障害発生後、どの程度の時間で復旧するかという目標 |
| HA | High Availability。冗長化により可用性を高める構成 |

## 12. Migration部分の完了状況

完了済み：

- Alembic導入
- 初期Revision作成
- Migrationのローカル`upgrade`・`downgrade`テスト
- Cloud SQLのオンデマンドバックアップ
- 自動バックアップ有効化
- 実DBスキーマ確認
- 初期Migrationとの機械比較（差分0件）
- `stamp`による既存DBのAlembic管理移行
- `current --check-heads`成功
- `alembic check`成功
- `0002_updated_at`による実際のスキーマ変更
- Cloud SQLへの`upgrade head`成功
- `tickets.updated_at`の型・NULL許可・既存データ保持を確認
- 取得済みバックアップから検証用Cloud SQLへの復元成功
- 復元データ件数と参照整合性の確認

Phase 4全体では、今後、`downgrade`演習、接続障害テスト、Publish失敗時のDB整合性検討、RPO/RTO・HA設計の整理を行う。

## 13. 実際のスキーマ変更結果

### 13.1 変更内容

`tickets`テーブルへ、更新日時を保存するNULL許可の`updated_at`を追加した。

```text
Revision: 0002_updated_at
Down revision: 0001_initial
型: timestamp with time zone
NULL許可: YES
```

### 13.2 適用前確認

```text
Alembic Revision: 0001_initial
updated_at: 存在しない
```

### 13.3 Upgrade

```powershell
uv run alembic upgrade head
```

実行結果：

```text
Running upgrade 0001_initial -> 0002_updated_at, Add updated_at to tickets.
```

### 13.4 適用後確認

```powershell
uv run alembic current --check-heads
uv run alembic check
```

確認結果：

```text
0002_updated_at (head)
No new upgrade operations detected.
```

Cloud SQLの実スキーマ確認結果：

```text
alembic_version: 0002_updated_at
updated_at型: timestamp with time zone
NULL許可: YES
tickets既存行数: 9
updated_atがNULLではない既存行数: 0
```

既存9件のチケットは保持され、追加カラムは意図どおりNULLで初期化された。「実際のスキーマ変更をMigrationで行う」課題は完了。


## 14. バックアップ復元リハーサル

### 14.1 目的

バックアップは、作成に成功しただけでは復旧手段として十分とはいえない。実際に別インスタンスへ復元し、接続、データ件数、参照整合性、スキーマの時点整合性を確認することで、障害時に利用できるバックアップであることを検証した。

本番インスタンスへ直接復元すると現在のデータを上書きするため、リハーサルでは検証専用の`incident-db-restore-rehearsal`を作成した。

### 14.2 使用したバックアップ

```text
Project: gcp-cloud-incident-platform
Source instance: incident-db
Backup ID: 1787104554863
Type: ON_DEMAND
Status: SUCCESSFUL
Description: before-alembic-baseline-2026-08-19
Start: 2026-08-19T01:55:54.869Z
End: 2026-08-19T01:56:55.715Z
```

確認コマンド：

```powershell
gcloud sql backups describe 1787104554863 `
  --instance=incident-db `
  --project=gcp-cloud-incident-platform `
  --format="yaml(id,status,type,startTime,endTime,description)"
```

`status: SUCCESSFUL`を確認してから復元を開始した。作成中または失敗したバックアップを変更作業や復旧計画の根拠にしてはならない。

### 14.3 検証用インスタンスの作成

最初はEditionとTierを省略したため、次のエラーになった。

```text
Invalid Tier (db-n1-standard-1) for (ENTERPRISE_PLUS) Edition.
```

PostgreSQL 17では、作成時にEditionを省略すると`ENTERPRISE_PLUS`が選択される場合がある。一方、暗黙に選択された`db-n1-standard-1`はEnterprise Plus用Tierではないため、組み合わせが不正だった。

復元検証は小規模データを対象とするため、Enterprise Editionと低コストTierを明示して作成した。

```powershell
gcloud sql instances create incident-db-restore-rehearsal `
  --project=gcp-cloud-incident-platform `
  --database-version=POSTGRES_17 `
  --region=asia-northeast1 `
  --edition=ENTERPRISE `
  --tier=db-f1-micro `
  --availability-type=zonal `
  --no-deletion-protection
```

作成結果：

```text
Name: incident-db-restore-rehearsal
Database version: POSTGRES_17
Zone: asia-northeast1-b
Tier: db-f1-micro
State: RUNNABLE
```

復元先のDBメジャーバージョンは復元元と互換性のあるものにする。また、実運用の性能試験を兼ねる場合は、本番と同じEdition、Tier、ストレージ、ネットワーク構成を使用する必要がある。今回は「バックアップからデータを戻せるか」の確認が目的であり、性能評価は対象外とした。

### 14.4 復元実行と時間計測

```powershell
$restoreStartedAt = Get-Date
$restoreTimer = [System.Diagnostics.Stopwatch]::StartNew()

gcloud sql backups restore 1787104554863 `
  --restore-instance=incident-db-restore-rehearsal `
  --backup-instance=incident-db `
  --backup-project=gcp-cloud-incident-platform `
  --project=gcp-cloud-incident-platform

$restoreExitCode = $LASTEXITCODE
$restoreTimer.Stop()
$restoreFinishedAt = Get-Date

[PSCustomObject]@{
  StartedAt  = $restoreStartedAt
  FinishedAt = $restoreFinishedAt
  Duration   = $restoreTimer.Elapsed
  ExitCode   = $restoreExitCode
}
```

結果：

```text
CLI計測開始: 2026-08-19 15:42:56 JST
CLI計測終了: 2026-08-19 16:29:03 JST
CLI計測時間: 00:46:06.8585913
ExitCode: 0
```

Cloud SQL Operationも確認した。

```powershell
gcloud sql operations list `
  --instance=incident-db-restore-rehearsal `
  --project=gcp-cloud-incident-platform `
  --sort-by="~startTime" `
  --limit=10 `
  --format="table(name,operationType,status,startTime,endTime,error)"
```

```text
Operation type: RESTORE_VOLUME
Status: DONE
Start: 2026-08-19T06:43:02.793Z
End: 2026-08-19T06:56:43.178Z
Cloud SQL内部の復元時間: 約13分40秒
Error: なし
```

CLI計測時間とCloud SQL Operationの時間は意味が異なる。Operation時間はCloud SQL側の復元処理時間であり、CLI計測時間には確認入力、待機、結果が端末へ返るまでの時間などが含まれる。RTOを検討するときは、DB内部の処理時間だけでなく、障害判断、インスタンス準備、接続先切り替え、データ検証、アプリケーション疎通まで含めた利用再開時間を測定する。

検証用インスタンスの作成には約9分46秒かかった。新規インスタンスを作成して復元する方式では、少なくとも「インスタンス作成時間＋復元時間＋検証・切り替え時間」が復旧時間に含まれる。

### 14.5 接続時の認証と権限

最初に`postgres`で接続したところ、バックアップ取得時点のパスワードが不明だったため認証に失敗した。

```text
FATAL: password authentication failed for user "postgres"
```

Cloud SQLは既存パスワードを表示できないため、検証用インスタンスの`postgres`パスワードだけを再設定した。

```powershell
gcloud sql users set-password postgres `
  --instance=incident-db-restore-rehearsal `
  --project=gcp-cloud-incident-platform `
  --prompt-for-password
```

再設定後、Cloud SQL Auth Proxy経由の接続には成功した。ただし、`postgres`で`tickets`と`attachments`を参照すると、次の権限エラーになった。

```text
ERROR: permission denied for table tickets
ERROR: permission denied for table attachments
```

Cloud SQLの`postgres`は、通常の自己管理PostgreSQLにおける完全なOS管理者相当のスーパーユーザーとは異なる。また、テーブルの所有者または権限を持つユーザーがアプリ用の`incident`であるため、データ確認は`incident`で行った。

検証用インスタンスの`incident`パスワードを一時的に再設定して接続した。

```powershell
gcloud sql users set-password incident `
  --instance=incident-db-restore-rehearsal `
  --project=gcp-cloud-incident-platform `
  --prompt-for-password

gcloud sql connect incident-db-restore-rehearsal `
  --project=gcp-cloud-incident-platform `
  --user=incident `
  --database=incidents
```

パスワード変更は検証用インスタンスだけに対して行い、本番`incident-db`のユーザーやSecret Managerは変更していない。

### 14.6 データ件数と参照整合性の確認

```sql
SELECT 'tickets' AS table_name, COUNT(*) AS row_count
FROM public.tickets
UNION ALL
SELECT 'attachments', COUNT(*)
FROM public.attachments;
```

結果：

```text
tickets: 9
attachments: 1
```

添付ファイルが存在しないチケットを参照していないか確認した。

```sql
SELECT COUNT(*) AS orphan_attachments
FROM public.attachments AS a
LEFT JOIN public.tickets AS t
  ON t.id = a.ticket_id
WHERE t.id IS NULL;
```

結果：

```text
orphan_attachments: 0
```

件数が復元元の記録と一致し、`attachments.ticket_id`の参照先がすべて存在したため、主要データの復元と参照整合性を確認できた。ただし、件数一致だけでは全データの完全一致を証明できない。より厳密な検証では、主キー範囲、重要列、集計値、ハッシュ、制約、インデックス、アプリケーションからの読み書きも確認する。

### 14.7 バックアップ時点のスキーマ確認

```sql
SELECT to_regclass('public.alembic_version');
```

結果は`NULL`であり、`alembic_version`は存在しなかった。

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'tickets'
  AND column_name = 'updated_at';
```

結果は0行であり、`tickets.updated_at`は存在しなかった。

使用したバックアップは`before-alembic-baseline-2026-08-19`であり、Alembic導入と`0002_updated_at`適用より前に取得されている。このため、`alembic_version`と`updated_at`が存在しないことは異常ではなく、バックアップ取得時点のDB状態へ正しく戻ったことを示している。

バックアップ復元は「現在のMigration Headへ戻す処理」ではなく、「バックアップを取得した時点へ戻す処理」である。復元後に現在のアプリケーションを接続する場合は、バックアップ時点から現在までのMigrationを順番に適用し、アプリケーションとDBスキーマの互換性を回復させる必要がある。

### 14.8 総合判定

```text
判定: バックアップ復元リハーサル成功

- バックアップ: SUCCESSFUL
- 検証用インスタンス: RUNNABLE
- 復元Operation: RESTORE_VOLUME / DONE
- Operationエラー: なし
- tickets: 9件
- attachments: 1件
- 孤立attachments: 0件
- バックアップ取得時点のスキーマを再現
```

取得済みバックアップから独立したCloud SQLインスタンスを復元でき、期待した件数、参照整合性、取得時点のスキーマを確認できたため、リハーサルは成功と判定した。

### 14.9 クリーンアップ

検証完了後は、継続課金を避けるため、対象名が本番`incident-db`ではなく`incident-db-restore-rehearsal`であることを確認してから削除する。

```powershell
gcloud sql instances describe incident-db-restore-rehearsal `
  --project=gcp-cloud-incident-platform `
  --format="yaml(name,state,region)"

gcloud sql instances delete incident-db-restore-rehearsal `
  --project=gcp-cloud-incident-platform
```

この記録の作成時点では、検証用インスタンスの削除完了は未確認である。削除後は`gcloud sql instances list`で残存していないことを確認する。

### 14.10 運用設計への学び

- バックアップの成功表示だけでなく、定期的な復元テストが必要。
- 復元は本番を上書きせず、隔離した検証用インスタンスで行う。
- バックアップの時刻とMigration Revisionを一緒に記録する。
- RPOは「どこまでのデータ損失を許容するか」、RTOは「いつまでにサービスを再開するか」を表す。
- 日次バックアップだけでは、最大でバックアップ間隔分のデータを失う可能性がある。より短いRPOが必要ならPITRを検討する。
- PITRを有効にしても、手順、権限、接続先切り替え、検証方法が未整備なら目標RTOを満たせない。
- 復元後の認証情報、DB権限、Secret Manager、Cloud Run接続先の扱いを復旧手順に含める。
- 件数確認に加えて、外部キー相当の参照整合性や重要データの内容を検証する。
- 復元したDBが古いRevisionの場合、アプリケーション接続前に必要なMigrationを適用する。
- 現在のZONAL構成はゾーン障害への自動フェイルオーバーを提供しない。短いRTOが必要ならREGIONAL HA構成も比較する。

今回の結果から、標準バックアップによる復元経路は利用可能と確認できた。次の課題は、許容するRPO/RTOを数値で決め、PITRとREGIONAL HAの費用対効果を評価し、アプリケーションを含む復旧手順を通しで計測することである。

## 15. DB接続障害テスト

### 15.1 目的と確認範囲

DB接続経路の一部が利用できなくなったときに、失敗を正しく検出できること、復旧後にアプリケーションを再デプロイせず再接続できること、SQLAlchemyの接続Poolが古い接続を再利用し続けないことを確認する。

テスト対象は次の4種類である。

| テスト | 影響範囲 | 確認内容 |
|---|---|---|
| ローカルProxy停止 | テスト端末だけ | Proxy停止中は接続に失敗し、再起動後は成功すること |
| 不正パスワード | テストプロセスだけ | 認証エラーを検出できること |
| 不正ポート | テストプロセスだけ | 到達不能な接続先を検出できること |
| Cloud SQL停止 | APIとWorkerを含む環境全体 | DB利用APIが失敗し、再起動後に再接続できること |

`src/incident_platform/db.py`では、次の設定を使用している。

```python
engine = create_engine(settings.database_url, pool_pre_ping=True)
```

`pool_pre_ping=True`は、Poolから接続を取り出すときに生存確認を行い、切断済みの接続を破棄して再接続する設定である。ただし、実行中のSQLやトランザクションが途中で切断された場合に、その処理を自動再実行する設定ではない。そのリクエストは失敗し、必要ならアプリケーション側でトランザクション全体を再試行する。

### 15.2 現在の確認結果

2026-08-19に、変更を伴わないコマンドで次を確認した。

| 項目 | 確認結果 |
|---|---|
| GCPプロジェクト | `gcp-cloud-incident-platform` |
| Cloud SQL | `incident-db` / `RUNNABLE` / `POSTGRES_17` |
| Activation Policy | `ALWAYS` |
| 可用性 | `ZONAL` |
| Cloud SQLインスタンス数 | 1台 |
| Cloud Run API Revision | `incident-platform-00005-4kv` |
| Cloud RunのDB Secret | `incident-database-url:2` |
| Secret `latest` | Version 2と一致 |
| `GET /health` | HTTP 200 |
| `GET /tickets` | HTTP 200 |

`/health`はDBへSQLを実行せず固定レスポンスを返すため、DB疎通確認には使用できない。DB接続障害の判定には、DBを読む`GET /tickets`またはProxy経由の`SELECT 1`を使用する。

このPowerShell環境では、`gcloud`が`gcloud.ps1`へ解決されると実行ポリシーで拒否される。そのため、以降は実行可能であることを確認済みの`gcloud.cmd`を明示的に解決して使用する。

### 15.3 共通の事前確認

次のスクリプトは、プロジェクト、対象インスタンス、Cloud RunのCloud SQL接続、DB Secret参照を確認する。いずれかが想定と異なる場合は、障害操作を実行せず停止する。

```powershell
$ErrorActionPreference = "Stop"
$Gcloud = (Get-Command gcloud.cmd -ErrorAction Stop).Source
$ProjectId = "gcp-cloud-incident-platform"
$Region = "asia-northeast1"
$Instance = "incident-db"
$ApiService = "incident-platform"
$ExpectedConnectionName = "${ProjectId}:${Region}:${Instance}"

$CurrentProject = (& $Gcloud config get-value project).Trim()
if ($CurrentProject -ne $ProjectId) {
  throw "Project mismatch: $CurrentProject"
}

$InstanceJson = (
  & $Gcloud sql instances describe $Instance `
    --project=$ProjectId `
    --format=json | ConvertFrom-Json
)

if ($InstanceJson.connectionName -ne $ExpectedConnectionName) {
  throw "Cloud SQL connection name mismatch."
}
if ($InstanceJson.state -ne "RUNNABLE") {
  throw "Cloud SQL is not RUNNABLE: $($InstanceJson.state)"
}

$ServiceJson = (
  & $Gcloud run services describe $ApiService `
    --project=$ProjectId `
    --region=$Region `
    --format=json | ConvertFrom-Json
)

$DatabaseUrlEnv = $ServiceJson.spec.template.spec.containers[0].env |
  Where-Object name -eq "DATABASE_URL"
$CloudSqlAnnotation =
  $ServiceJson.spec.template.metadata.annotations."run.googleapis.com/cloudsql-instances"

if ($CloudSqlAnnotation -ne $ExpectedConnectionName) {
  throw "Cloud Run Cloud SQL attachment mismatch."
}
if (-not $DatabaseUrlEnv.valueFrom.secretKeyRef.name -or
    -not $DatabaseUrlEnv.valueFrom.secretKeyRef.key) {
  throw "DATABASE_URL Secret reference is missing."
}

[PSCustomObject]@{
  Project               = $CurrentProject
  Instance              = $InstanceJson.name
  State                 = $InstanceJson.state
  ActivationPolicy      = $InstanceJson.settings.activationPolicy
  AvailabilityType      = $InstanceJson.settings.availabilityType
  ApiRevision           = $ServiceJson.status.latestReadyRevisionName
  DatabaseSecret        = $DatabaseUrlEnv.valueFrom.secretKeyRef.name
  DatabaseSecretVersion = $DatabaseUrlEnv.valueFrom.secretKeyRef.key
}
```

現在の確認結果は、`RUNNABLE`、`ALWAYS`、`ZONAL`、Secret Version `2`である。

### 15.4 ローカルDBプローブの準備

Cloud Runが実際に参照しているSecretバージョンを取得し、パスワードを表示せず、Proxy用TCP URLへ変換する。

```powershell
$ProxyPort = 5433
$ProxyPath = Join-Path $env:LOCALAPPDATA `
  "Google\Cloud SDK\google-cloud-sdk\bin\cloud-sql-proxy.exe"

if (-not (Test-Path -LiteralPath $ProxyPath)) {
  throw "Cloud SQL Auth Proxy was not found: $ProxyPath"
}

$ExistingListener = Get-NetTCPConnection `
  -LocalPort $ProxyPort `
  -State Listen `
  -ErrorAction SilentlyContinue
if ($ExistingListener) {
  throw "Port $ProxyPort is already in use."
}

$DatabaseSecretName = $DatabaseUrlEnv.valueFrom.secretKeyRef.name
$DatabaseSecretVersion = $DatabaseUrlEnv.valueFrom.secretKeyRef.key
$CloudRunDatabaseUrl = & $Gcloud secrets versions access $DatabaseSecretVersion `
  --secret=$DatabaseSecretName `
  --project=$ProjectId
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($CloudRunDatabaseUrl)) {
  throw "DATABASE_URL Secret access failed."
}

$env:CLOUD_RUN_DATABASE_URL = $CloudRunDatabaseUrl
$BuildProxyUrlCode = @'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["CLOUD_RUN_DATABASE_URL"])
proxy_url = url.set(host="127.0.0.1", port=5433, query={})
print(proxy_url.render_as_string(hide_password=False))
'@

$env:DATABASE_URL = ($BuildProxyUrlCode | uv run python -).Trim()
$ValidDatabaseUrl = $env:DATABASE_URL
```

DBプローブは、期待どおり接続できた場合、または期待どおり接続に失敗した場合だけExit Code `0`を返す。接続URL、パスワード、SQLAlchemyの詳細エラー本文は表示しない。

```powershell
$DbProbeCode = @'
import os
from sqlalchemy import create_engine, text

expected = os.environ.get("EXPECT_DB", "up")
engine = create_engine(
    os.environ["DATABASE_URL"],
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    connected = True
    error_type = "none"
except Exception as exc:
    connected = False
    error_type = type(exc).__name__
finally:
    engine.dispose()

expected_connected = expected == "up"
passed = connected == expected_connected
print(
    f"{'PASS' if passed else 'FAIL'}: "
    f"expected={expected}, connected={connected}, error={error_type}"
)
raise SystemExit(0 if passed else 1)
'@
```

### 15.5 Proxy停止と復旧

1つ目のPowerShellでProxyを起動する。

```powershell
$ProxyPath = Join-Path $env:LOCALAPPDATA `
  "Google\Cloud SDK\google-cloud-sdk\bin\cloud-sql-proxy.exe"

& $ProxyPath `
  --address=127.0.0.1 `
  --port=5433 `
  gcp-cloud-incident-platform:asia-northeast1:incident-db
```

2つ目のPowerShellで待受と正常接続を確認する。

```powershell
Test-NetConnection 127.0.0.1 -Port 5433

$env:EXPECT_DB = "up"
$DbProbeCode | uv run python -
if ($LASTEXITCODE -ne 0) {
  throw "Baseline DB probe failed."
}
```

Proxyを起動したPowerShellで`Ctrl+C`を押して停止し、2つ目のPowerShellで停止と接続失敗を確認する。

```powershell
$Listener = Get-NetTCPConnection `
  -LocalPort 5433 `
  -State Listen `
  -ErrorAction SilentlyContinue
if ($Listener) {
  throw "Proxy is still listening on port 5433."
}

$env:EXPECT_DB = "down"
$DbProbeCode | uv run python -
if ($LASTEXITCODE -ne 0) {
  throw "Unexpected Proxy-stop test result."
}
```

Proxyを同じコマンドで再起動し、復旧を確認する。

```powershell
Test-NetConnection 127.0.0.1 -Port 5433

$env:EXPECT_DB = "up"
$DbProbeCode | uv run python -
if ($LASTEXITCODE -ne 0) {
  throw "DB did not recover after Proxy restart."
}
```

実接続で、Proxy停止中は`OperationalError`、再起動後は`SELECT 1`成功を確認した。

### 15.6 不正パスワードと不正ポート

本番Cloud SQLユーザーのパスワードは変更しない。テストプロセス内の接続URLだけを書き換える。

不正パスワード：

```powershell
$env:SOURCE_DATABASE_URL = $ValidDatabaseUrl
$BuildInvalidPasswordUrlCode = @'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["SOURCE_DATABASE_URL"])
print(
    url.set(password="db-failure-test-invalid")
       .render_as_string(hide_password=False)
)
'@

$env:DATABASE_URL = ($BuildInvalidPasswordUrlCode | uv run python -).Trim()
$env:EXPECT_DB = "down"
$DbProbeCode | uv run python -
if ($LASTEXITCODE -ne 0) {
  throw "Unexpected invalid-password test result."
}
```

不正ポート：

```powershell
$BuildInvalidPortUrlCode = @'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["SOURCE_DATABASE_URL"])
print(url.set(port=5434).render_as_string(hide_password=False))
'@

$env:DATABASE_URL = ($BuildInvalidPortUrlCode | uv run python -).Trim()
$env:EXPECT_DB = "down"
$DbProbeCode | uv run python -
if ($LASTEXITCODE -ne 0) {
  throw "Unexpected invalid-port test result."
}

$env:DATABASE_URL = $ValidDatabaseUrl
```

実接続で、不正パスワードと不正ポートはいずれも`OperationalError`となり、期待した接続失敗を検出できた。

### 15.7 `pool_pre_ping`と接続Poolの確認

次のプローブは、同じEngineと接続Poolを保持したまま30秒待機する。最初の`SELECT 1`が終わった後、待機中に別PowerShellでProxyを停止して再起動する。

```powershell
$env:DATABASE_URL = $ValidDatabaseUrl
$PoolProbeCode = @'
import os
import time
from sqlalchemy import create_engine, text

engine = create_engine(
    os.environ["DATABASE_URL"],
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)

with engine.connect() as connection:
    connection.execute(text("SELECT 1"))
print("pool_baseline: success=True", flush=True)

print("Restart Proxy within 30 seconds.", flush=True)
time.sleep(30)

try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    print("pool_after_proxy_restart: success=True")
except Exception as exc:
    print(
        "pool_after_proxy_restart: "
        f"success=False, error={type(exc).__name__}"
    )
    raise
finally:
    engine.dispose()
'@

$PoolProbeCode | uv run python -
```

実接続では、Proxy再起動前後の両方で成功した。Pool内に残った古い接続は再利用されず、`pool_pre_ping`による生存確認後に新しい接続が確立された。

ただし、これは「次にPoolから接続を取り出すとき」の復旧確認である。実行中のトランザクションを中断してProxyを停止した場合、そのトランザクションは失敗する。書き込み処理の再試行を追加する場合は、二重登録を防ぐ冪等性と、トランザクション全体をやり直す境界を別途設計する。

### 15.8 Cloud SQL停止テスト

このテストは現在の`incident-db`を実際に停止する。Cloud SQLは1台だけで`ZONAL`構成のため、停止中はAPIとWorkerのDB処理がすべて利用できない。メンテナンス時間、関係者への通知、実行権限を確保してから行う。

2026-08-19時点では、現在稼働中の環境へ影響するため停止操作そのものは未実施である。停止・起動コマンドの構文と対象、現在の`ALWAYS`状態は確認済みである。

停止前に、復旧コマンドを別PowerShellへ準備する。

```powershell
$Gcloud = (Get-Command gcloud.cmd -ErrorAction Stop).Source
$ProjectId = "gcp-cloud-incident-platform"
$Instance = "incident-db"

# 緊急復旧用。停止テスト後は必ず実行する。
& $Gcloud sql instances patch $Instance `
  --project=$ProjectId `
  --activation-policy=ALWAYS `
  --quiet
```

停止直前の対象確認：

```powershell
& $Gcloud sql instances describe $Instance `
  --project=$ProjectId `
  --format="yaml(name,state,region,connectionName,settings.activationPolicy,settings.availabilityType)"

& $Gcloud sql instances list `
  --project=$ProjectId `
  --format="table(name,state,region,databaseVersion,settings.activationPolicy)"
```

期待値は、`name: incident-db`、`state: RUNNABLE`、`activationPolicy: ALWAYS`、`availabilityType: ZONAL`である。

APIの基準値を確認する。`/health`と`/tickets`の両方がHTTP 200であることを確認する。

```powershell
$ApiUrl = $ServiceJson.status.url

function Get-HttpStatusCode([string]$Uri) {
  try {
    $Response = Invoke-WebRequest `
      -UseBasicParsing `
      -Uri $Uri `
      -Method Get `
      -TimeoutSec 30
    return [int]$Response.StatusCode
  }
  catch {
    if ($_.Exception.Response) {
      return [int]$_.Exception.Response.StatusCode
    }
    return 0
  }
}

[PSCustomObject]@{
  Health  = Get-HttpStatusCode "$ApiUrl/health"
  Tickets = Get-HttpStatusCode "$ApiUrl/tickets"
}
```

Cloud SQL停止：

```powershell
$Confirmation = Read-Host "停止対象 incident-db を入力してください"
if ($Confirmation -cne "incident-db") {
  throw "Cloud SQL stop cancelled."
}

$TestStartedAt = Get-Date
& $Gcloud sql instances patch $Instance `
  --project=$ProjectId `
  --activation-policy=NEVER
if ($LASTEXITCODE -ne 0) {
  throw "Cloud SQL stop request failed."
}
```

停止状態とAPIの挙動を確認する。

```powershell
& $Gcloud sql instances describe $Instance `
  --project=$ProjectId `
  --format="yaml(name,state,settings.activationPolicy)"

[PSCustomObject]@{
  Health  = Get-HttpStatusCode "$ApiUrl/health"
  Tickets = Get-HttpStatusCode "$ApiUrl/tickets"
}
```

`activationPolicy: NEVER`を確認する。`/health`はDB非依存のためHTTP 200のままでも正常である。`/tickets`はDBを読むため、HTTP 200以外またはタイムアウトになることを確認する。

Cloud SQLを起動する。

```powershell
& $Gcloud sql instances patch $Instance `
  --project=$ProjectId `
  --activation-policy=ALWAYS `
  --quiet
if ($LASTEXITCODE -ne 0) {
  throw "Cloud SQL start request failed."
}
```

DBを使用するAPIがHTTP 200へ戻るまで確認し、利用再開までの時間を記録する。

```powershell
$RecoveryTimer = [System.Diagnostics.Stopwatch]::StartNew()
$Recovered = $false

for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
  $Policy = (& $Gcloud sql instances describe $Instance `
    --project=$ProjectId `
    --format="value(settings.activationPolicy)").Trim()
  $TicketsStatus = Get-HttpStatusCode "$ApiUrl/tickets"

  if ($Policy -eq "ALWAYS" -and $TicketsStatus -eq 200) {
    $Recovered = $true
    break
  }
  Start-Sleep -Seconds 10
}

$RecoveryTimer.Stop()
if (-not $Recovered) {
  throw "DB API did not recover within 10 minutes."
}

[PSCustomObject]@{
  TestStartedAt = $TestStartedAt
  RecoveredAt   = Get-Date
  RecoveryTime  = $RecoveryTimer.Elapsed
  TicketsStatus = $TicketsStatus
}
```

最後に設定と直近Operationを確認する。

```powershell
& $Gcloud sql instances describe $Instance `
  --project=$ProjectId `
  --format="yaml(name,state,settings.activationPolicy)"

& $Gcloud sql operations list `
  --instance=$Instance `
  --project=$ProjectId `
  --sort-by="~startTime" `
  --limit=5 `
  --format="table(name,operationType,status,startTime,endTime,error)"
```

終了条件は、`activationPolicy: ALWAYS`、`GET /tickets: HTTP 200`、直近Operationに未解決エラーがないことである。

### 15.9 後片付け

ローカル変数と認証情報を削除する。

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:CLOUD_RUN_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:SOURCE_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:EXPECT_DB -ErrorAction SilentlyContinue

$CloudRunDatabaseUrl = $null
$ValidDatabaseUrl = $null
$BuildProxyUrlCode = $null
$BuildInvalidPasswordUrlCode = $null
$BuildInvalidPortUrlCode = $null
$DbProbeCode = $null
$PoolProbeCode = $null
```

### 15.10 検証済み結果

```text
正常接続: 成功
不正パスワード: 期待どおりOperationalError
不正ポート: 期待どおりOperationalError
Proxy停止中: 期待どおりOperationalError
Proxy再起動後: 再接続成功
同一Poolを保持したProxy再起動後: pool_pre_pingにより再接続成功
Cloud SQL停止: 本番影響があるため未実施
```

ローカル障害テストでは、接続経路の停止と復旧を期待どおり検出できた。残る確認は、メンテナンス時間内にCloud SQL自体を停止し、APIとWorkerを含む実環境のエラー挙動と復旧時間を測定することである。

