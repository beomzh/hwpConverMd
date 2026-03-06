import base64
import logging
import os
from pathlib import Path
from typing import List, Tuple
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

logger = logging.getLogger(__name__)

from app.core.exceptions import ConversionError
from app.schemas import ConvertResponse, ConvertResult, ErrorResponse
from app.services.converter import ConverterService
from app.utils.file_manager import OUTPUT_DIR, cleanup_files, save_output_file, save_temp_file

router = APIRouter()

# 최대 업로드 파일 크기 (환경변수로 설정 가능, 기본 100MB)
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024


# =============================================================================
#  공통 헬퍼
# =============================================================================

def _decode_base64(b64_data: str) -> bytes:
    """Base64 문자열을 디코딩한다.

    data URI prefix, 줄바꿈, 패딩 누락 등을 자동 보정한다.
    """
    b64_data = b64_data.strip()
    # data:application/octet-stream;base64,XXXX 형식 처리
    if b64_data.startswith("data:"):
        idx = b64_data.find(",")
        if idx != -1:
            b64_data = b64_data[idx + 1 :]
    # 줄바꿈·공백 제거
    b64_data = b64_data.replace("\n", "").replace("\r", "").replace(" ", "")
    # 패딩 보정
    pad = len(b64_data) % 4
    if pad:
        b64_data += "=" * (4 - pad)
    return base64.b64decode(b64_data)


async def _extract_files(request: Request) -> List[Tuple[str, bytes]]:
    """Content-Type에 따라 multipart 또는 JSON에서 파일 목록을 추출한다.

    반환: [(filename, content_bytes), ...]
    """
    content_type = request.headers.get("content-type", "")

    # ── multipart/form-data (파일 업로드) ──
    if "multipart" in content_type:
        form = await request.form()
        files: List[Tuple[str, bytes]] = []
        for key in form:
            for item in form.getlist(key):
                if hasattr(item, "read"):  # UploadFile
                    content = await item.read()
                    files.append((item.filename or "unknown", content))
        if not files:
            raise HTTPException(status_code=400, detail="파일이 없습니다.")
        return files

    # ── application/json (base64) ──
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="multipart/form-data(파일) 또는 application/json(base64)으로 전송하세요.",
        )

    file_items: list = []

    if isinstance(body.get("files"), list) and body["files"]:
        file_items = body["files"]
    elif body.get("filename") and body.get("content_base64"):
        file_items = [
            {"filename": body["filename"], "content_base64": body["content_base64"]}
        ]
    else:
        raise HTTPException(
            status_code=400,
            detail="filename+content_base64 또는 files 배열이 필요합니다.",
        )

    files = []
    for item in file_items:
        fname = item.get("filename", "unknown")
        b64 = item.get("content_base64", "")
        try:
            raw = _decode_base64(b64)
        except Exception as exc:
            logger.error(f"[base64] {fname} decode failed: {exc}")
            # 디코딩 실패는 (filename, None) 대신 빈 bytes → _convert_one 에서 처리
            files.append((fname, b""))
            continue
        files.append((fname, raw))

    return files


async def _convert_one(filename: str, content: bytes) -> ConvertResult:
    """단일 파일을 변환하고 ConvertResult를 반환한다.

    변환 실패 시에도 예외를 던지지 않고 error 필드에 메시지를 담아 반환한다.
    """
    ext = Path(filename).suffix.lower()
    if ext not in (".hwp", ".hwpx"):
        return ConvertResult(
            filename=filename,
            error="HWP 또는 HWPX 파일만 지원합니다.",
        )

    if len(content) == 0:
        return ConvertResult(
            filename=filename,
            error=f"빈 파일입니다: {filename} (0 bytes)",
        )
    if len(content) > MAX_UPLOAD_SIZE:
        max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
        file_mb = round(len(content) / (1024 * 1024), 1)
        return ConvertResult(
            filename=filename,
            error=f"파일 크기 초과: {file_mb}MB > {max_mb}MB 제한",
        )

    temp_path = save_temp_file(content, ext)
    try:
        markdown_result = await ConverterService.convert(temp_path)
        file_id = save_output_file(markdown_result, filename)
        return ConvertResult(
            filename=filename,
            markdown=markdown_result,
            download_url=f"/api/v1/download/{file_id}",
        )
    except ConversionError as e:
        return ConvertResult(filename=filename, error=str(e))
    except Exception as e:
        logger.error(f"[convert] {filename}: {e}")
        return ConvertResult(filename=filename, error=f"변환 실패: {e}")
    finally:
        cleanup_files(temp_path)


