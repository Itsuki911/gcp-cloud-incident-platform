# GCP Cloud Incident Platform

問い合わせ・障害報告・サポートチケットを受け取るシステムの開発環境です。現在はAIとGoogle Cloudを使用せず、APIとデータベース処理をローカル環境で実行します。

設計内容は [architecture/initial-design.md](architecture/initial-design.md) を参照してください。

## ローカルセットアップ

前提条件：

- Python 3.11
- uv
- Git

PowerShellで次を実行します。

```powershell
docker compose up -d db
.\scripts\setup.ps1
uv run uvicorn incident_platform.main:app --reload --port 8080
```

起動後は以下を確認できます。

- APIドキュメント: <http://localhost:8080/docs>
- ヘルスチェック: <http://localhost:8080/health>

利用できるAPI：

| メソッド | エンドポイント | 内容 |
| --- | --- | --- |
| `POST` | `/tickets` | チケットを`queued`で保存 |
| `GET` | `/tickets` | チケット一覧を新しい順で取得 |
| `GET` | `/tickets/{id}` | IDを指定してチケットを取得 |
| `GET` | `/health` | APIの稼働確認 |

## `/docs` での動作確認

1. ブラウザで <http://localhost:8080/docs> を開く。
2. `POST /tickets` を開き、「Try it out」を押す。
3. Request bodyへ次のように入力し、「Execute」を押す。

```json
{
  "title": "ログインエラー",
  "raw_question": "ログインすると500エラーになります。"
}
```

4. Response bodyに表示された実際の `id` をコピーする。

```json
{
  "id": "ここに実際のUUIDが表示されます",
  "status": "queued"
}
```

5. `GET /tickets/{ticket_id}` を開き、「Try it out」を押す。
6. `ticket_id` にコピーした `id` を貼り付け、「Execute」を押す。
7. Response bodyに登録内容が表示されることを確認する。

`3fa85f64-5717-4562-b3fc-2c963f66afa6` など、画面に最初から表示されるサンプルUUIDでは登録データを取得できません。必ず `POST /tickets` のResponse bodyに返された `id` を使用してください。

登録済みチケットとIDの一覧は、`GET /tickets` の「Execute」から確認できます。

## Docker Compose

Docker Desktopを起動後、次を実行します。

```powershell
docker compose up --build
```

| サービス | URL・ポート |
| --- | --- |
| API | <http://localhost:8080> |
| PostgreSQL | `localhost:5432` |

停止時は `docker compose down` を実行します。

ローカルデータを削除する場合は、次を実行します。

```powershell
docker compose down --volumes
```

## 開発用コマンド

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`.env.example` を `.env` にコピーし、ローカル固有値を設定してください。`.env` と認証情報はGit管理対象外です。
