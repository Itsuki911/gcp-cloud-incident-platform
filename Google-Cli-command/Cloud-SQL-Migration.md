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

Phase 4全体では、今後、`downgrade`演習、バックアップ復元リハーサル、接続障害テスト、Publish失敗時のDB整合性検討、RPO/RTO・HA設計の整理を行う。

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


バックアップ復元リハーサル
- 取得済みバックアップから検証用Cloud SQLへ復元
- tickets=9件、attachments=1件を照合
- 復元所要時間を記録
- 検証用インスタンスを削除
- PITRを有効にするか判断

DB接続障害テスト
- Proxy停止
- 不正パスワード
- 不正ポート
- Cloud SQL停止
- 復旧後に再接続できるか確認
- pool_pre_pingや接続Poolの挙動を記録

Publish失敗時のDB整合性を見直す
現在はDBへ保存・commitした後にPub/SubへPublishしています。
- Publish失敗時、queuedのまま残ることを再現
- publish_failed状態、再送処理、Outboxパターンを比較
- 本格的なOutbox実装はPhase 6へ回してもよい
- Phase 4では問題と採用方針を明文化

運用設計・記録を作成
- ER図
- Migration履歴
- バックアップ・復元結果
- 接続障害時の挙動
- データ消失条件
- RPO/RTO
- 現在のZONAL構成と本番向けHA構成の比較
