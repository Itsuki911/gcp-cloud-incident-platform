Google-Cli-command\Pub-Sub-Reliability-and-Idempotency.md
phase5で行うタスク、用語一覧、　これまでと同じように、課題を解決するための、gcloud cli commandをまとめて。
各コマンド、一操作一コマンド、変数使用なし、各コマンドの役割、期待される結果を簡潔にまとめて。　
用語集を最初にもってきて、初学者でも、全体を理解しやすいようにして。　

各コマンド、が現在の状況で、コマンドを実行してもエラーが出ないかを確認コマンドでかくにんして。しかし、マークダウン内に確認結果の記載は必要ないです。
しかし、私の練習のための、メインのコマンド入力と結果確認は私がやるので、あなたが行うのは、エラー回避のための確認を事前にすることです。


f675e9a3-85bb-44d6-a07c-000bc9efdf1c

Invoke-RestMethod `
  -Method Get `
  -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets/f675e9a3-85bb-44d6-a07c-000bc9efdf1c"


  beae9f18-c313-427a-82a2-30e7f212c758

  Set-Content `
  -LiteralPath "C:\Users\ITSUKI\AppData\Local\Temp\phase6-duplicate-event.yaml" `
  -Encoding ascii `
  -Value @('--message: >-','  {"schema_version":"1","event_id":"60000000-0000-4000-8000-000000000003","event_type":"ticket.created","ticket_id":"beae9f18-c313-427a-82a2-30e7f212c758","created_at":"2026-08-22T03:20:00Z"}')


Invoke-RestMethod `
  -Method Get `
  -Uri "https://incident-platform-888088780947.asia-northeast1.run.app/tickets/beae9f18-c313-427a-82a2-30e7f212c758"
