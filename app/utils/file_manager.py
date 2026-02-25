import os
import shutil
import uuid
from pathlib import Path

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)


def save_temp_file(file_content: bytes, extension: str) -> str:
    """업로드된 파일을 고유한 이름으로 임시 저장"""
    file_id = uuid.uuid4()
    file_path = TEMP_DIR / f"{file_id}{extension}"
    with open(file_path, "wb") as f:
        f.write(file_content)
    return str(file_path)


def cleanup_files(*file_paths: str):
    """작업이 끝난 임시 파일들을 삭제"""
    for path in file_paths:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
