# GCP Cloud Incident Platform

問い合わせ・障害報告・サポートチケットを受け取り、AIによるカテゴリ、重要度、要約の生成を非同期で行うクラウドネイティブシステムの開発環境です。

設計内容は [architecture/initial-design.md](architecture/initial-design.md) を参照してください。

## 確認済みバージョン

| 対象 | 使用バージョン | 許容範囲 |
| --- | --- | --- |
| Python | 3.11.15 | 3.11系 |
| uv | 0.12.3 | Dockerfileで固定 |
| Git | 2.53.0 | 端末導入済みバージョン |
| Docker Engine / CLI | 29.7.2 | 端末導入済みバージョン |
| Docker Compose | 5.3.1 | 端末導入済みバージョン |
| Google Cloud CLI | 580.0.0 | 端末導入済みバージョン |
| FastAPI | 0.141.1 | 0.115以上、1.0未満 |
| Pydantic | 2.13.4 | 2.7以上、3.0未満 |
| SQLAlchemy | 2.0.52 | 2.0.51以上、2.1未満 |
| psycopg | 3.3.4 | 3.2以上、4.0未満 |
| Google Cloud Pub/Sub client | 2.39.1 | 2.31.1以上、3.0未満 |
| Google Cloud Secret Manager client | 2.30.0 | 2.20以上、3.0未満 |
| HTTPX2（テスト用） | 2.10.0 | 2.9以上、3.0未満 |
| PostgreSQL | 17 | Dockerイメージで指定 |

実際に解決された全依存バージョンは `uv.lock` に固定されます。

Pythonライブラリの構成と許容範囲は、2026年8月14日にContext7から取得したFastAPI、SQLAlchemy、Google Cloud Python Clientのドキュメントを基にしています。Docker DesktopとGoogle Cloud CLIの導入方法は、それぞれのWindows向け公式手順に従っています。

## ローカルセットアップ

前提条件：

- Python 3.11
- uv
- Git

PowerShellで次を実行します。

```powershell
.\scripts\setup.ps1
uv run uvicorn incident_platform.main:app --reload --port 8080
```

起動後は以下を確認できます。

- APIドキュメント: <http://localhost:8080/docs>
- ヘルスチェック: <http://localhost:8080/health>

## Docker Compose

Docker Desktopを起動後、次を実行します。

```powershell
docker compose up --build
```

| サービス | URL・ポート |
| --- | --- |
| API | <http://localhost:8080> |
| Worker | <http://localhost:8081> |
| PostgreSQL | `localhost:5432` |

停止時は `docker compose down` を実行します。データも削除する場合のみ `docker compose down --volumes` を使用してください。

## Google Cloud CLI

Google Cloud CLIをインストールした後、新しいターミナルを開き、課金が有効なプロジェクトIDを指定して実行します。

```powershell
.\scripts\gcloud-bootstrap.ps1 -ProjectId "YOUR_PROJECT_ID"
```

このスクリプトは次を設定します。

- 操作対象プロジェクトとCloud Runリージョン
- ユーザー認証とApplication Default Credentials
- Cloud Run、Cloud SQL、Pub/Sub、Secret Manager、Artifact Registry、Cloud BuildのAPI
- `incident-tickets` トピック
- `incident-tickets-worker` サブスクリプション

Cloud SQLインスタンスとAI APIシークレットは、課金、サイズ、パスワード、AIプロバイダーの選択が必要なため自動作成しません。

## 開発用コマンド

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`.env.example` を `.env` にコピーし、ローカル固有値を設定してください。`.env` と認証情報はGit管理対象外です。
