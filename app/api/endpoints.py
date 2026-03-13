import base64
import logging
import os
from pathlib import Path
from typing import List, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
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
#  OpenAPI 공통 스키마 (Swagger / ReDoc 문서용)
# =============================================================================

# ── Request Body 스키마 ──

_MULTIPART_SINGLE_SCHEMA = {
    "schema": {
        "type": "object",
        "required": ["file"],
        "properties": {
            "file": {
                "type": "string",
                "format": "binary",
                "description": "HWP 또는 HWPX 파일",
            }
        },
    }
}

_MULTIPART_MULTI_SCHEMA = {
    "schema": {
        "type": "object",
        "required": ["file"],
        "properties": {
            "file": {
                "type": "array",
                "items": {"type": "string", "format": "binary"},
                "description": "HWP/HWPX 파일 (다중 업로드 가능)",
            }
        },
    }
}

_JSON_SINGLE_SCHEMA = {
    "schema": {
        "type": "object",
        "required": ["filename", "content_base64"],
        "properties": {
            "filename": {
                "type": "string",
                "example": "보고서.hwp",
                "description": "파일명 (.hwp 또는 .hwpx)",
            },
            "content_base64": {
                "type": "string",
                "example": "0M8R4KGxGuEAAAAA...",
                "description": "Base64 인코딩된 파일 내용",
            },
        },
    },
    "examples": {
        "단일 파일": {
            "summary": "단일 파일 전송",
            "value": {
                "filename": "보고서.hwp",
                "content_base64": "0M8R4KGxGuEAAAAA...",
            },
        }
    },
}

_JSON_MULTI_SCHEMA = {
    "schema": {
        "oneOf": [
            {
                "title": "단일 파일",
                "type": "object",
                "required": ["filename", "content_base64"],
                "properties": {
                    "filename": {
                        "type": "string",
                        "example": "보고서.hwp",
                        "description": "파일명 (.hwp 또는 .hwpx)",
                    },
                    "content_base64": {
                        "type": "string",
                        "example": "0M8R4KGxGuEAAAAA...",
                        "description": "Base64 인코딩된 파일 내용",
                    },
                },
            },
            {
                "title": "다중 파일",
                "type": "object",
                "required": ["files"],
                "properties": {
                    "files": {
                        "type": "array",
                        "description": "변환할 파일 목록",
                        "items": {
                            "type": "object",
                            "required": ["filename", "content_base64"],
                            "properties": {
                                "filename": {
                                    "type": "string",
                                    "description": "파일명",
                                },
                                "content_base64": {
                                    "type": "string",
                                    "description": "Base64 인코딩된 파일 내용",
                                },
                            },
                        },
                    }
                },
            },
        ]
    },
    "examples": {
        "단일 파일": {
            "summary": "단일 파일 전송",
            "value": {
                "filename": "보고서.hwp",
                "content_base64": "0M8R4KGxGuEAAAAA...",
            },
        },
        "다중 파일": {
            "summary": "다중 파일 전송",
            "value": {
                "files": [
                    {"filename": "보고서.hwp", "content_base64": "0M8R4KGxGuEAAAAA..."},
                    {"filename": "회의록.hwpx", "content_base64": "UEsDBBQAAAAI..."},
                ]
            },
        },
    },
}

# ── Response 스키마 ──

