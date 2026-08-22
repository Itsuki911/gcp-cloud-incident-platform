・google cloud cliが利用可能かを確認する
gcloud version

・google cloud の各種サービスを最新バージョンにする
gcloud components update

・ログイン
gcloud auth login 'adachiitsukiyishu@gmail.com'

・ログイン中のアカウントを表示する
gcloud auth list

・複数のアカウントを使用している場合のアカウントスイッチング
gcloud config set account `ACCOUNT`

・プロジェクト一覧
gcloud projects list

・プロジェクト一覧で表示されなかったプロジェクトを明示的に書いて、アクティブかどうかを確かめる
gcloud projects describe <gcp-cloud-incident-platform>

・プロジェクト選択
gcloud config set project gcp-cloud-incident-platform

・現在の設定確認(プロジェクトに移動後)
gcloud config get-value project
期待される結果：gcp-cloud-incident-platform

・Cloud Run の操作時に使用されるデフォルトのリージョン（地域）を設定
gcloud config set run/region asia-northeast1

・DockerがGoogl CloudのArtifact Registry（コンテナリポジトリに対して、操作を行えるように認証情報を登録する
gcloud auth configure-docker asia-northeast1-docker.pkg.dev

・使用するAPIの登録
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
今回は
Cloud Run API　　　　　：コンテナ化されたアプリケーションをサーバーレス環境で実行・管理するための API
Cloud Build API　　　　：ソースコードからコンテナイメージなどを自動でビルド・テスト・デプロイするための API
Artifact Registry API　：ビルドしたコンテナイメージやパッケージを安全に保管・管理するためのレジストリ API

・ソースコードから直接デプロイ
gcloud run deploy incident-platform `
  --source . `
  --region asia-northeast1 `
  --allow-unauthenticated

・現在登録されている設定一覧
gcloud config list


・Cloud SQLインスタンスの用意
gcloud sql instances create incident-db `
   --database-version=POSTGRES_17 `
   --edition=ENTERPRISE `
   --tier=db-f1-micro `
   --region=asia-northeast1 `
   --storage-type=SSD `
   --storage-size=10 `
   --storage-auto-increase `
   --availability-type=ZONAL
＊INSTANCE_NAME:incident-db

・Cloud SQL インスタンスの｛プロジェクトID:リージョン:インスタンスID｝の確認
gcloud sql instances describe incident-db

・アプリ用データベースの作成
gcloud sql databases create incidents --instance=incident-db
name:incidents

・Cloud SQL インスタンスに新しいDBユーザーを作成する
gcloud sql users create incident --instance=incident-db --password="YOUR_STRONG_PASSWORD"
password : vuaWkVBuyiucqBL4jWvd

・Secret Manager APIの登録
gcloud services enable secretmanager.googleapis.com

・DB接続情報を保存するSecretの作成
gcloud secrets create incident-database-url --replication-policy=automatic
シークレット(保管庫)の名前 : incident-database-url

・シークレットへ接続情報の登録
$DbPassword = [System.Net.NetworkCredential]::new("", (Read-Host "DBパスワード" -AsSecureString)).Password
先ほど作成したDBパスワードを入力する

・接続URLを変数に設定
$DatabaseUrl = "postgresql+psycopg://incident:$([Uri]::EscapeDataString($DbPassword))@/incidents?host=/cloudsql/gcp-cloud-incident-platform:asia-northeast1:incident-db"

・Secret登録用の一時ファイルを作成
[System.IO.File]::WriteAllText("$env:TEMP\incident-database-url.txt", $DatabaseUrl)

・接続情報をSecretへ登録
gcloud secrets versions add incident-database-url --data-file="$env:TEMP\incident-database-url.txt"

・パスワードを含む一次ファイルの削除
Remove-Item "$env:TEMP\incident-database-url.txt"

・Cloud Run専用のサービスアカウントを作成
gcloud iam service-accounts create incident-platform-run --display-name="Incident Platform Cloud Run"
出力：
サービスアカウントメール：プログラム・システムの識別・認識を行い、権限（IAM ロール）を付与するための宛先として機能する。

・このサービスアカウントへCloud SQL接続権限を付与
gcloud projects add-iam-policy-binding gcp-cloud-incident-platform --member="serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" --role="roles/cloudsql.client" --condition=None

・このサービスアカウントへSecretの読み取り権限を付与
gcloud secrets add-iam-policy-binding incident-database-url --member="serviceAccount:incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"

・Secret登録後、PowerShell上のパスワード情報を削除する
Remove-Variable DbPassword, DatabaseUrl

・デプロイ　ーCloud SQL接続とSecretを設定
gcloud run deploy incident-platform `
  --source . `
  --region asia-northeast1 `
  --service-account incident-platform-run@gcp-cloud-incident-platform.iam.gserviceaccount.com `
  --add-cloudsql-instances gcp-cloud-incident-platform:asia-northeast1:incident-db `
  --set-secrets DATABASE_URL=incident-database-url:latest `
  --set-env-vars APP_ENV=production `
  --allow-unauthenticated

・APIのヘルスチェック
Invoke-RestMethod https://incident-platform-888088780947.asia-northeast1.run.app/health

・Cloud SQLへの書き込みを確認
Invoke-RestMethod -Method Post -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets" -ContentType "application/json" -Body '{"title":"Cloud Run動作確認","raw_question":"Cloud SQL接続テスト"}'


・Cloud SQL インスタンスの運用
一時停止
gcloud sql instances patch incident-db --activation-policy=NEVER

再起動
gcloud sql instances patch incident-db --activation-policy=ALWAYS

稼働状況確認
gcloud sql instances describe incident-db --format="get(state)"


IAM
・サービスアカウント一覧
gcloud iam service-accounts list

・Cloud Run専用のサービスアカウントを作成
gcloud iam service-accounts create incident-platform-run --display-name="Incident Platform Cloud Run"


・Vertex AI APIを有効化
gcloud services enable aiplatform.googleapis.com


・Worker用サービスアカウント
gcloud iam service-accounts create incident-worker-run --display-name="Incident AI Worker"

↓

・Vertex AIの利用権限を付与
gcloud projects add-iam-policy-binding gcp-cloud-incident-platform --member="serviceAccount:incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" --role="roles/aiplatform.user" --condition=None


・Cloud SQL接続権限を付与
gcloud projects add-iam-policy-binding gcp-cloud-incident-platform --member="serviceAccount:incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" --role="roles/cloudsql.client" --condition=None

・DB Secretの参照権限を付与
gcloud secrets add-iam-policy-binding incident-database-url --member="serviceAccount:incident-worker-run@gcp-cloud-incident-platform.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"

・非公開Workerをデプロイ