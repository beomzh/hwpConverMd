import os
import shutil
import uuid
from pathlib import Path

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def save_temp_file(file_content: bytes, extension: str) -> str:
    """업로드된 파일을 고유한 이름으로 임시 저장"""
    file_id = uuid.uuid4()
    file_path = TEMP_DIR / f"{file_id}{extension}"
    with open(file_path, "wb") as f:
        f.write(file_content)
    return str(file_path)


def save_output_file(markdown: str, original_filename: str) -> str:
    """변환된 마크다운을 output 디렉토리에 저장하고 파일 ID를 반환"""
    stem = Path(original_filename).stem
    file_id = str(uuid.uuid4())[:8]
    md_filename = f"{stem}_{file_id}.md"
    file_path = OUTPUT_DIR / md_filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return md_filename


def cleanup_files(*file_paths: str):
    """작업이 끝난 임시 파일들을 삭제"""
    for path in file_paths:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
