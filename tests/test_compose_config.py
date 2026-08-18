from pathlib import Path


# APIのADC設定を確認する
def test_api_mounts_local_adc() -> None:
    compose = Path(__file__).parents[1].joinpath("compose.yaml").read_text(encoding="utf-8")
    api_config = compose.split("  api:\n", 1)[1].split("\n# コンテナ間", 1)[0]

    assert "GOOGLE_APPLICATION_CREDENTIALS: /var/run/google/adc.json" in api_config
    assert "ATTACHMENT_BUCKET: gcp-cloud-incident-platform-ticket-attachments" in api_config
    assert "source: ${APPDATA}/gcloud/application_default_credentials.json" in api_config
    assert "target: /var/run/google/adc.json" in api_config
    assert "read_only: true" in api_config
    assert "create_host_path: false" in api_config