# =============================================================================
#  POST /convert — JSON 응답 (다중 파일 지원)
# =============================================================================
_CONVERT_DESC = (
    "HWP/HWPX 파일을 Markdown으로 변환하여 JSON으로 반환합니다.\n\n"
    "**두 가지 전송 방식 모두 지원:**\n"
    "- `multipart/form-data` — 파일 직접 업로드 (key: `file`)\n"
    "- `application/json` — Base64 인코딩된 파일 전송\n"
    "  - 단일: `{\"filename\": \"보고서.hwp\", \"content_base64\": \"...\"}`\n"
    "  - 다중: `{\"files\": [{\"filename\": \"...\", \"content_base64\": \"...\"}]}`\n\n"
    "- **다중 파일**: 여러 파일을 동시에 업로드 가능\n"
    "- **응답**: `{results: [{filename, markdown, download_url, error}]}` JSON"
)


@router.post(
    "/convert",
    response_model=ConvertResponse,
    summary="HWP/HWPX → Markdown 변환 (파일 또는 Base64 JSON)",
    description=_CONVERT_DESC,
    responses={
        200: {"description": "변환 성공"},
        400: {"description": "잘못된 요청", "model": ErrorResponse},
        500: {"description": "변환 중 서버 에러 발생", "model": ErrorResponse},
    },
    operation_id="convertFile",
)
async def convert_file(request: Request):
    """HWP/HWPX 파일을 Markdown JSON으로 반환한다. (파일 업로드 & JSON 모두 지원)"""
    file_list = await _extract_files(request)
    results = [await _convert_one(name, data) for name, data in file_list]
    return ConvertResponse(results=results)


# =============================================================================
#  POST /convert/raw — Raw Markdown 텍스트 반환 (첫 번째 파일만)
# =============================================================================
_RAW_DESC = (
    "HWP/HWPX 파일을 순수 Markdown 텍스트로 반환합니다.\n\n"
    "**두 가지 전송 방식 모두 지원:**\n"
    "- `multipart/form-data` — 파일 직접 업로드 (key: `file`)\n"
    "- `application/json` — `{\"filename\": \"...\", \"content_base64\": \"...\"}`\n\n"
    "- **단일 파일 전용**: 여러 파일 전송 시 첫 번째 파일만 변환\n"
    "- **응답**: `text/markdown` Content-Type의 순수 텍스트"
)


