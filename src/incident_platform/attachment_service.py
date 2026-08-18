from pathlib import PurePosixPath
from uuid import UUID

ALLOWED_FILE_TYPES = {
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "application/vnd.ms-excel"},
    ".md": {"text/markdown", "text/plain"},
    ".json": {"application/json", "text/json", "text/plain"},
    ".xml": {"application/xml", "text/xml"},
    ".yaml": {"application/yaml", "application/x-yaml", "text/yaml", "text/plain"},
    ".yml": {"application/yaml", "application/x-yaml", "text/yaml", "text/plain"},
    ".log": {"text/plain", "application/octet-stream"},
    ".doc": {"application/msword"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".ppt": {"application/vnd.ms-powerpoint"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".gif": {"image/gif"},
    ".webp": {"image/webp"},
    ".bmp": {"image/bmp"},
    ".tif": {"image/tiff"},
    ".tiff": {"image/tiff"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
    ".7z": {"application/x-7z-compressed"},
    ".tar": {"application/x-tar"},
    ".gz": {"application/gzip", "application/x-gzip"},
}


# ファイル情報を検証する
def validate_file(filename: str, content_type: str) -> tuple[str, str]:
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    media_type = content_type.split(";", 1)[0].strip().lower()
    extension = PurePosixPath(safe_name).suffix.lower()
    if not safe_name or safe_name in {".", ".."} or any(ord(char) < 32 for char in safe_name):
        raise ValueError("Invalid filename")
    if media_type not in ALLOWED_FILE_TYPES.get(extension, set()):
        raise ValueError("Unsupported file type")
    return safe_name, media_type


# Object名を生成する
def build_object_name(ticket_id: UUID, attachment_id: UUID, filename: str) -> str:
    return f"tickets/{ticket_id}/{attachment_id}-{filename}"
