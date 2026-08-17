# Cloud Run Revision操作

## 1. 用語まとめ

| 用語 | 意味 |
| --- | --- |
| Service | 固定URLを持ち、リクエストをRevisionへ振り分ける単位 |
| Revision | コンテナイメージと実行設定を保存した変更不能な版 |
| Instance | Revisionを基に実際に起動するコンテナの実体 |
| Traffic | 各Revisionへ割り当てるリクエストの割合 |
| Revision Tag | 通常トラフィックを送らず、特定Revisionへ接続する名前 |
| Rollout | 新Revisionへ段階的にTrafficを移す操作 |
| Rollback | Trafficを以前のRevisionへ戻す操作 |

サービスへのデプロイや実行設定の変更により、新しいRevisionが作成されます。作成済みRevisionは変更できません。

## 2. このプロジェクトでの用途

このプロジェクトには、次のCloud Run Serviceがあります。

| Service | 用途 |
| --- | --- |
| `incident-platform` | チケットAPIを公開する |
| `incident-worker` | Pub/SubのPush通知を処理する |

ServiceごとにRevisionの履歴とトラフィック設定を持ちます。Revisionは、次の用途で使用します。

- 新しいコードや設定をトラフィック0%で検証する
- 新旧Revisionへトラフィックを分割する
- 問題発生時に以前のRevisionへ戻す
- 各Revisionのイメージや環境設定を確認する

操作対象のプロジェクトとリージョンは、次のとおりです。

```text
Project: gcp-cloud-incident-platform
Region: asia-northeast1
```

以下のコマンドはWindows PowerShell向けです。`REVISION_NAME`、`OLD_REVISION_NAME`、`NEW_REVISION_NAME`は、一覧で確認した実際のRevision名へ置き換えます。

PowerShellの実行ポリシーで`gcloud.ps1`が拒否される場合は、`gcloud`を`gcloud.cmd`へ読み替えます。

## 3. 操作対象の設定

プロジェクトを設定します。

```powershell
gcloud config set project gcp-cloud-incident-platform
```

Cloud Runのデフォルトリージョンを設定します。

```powershell
gcloud config set run/region asia-northeast1
```

## 4. Serviceを確認する

プロジェクト内のCloud Run Serviceを表示します。

```powershell
gcloud run services list `
  --region=asia-northeast1
```

## 5. Revisionを一覧表示する

Incident APIのRevisionを表示します。

```powershell
gcloud run revisions list `
  --service=incident-platform `
  --region=asia-northeast1
```

WorkerのRevisionを表示します。

```powershell
gcloud run revisions list `
  --service=incident-worker `
  --region=asia-northeast1
```

Revision名、作成時刻、稼働状態、トラフィック割り当てを確認します。

## 6. Revisionの詳細を確認する

指定したRevisionの詳細を表示します。

```powershell
gcloud run revisions describe REVISION_NAME `
  --region=asia-northeast1
```

詳細をYAML形式で表示します。

```powershell
gcloud run revisions describe REVISION_NAME `
  --region=asia-northeast1 `
  --format=yaml
```

コンテナイメージ、環境変数、CPU、メモリなどを確認できます。

## 7. 現在のトラフィックを確認する

Incident APIのトラフィック設定を表示します。

```powershell
gcloud run services describe incident-platform `
  --region=asia-northeast1 `
  --format="yaml(status.traffic)"
```

Workerのトラフィック設定を表示します。

```powershell
gcloud run services describe incident-worker `
  --region=asia-northeast1 `
  --format="yaml(status.traffic)"
```

## 8. 新Revisionをトラフィック0%で作成する

Incident APIを新しいRevisionとしてデプロイし、通常のリクエストは送らないようにします。

```powershell
gcloud run deploy incident-platform `
  --source=. `
  --region=asia-northeast1 `
  --no-traffic `
  --tag=preview
```

既存Serviceで省略した設定は原則として引き継がれますが、実行前に現在のService設定を確認します。`preview`タグのURLを使うと、通常トラフィックを移さずに新Revisionを確認できます。

## 9. Revisionへトラフィックを切り替える

指定したRevisionへ100%切り替えます。

```powershell
gcloud run services update-traffic incident-platform `
  --region=asia-northeast1 `
  --to-revisions="NEW_REVISION_NAME=100"
```

Serviceは停止されません。切り替え中の処理中リクエストは破棄されません。

## 10. 段階的に切り替える

旧Revisionへ90%、新Revisionへ10%を割り当てます。

```powershell
gcloud run services update-traffic incident-platform `
  --region=asia-northeast1 `
  --to-revisions="OLD_REVISION_NAME=90,NEW_REVISION_NAME=10"
```

ログやエラー率を確認しながら、50%ずつへ変更します。

```powershell
gcloud run services update-traffic incident-platform `
  --region=asia-northeast1 `
  --to-revisions="OLD_REVISION_NAME=50,NEW_REVISION_NAME=50"
```

問題がなければ、新Revisionを100%にします。

```powershell
gcloud run services update-traffic incident-platform `
  --region=asia-northeast1 `
  --to-revisions="NEW_REVISION_NAME=100"
```

トラフィック変更の反映には時間がかかる場合があります。移行中は旧Revisionと新Revisionのどちらかへリクエストが届く可能性があります。

## 11. 最新Revisionへ切り替える

現在の最新Revisionへ100%のトラフィックを割り当てます。

```powershell
gcloud run services update-traffic incident-platform `
  --region=asia-northeast1 `
  --to-latest
```

この設定では、今後作成される最新Revisionにも自動でトラフィックが割り当てられます。検証してから切り替える運用では、Revision名を明示する方法を使用します。

## 12. 以前のRevisionへ戻す

問題が発生した場合は、旧Revisionへ100%戻します。

```powershell
gcloud run services update-traffic incident-platform `
  --region=asia-northeast1 `
  --to-revisions="OLD_REVISION_NAME=100"
```

再デプロイせずにロールバックできます。Workerを戻す場合は、Service名を`incident-worker`へ変更します。

## 13. Revisionを削除する

指定したRevisionを削除します。

```powershell
gcloud run revisions delete REVISION_NAME `
  --region=asia-northeast1
```

Revisionの削除は元に戻せません。次のRevisionは削除できません。

- トラフィックを受信できるRevision
- Serviceに残る唯一のRevision
- 最新Revision

通常は手動削除する必要はありません。Revisionを削除しても、Artifact Registryのコンテナイメージは自動削除されません。

## 14. 推奨する確認順序

```text
Revision一覧を確認
  ↓
新Revisionをトラフィック0%で作成
  ↓
タグURLで動作確認
  ↓
新Revisionへ10%を割り当て
  ↓
ログとエラー率を確認
  ↓
問題なし：新Revisionへ100%
問題あり：旧Revisionへ100%
```

## 参考資料

- [Cloud Runのリビジョンを管理する](https://docs.cloud.google.com/run/docs/managing/revisions?hl=ja)
- [ロールバック、段階的なロールアウト、トラフィックの移行](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration?hl=ja)