@router.post(
    "/convert/raw",
    response_class=PlainTextResponse,
    summary="HWP/HWPX → Markdown 변환 (Raw Text, 파일 또는 Base64 JSON)",
    description=_RAW_DESC,
    responses={
        200: {
            "description": "변환 성공 — 순수 Markdown 텍스트 반환",
            "content": {
                "text/markdown": {
                    "schema": {"type": "string"},
                    "example": "# 보고서 제목\n\n## 1. 개요\n\n본문 내용입니다.",
                }
            },
        },
        400: {"description": "잘못된 요청", "model": ErrorResponse},
        500: {"description": "변환 중 서버 에러 발생", "model": ErrorResponse},
    },
    operation_id="convertFileToRaw",
)
async def convert_file_raw(request: Request):
    """HWP/HWPX 파일을 순수 Markdown 텍스트로 반환한다. (첫 번째 파일만)"""
    file_list = await _extract_files(request)
    filename, content = file_list[0]

    ext = Path(filename).suffix.lower()
    if ext not in (".hwp", ".hwpx"):
        raise HTTPException(
            status_code=400,
            detail="HWP 또는 HWPX 파일만 업로드 가능합니다.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail=f"빈 파일입니다: {filename}")
    if len(content) > MAX_UPLOAD_SIZE:
        max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
        file_mb = round(len(content) / (1024 * 1024), 1)
        raise HTTPException(
            status_code=413, detail=f"파일 크기 초과: {file_mb}MB > {max_mb}MB"
        )

    temp_path = save_temp_file(content, ext)
    try:
        markdown_result = await ConverterService.convert(temp_path)
        return PlainTextResponse(
            content=markdown_result,
            media_type="text/markdown; charset=utf-8",
        )
    except ConversionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cleanup_files(temp_path)


# =============================================================================
#  POST /convert/base64 — JSON 응답 (다중 파일 지원, /convert 별칭)
# =============================================================================
_BASE64_DESC = (
    "HWP/HWPX 파일을 Markdown으로 변환하여 JSON으로 반환합니다.\n\n"
    "**`/convert`와 동일하게 동작합니다. 두 가지 전송 방식 모두 지원:**\n"
    "- `multipart/form-data` — 파일 직접 업로드 (key: `file`)\n"
    "- `application/json` — Base64 인코딩된 파일 전송\n"
    "  - 단일: `{\"filename\": \"보고서.hwp\", \"content_base64\": \"...\"}`\n"
    "  - 다중: `{\"files\": [{\"filename\": \"...\", \"content_base64\": \"...\"}]}`"
)


@router.post(
    "/convert/base64",
    response_model=ConvertResponse,
    summary="HWP/HWPX → Markdown 변환 (파일 또는 Base64 JSON — /convert 별칭)",
    description=_BASE64_DESC,
    responses={
        200: {"description": "변환 성공"},
        400: {"description": "잘못된 요청", "model": ErrorResponse},
        500: {"description": "변환 중 서버 에러 발생", "model": ErrorResponse},
    },
    operation_id="convertFileBase64",
)
async def convert_file_base64(request: Request):
    """HWP/HWPX 파일을 Markdown JSON으로 반환한다. (/convert와 동일)"""
    file_list = await _extract_files(request)
    results = [await _convert_one(name, data) for name, data in file_list]
    return ConvertResponse(results=results)


# =============================================================================
#  GET /download/{file_id} — Markdown 파일 다운로드
# =============================================================================
@router.get(
    "/download/{file_id}",
    summary="변환된 Markdown 파일 다운로드",
    description=(
        "변환 결과로 생성된 Markdown 파일을 다운로드합니다.\n\n"
        "- **file_id**: 변환 응답의 `download_url`에 포함된 UUID (예: `a1b2c3d4`)"
    ),
    operation_id="downloadMarkdown",
)
async def download_markdown(file_id: str):
    """변환된 Markdown 파일을 UUID 기반으로 다운로드한다."""
    # path traversal 방지: 알파벳·숫자·하이픈만 허용
    safe_id = "".join(c for c in file_id if c.isalnum() or c == "-")
    md_path = OUTPUT_DIR / f"{safe_id}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    # 원본 파일명 복원 (다운로드 시 표시용)
    name_path = OUTPUT_DIR / f"{safe_id}.name"
    if name_path.exists():
        original_name = name_path.read_text(encoding="utf-8").strip()
        stem = Path(original_name).stem
        download_name = f"{stem}.md"
    else:
        download_name = f"{safe_id}.md"
    # RFC 5987: 한글 등 비ASCII 파일명은 filename*=UTF-8'' 인코딩 필수
    encoded_name = quote(download_name)
    return FileResponse(
        path=str(md_path),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{encoded_name}"; '
                f"filename*=UTF-8''{encoded_name}"
            )
        },
    )