_CONVERT_RESPONSES = {
    200: {
        "description": "변환 성공 — 파일별 변환 결과를 JSON으로 반환합니다.",
        "content": {
            "application/json": {
                "examples": {
                    "성공": {
                        "summary": "단일 파일 변환 성공",
                        "value": {
                            "results": [
                                {
                                    "filename": "보고서.hwp",
                                    "markdown": "# 보고서 제목\n\n## 1. 개요\n\n본문 내용입니다.",
                                    "download_url": "/api/v1/download/a1b2c3d4",
                                    "error": "",
                                }
                            ]
                        },
                    },
                    "부분 실패": {
                        "summary": "다중 파일 중 일부 실패",
                        "value": {
                            "results": [
                                {
                                    "filename": "보고서.hwp",
                                    "markdown": "# 제목\n\n내용",
                                    "download_url": "/api/v1/download/a1b2c3d4",
                                    "error": "",
                                },
                                {
                                    "filename": "문서.pdf",
                                    "markdown": "",
                                    "download_url": "",
                                    "error": "HWP 또는 HWPX 파일만 지원합니다.",
                                },
                            ]
                        },
                    },
                }
            }
        },
    },
    400: {
        "description": "잘못된 요청 — 파일 누락, 지원하지 않는 형식 등",
        "content": {
            "application/json": {
                "examples": {
                    "파일 누락": {
                        "summary": "파일이 전송되지 않음",
                        "value": {"detail": "파일이 없습니다."},
                    },
                    "잘못된 Content-Type": {
                        "summary": "지원하지 않는 Content-Type",
                        "value": {
                            "detail": "multipart/form-data(파일) 또는 application/json(base64)으로 전송하세요."
                        },
                    },
                    "필수 필드 누락": {
                        "summary": "JSON 필수 필드 누락",
                        "value": {
                            "detail": "filename+content_base64 또는 files 배열이 필요합니다."
                        },
                    },
                }
            }
        },
    },
    500: {
        "description": "서버 내부 오류 — HWP 파싱 실패 등",
        "content": {
            "application/json": {
                "example": {
                    "detail": "HWP 파일 변환 중 오류가 발생했습니다."
                }
            }
        },
    },
}

_RAW_RESPONSES = {
    200: {
        "description": "변환 성공 — 순수 Markdown 텍스트를 반환합니다.",
        "content": {
            "text/markdown": {
                "schema": {"type": "string"},
                "example": "# 보고서 제목\n\n## 1. 개요\n\n본문 내용입니다.\n\n## 2. 세부 사항\n\n- 항목 1\n- 항목 2",
            }
        },
    },
    400: {
        "description": "잘못된 요청 — 파일 누락, 미지원 형식, 빈 파일 등",
        "content": {
            "application/json": {
                "examples": {
                    "미지원 형식": {
                        "summary": "HWP/HWPX 외 파일",
                        "value": {"detail": "HWP 또는 HWPX 파일만 업로드 가능합니다."},
                    },
                    "빈 파일": {
                        "summary": "파일 내용이 비어 있음",
                        "value": {"detail": "빈 파일입니다: 보고서.hwp"},
                    },
                    "Base64 디코딩 실패": {
                        "summary": "Base64 인코딩 오류",
                        "value": {"detail": "Base64 디코딩 실패: Invalid base64-encoded string"},
                    },
                }
            }
        },
    },
    413: {
        "description": "파일 크기 초과 — 업로드 제한 초과",
        "content": {
            "application/json": {
                "example": {"detail": "파일 크기 초과: 150.3MB > 100MB"}
            }
        },
    },
    500: {
        "description": "서버 내부 오류 — HWP 파싱 실패 등",
        "content": {
            "application/json": {
                "example": {"detail": "HWP 파일 변환 중 오류가 발생했습니다."}
            }
        },
    },
}

_DOWNLOAD_RESPONSES = {
    200: {
        "description": "Markdown 파일 다운로드 성공",
        "content": {
            "text/markdown": {
                "schema": {"type": "string", "format": "binary"},
                "example": "# 보고서 제목\n\n본문 내용입니다.",
            }
        },
    },
    404: {
        "description": "파일을 찾을 수 없음 — file_id가 잘못되었거나 TTL이 만료됨",
        "content": {
            "application/json": {
                "examples": {
                    "만료됨": {
                        "summary": "TTL 만료로 삭제된 파일",
                        "value": {"detail": "파일을 찾을 수 없습니다."},
                    },
                    "잘못된 ID": {
                        "summary": "존재하지 않는 file_id",
                        "value": {"detail": "파일을 찾을 수 없습니다."},
                    },
                }
            }
        },
    },
}


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

    반환: [(filename, content_bytes), ...], {filename: error_msg, ...}
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
        return files, {}

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

    files: List[Tuple[str, bytes]] = []
    decode_errors: dict = {}
    for item in file_items:
        fname = item.get("filename", "unknown")
        b64 = item.get("content_base64", "")
        try:
            raw = _decode_base64(b64)
        except Exception as exc:
            logger.error(f"[base64] {fname} decode failed: {exc}")
            decode_errors[fname] = str(exc)
            files.append((fname, b""))
            continue
        files.append((fname, raw))

    return files, decode_errors


