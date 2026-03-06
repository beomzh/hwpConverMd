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
    """변환된 마크다운을 output 디렉토리에 저장하고 file_id를 반환한다.

    파일은 ``{file_id}.md`` 로 저장하여 한글 경로 문제를 회피하고,
    원본 파일명은 ``{file_id}.name`` 에 별도 저장하여 다운로드 시 사용한다.
    """
    file_id = str(uuid.uuid4())[:8]
    # Markdown 저장 (UUID 기반 파일명)
    md_path = OUTPUT_DIR / f"{file_id}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    # 원본 파일명 저장 (다운로드 시 Content-Disposition에 사용)
    name_path = OUTPUT_DIR / f"{file_id}.name"
    with open(name_path, "w", encoding="utf-8") as f:
        f.write(original_filename)
    return file_id


def cleanup_files(*file_paths: str):
    """작업이 끝난 임시 파일들을 삭제"""
    for path in file_paths:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