async def _convert_one(
    filename: str, content: bytes, decode_error: str = ""
) -> ConvertResult:
    """단일 파일을 변환하고 ConvertResult를 반환한다.

    변환 실패 시에도 예외를 던지지 않고 error 필드에 메시지를 담아 반환한다.
    decode_error가 설정되어 있으면 Base64 디코딩 실패로 간주한다.
    """
    # Base64 디코딩 실패한 파일은 즉시 에러 반환
    if decode_error:
        return ConvertResult(
            filename=filename,
            error=f"Base64 디코딩 실패: {decode_error}",
        )

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
    "### 전송 방식\n"
    "| 방식 | Content-Type | 설명 |\n"
    "| --- | --- | --- |\n"
    "| 파일 업로드 | `multipart/form-data` | key: `file` 로 파일 직접 전송 |\n"
    "| Base64 JSON | `application/json` | 파일을 Base64로 인코딩하여 전송 |\n\n"
    "### 특징\n"
    "- **다중 파일** 동시 업로드 가능\n"
    "- 변환 실패 시에도 200으로 응답하며, 개별 결과의 `error` 필드에 에러 메시지를 담아 반환\n"
    "- 변환 성공 시 `download_url`로 Markdown 파일 다운로드 가능 (TTL: 24시간)"
)


@router.post(
    "/convert",
    response_model=ConvertResponse,
    summary="HWP/HWPX → Markdown 변환 (JSON 응답)",
    description=_CONVERT_DESC,
    responses=_CONVERT_RESPONSES,
    operation_id="convertFile",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": _MULTIPART_MULTI_SCHEMA,
                "application/json": _JSON_MULTI_SCHEMA,
            },
        }
    },
)
async def convert_file(request: Request):
    """HWP/HWPX 파일을 Markdown JSON으로 반환한다. (파일 업로드 & JSON 모두 지원)"""
    file_list, decode_errors = await _extract_files(request)
    results = [
        await _convert_one(name, data, decode_errors.get(name, ""))
        for name, data in file_list
    ]
    return ConvertResponse(results=results)


# =============================================================================
#  POST /convert/raw — Raw Markdown 텍스트 반환 (첫 번째 파일만)
# =============================================================================
_RAW_DESC = (
    "HWP/HWPX 파일을 순수 Markdown 텍스트(`text/markdown`)로 반환합니다.\n\n"
    "### 전송 방식\n"
    "| 방식 | Content-Type | 설명 |\n"
    "| --- | --- | --- |\n"
    "| 파일 업로드 | `multipart/form-data` | key: `file` 로 파일 직접 전송 |\n"
    "| Base64 JSON | `application/json` | 파일을 Base64로 인코딩하여 전송 |\n\n"
    "### 특징\n"
    "- **단일 파일 전용**: 여러 파일 전송 시 첫 번째 파일만 변환\n"
    "- 응답 Content-Type: `text/markdown; charset=utf-8`\n"
    "- 변환 실패 시 400 또는 500 에러 반환"
)


@router.post(
    "/convert/raw",
    response_class=PlainTextResponse,
    summary="HWP/HWPX → Markdown 변환 (Raw Text 응답)",
    description=_RAW_DESC,
    responses=_RAW_RESPONSES,
    operation_id="convertFileToRaw",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": _MULTIPART_SINGLE_SCHEMA,
                "application/json": _JSON_SINGLE_SCHEMA,
            },
        }
    },
)
async def convert_file_raw(request: Request):
    """HWP/HWPX 파일을 순수 Markdown 텍스트로 반환한다. (첫 번째 파일만)"""
    file_list, decode_errors = await _extract_files(request)
    filename, content = file_list[0]

    if filename in decode_errors:
        raise HTTPException(
            status_code=400,
            detail=f"Base64 디코딩 실패: {decode_errors[filename]}",
        )

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
    "`/convert`와 동일하게 동작하는 별칭(alias) 엔드포인트입니다.\n\n"
    "### 전송 방식\n"
    "| 방식 | Content-Type | 설명 |\n"
    "| --- | --- | --- |\n"
    "| 파일 업로드 | `multipart/form-data` | key: `file` 로 파일 직접 전송 |\n"
    "| Base64 JSON | `application/json` | 파일을 Base64로 인코딩하여 전송 |\n\n"
    "### 특징\n"
    "- **다중 파일** 동시 업로드 가능\n"
    "- `/convert`와 완전히 동일한 입력·출력 형식"
)


@router.post(
    "/convert/base64",
    response_model=ConvertResponse,
    summary="HWP/HWPX → Markdown 변환 (/convert 별칭)",
    description=_BASE64_DESC,
    responses=_CONVERT_RESPONSES,
    operation_id="convertFileBase64",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": _MULTIPART_MULTI_SCHEMA,
                "application/json": _JSON_MULTI_SCHEMA,
            },
        }
    },
)
async def convert_file_base64(request: Request):
    """HWP/HWPX 파일을 Markdown JSON으로 반환한다. (/convert와 동일)"""
    file_list, decode_errors = await _extract_files(request)
    results = [
        await _convert_one(name, data, decode_errors.get(name, ""))
        for name, data in file_list
    ]
    return ConvertResponse(results=results)


# =============================================================================
#  GET /download/{file_id} — Markdown 파일 다운로드
# =============================================================================
@router.get(
    "/download/{file_id}",
    summary="변환된 Markdown 파일 다운로드",
    description=(
        "변환 결과로 생성된 Markdown 파일을 다운로드합니다.\n\n"
        "### 파라미터\n"
        "- **file_id**: 변환 응답의 `download_url`에 포함된 8자리 UUID (예: `a1b2c3d4`)\n\n"
        "### 주의 사항\n"
        "- 파일은 변환 후 **24시간**(기본값) 동안 보관되며, 이후 자동 삭제됩니다.\n"
        "- `OUTPUT_TTL_SEC` 환경변수로 보관 시간을 변경할 수 있습니다."
    ),
    responses=_DOWNLOAD_RESPONSES,
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


# =============================================================================
#  POST /upload-md — 임의 Markdown 저장 및 다운로드 URL 발급
# =============================================================================
@router.post(
    "/upload-md",
    summary="Markdown 내용을 저장하고 다운로드 URL 반환",
    description=(
        "LLM 분석 보고서 등 임의의 Markdown 내용을 서버에 저장하고 "
        "다운로드 가능한 URL을 반환합니다.\n\n"
        "- **content**: Markdown 텍스트 (form field)\n"
        "- **filename**: 다운로드 시 표시할 파일명 (선택, 기본값: `report.md`)\n"
        "- 저장된 파일은 24시간 후 자동 삭제됩니다."
    ),
    operation_id="uploadMarkdown",
)
async def upload_markdown(
    content: str = Form(..., description="저장할 Markdown 텍스트"),
    filename: str = Form("report.md", description="다운로드 시 사용할 파일명"),
):
    """Markdown 내용을 OUTPUT_DIR에 저장하고 download_url을 반환한다."""
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="content가 비어 있습니다.")
    file_id = save_output_file(content, filename)
    return JSONResponse({
        "file_id": file_id,
        "filename": filename,
        "download_url": f"/api/v1/download/{file_id}",
    })
