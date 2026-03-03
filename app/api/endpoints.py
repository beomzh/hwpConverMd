import base64
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

logger = logging.getLogger(__name__)

from app.core.exceptions import ConversionError
from app.schemas import Base64ConvertRequest, ConvertResponse, ErrorResponse
from app.services.converter import ConverterService
from app.utils.file_manager import OUTPUT_DIR, cleanup_files, save_output_file, save_temp_file

router = APIRouter()


@router.post(
    "/convert",
    response_model=ConvertResponse,
    summary="HWP/HWPX → Markdown 변환 (JSON)",
    description=(
        "HWP 또는 HWPX 파일을 업로드하면 Markdown으로 변환하여 "
        "JSON 형태로 반환합니다.\n\n"
        "- **지원 형식**: `.hwp`, `.hwpx`\n"
        "- **응답**: `{filename, markdown}` JSON 객체\n"
        "- **테이블/서식**: 원본 문서의 표, 제목, 볼드/이탤릭 등을 Markdown으로 변환"
    ),
    responses={
        200: {
            "description": "변환 성공",
            "content": {
                "application/json": {
                    "example": {
                        "filename": "보고서.hwp",
                        "markdown": "# 보고서 제목\n\n## 1. 개요\n\n본문 내용입니다.\n\n## 2. 세부사항\n\n| 항목 | 설명 |\n| --- | --- |\n| A | 내용 A |",
                    }
                }
            },
        },
        400: {
            "description": "지원하지 않는 파일 형식",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "HWP 또는 HWPX 파일만 업로드 가능합니다."
                    }
                }
            },
        },
        500: {
            "description": "변환 중 서버 에러 발생",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"detail": "HWP 변환 실패: hwp5html 실행 오류"}
                }
            },
        },
    },
    operation_id="convertFileToJson",
)
async def convert_file(
    file: UploadFile = File(
        ...,
        description="변환할 HWP 또는 HWPX 파일 (.hwp, .hwpx)",
    ),
):
    """HWP/HWPX 파일을 업로드하면 Markdown JSON으로 반환한다."""
    ext = Path(file.filename).suffix.lower()

    if ext not in (".hwp", ".hwpx"):
        raise HTTPException(
            status_code=400,
            detail="HWP 또는 HWPX 파일만 업로드 가능합니다.",
        )

    content = await file.read()
    temp_path = save_temp_file(content, ext)

    try:
        markdown_result = await ConverterService.convert(temp_path)
        md_filename = save_output_file(markdown_result, file.filename)
        return {
            "filename": file.filename,
            "markdown": markdown_result,
            "download_url": f"/api/v1/download/{md_filename}",
        }
    except ConversionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cleanup_files(temp_path)


@router.post(
    "/convert/raw",
    response_class=PlainTextResponse,
    summary="HWP/HWPX → Markdown 변환 (Raw Text)",
    description=(
        "HWP 또는 HWPX 파일을 업로드하면 순수 Markdown 텍스트로 반환합니다.\n\n"
        "- **지원 형식**: `.hwp`, `.hwpx`\n"
        "- **응답**: `text/markdown` Content-Type의 순수 텍스트\n"
        "- **용도**: Markdown 파일로 바로 저장하거나, "
        "Markdown 렌더러에 직접 전달할 때 유용"
    ),
    responses={
        200: {
            "description": "변환 성공 — 순수 Markdown 텍스트 반환",
            "content": {
                "text/markdown": {
                    "schema": {"type": "string"},
                    "example": "# 보고서 제목\n\n## 1. 개요\n\n본문 내용입니다.\n\n## 2. 세부사항\n\n| 항목 | 설명 |\n| --- | --- |\n| A | 내용 A |",
                }
            },
        },
        400: {
            "description": "지원하지 않는 파일 형식",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                    "example": {
                        "detail": "HWP 또는 HWPX 파일만 업로드 가능합니다."
                    },
                }
            },
        },
        500: {
            "description": "변환 중 서버 에러 발생",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                    "example": {"detail": "HWPX 파싱 실패: section 파일 없음"},
                }
            },
        },
    },
    operation_id="convertFileToRaw",
)
async def convert_file_raw(
    file: UploadFile = File(
        ...,
        description="변환할 HWP 또는 HWPX 파일 (.hwp, .hwpx)",
    ),
):
    """HWP/HWPX 파일을 업로드하면 순수 Markdown 텍스트로 반환한다."""
    ext = Path(file.filename).suffix.lower()

    if ext not in (".hwp", ".hwpx"):
        raise HTTPException(
            status_code=400,
            detail="HWP 또는 HWPX 파일만 업로드 가능합니다.",
        )

    content = await file.read()
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


@router.post(
    "/convert/base64",
    response_model=ConvertResponse,
    summary="HWP/HWPX → Markdown 변환 (Base64 JSON)",
    description=(
        "Base64로 인코딩된 HWP/HWPX 파일을 JSON으로 전송하여 "
        "Markdown으로 변환합니다.\n\n"
        "- **용도**: Flowise Custom Tool, n8n, Zapier 등 "
        "multipart/form-data를 지원하지 않는 외부 시스템 연동\n"
        "- **지원 형식**: `.hwp`, `.hwpx`\n"
        "- **요청**: `{filename, content_base64}` JSON 객체\n"
        "- **응답**: `{filename, markdown}` JSON 객체"
    ),
    responses={
        200: {
            "description": "변환 성공",
            "content": {
                "application/json": {
                    "example": {
                        "filename": "보고서.hwp",
                        "markdown": "# 보고서 제목\n\n## 1. 개요\n\n본문 내용입니다.",
                    }
                }
            },
        },
        400: {
            "description": "잘못된 요청 (파일 형식 오류 또는 Base64 디코딩 실패)",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "examples": {
                        "format_error": {
                            "summary": "파일 형식 오류",
                            "value": {
                                "detail": "HWP 또는 HWPX 파일만 업로드 가능합니다."
                            },
                        },
                        "base64_error": {
                            "summary": "Base64 디코딩 실패",
                            "value": {
                                "detail": "Base64 디코딩에 실패했습니다."
                            },
                        },
                    }
                }
            },
        },
        500: {
            "description": "변환 중 서버 에러 발생",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"detail": "HWP 변환 실패: hwp5html 실행 오류"}
                }
            },
        },
    },
    operation_id="convertFileBase64",
)
async def convert_file_base64(request: Base64ConvertRequest):
    """Base64 인코딩된 HWP/HWPX 파일을 Markdown JSON으로 반환한다."""
    ext = Path(request.filename).suffix.lower()

    if ext not in (".hwp", ".hwpx"):
        raise HTTPException(
            status_code=400,
            detail="HWP 또는 HWPX 파일만 업로드 가능합니다.",
        )

    # 디버그 로깅: 수신된 base64 데이터 정보
    b64_data = request.content_base64
    logger.info(
        f"[base64] filename={request.filename}, "
        f"len={len(b64_data)}, "
        f"first_80='{b64_data[:80]}', "
        f"last_40='{b64_data[-40:] if len(b64_data) > 40 else b64_data}'"
    )

    try:
        content = base64.b64decode(b64_data)
    except Exception as exc:
        logger.error(f"[base64] decode failed: {exc}")
        raise HTTPException(
            status_code=400,
            detail="Base64 디코딩에 실패했습니다.",
        )

    temp_path = save_temp_file(content, ext)

    try:
        markdown_result = await ConverterService.convert(temp_path)
        md_filename = save_output_file(markdown_result, request.filename)
        return {
            "filename": request.filename,
            "markdown": markdown_result,
            "download_url": f"/api/v1/download/{md_filename}",
        }
    except ConversionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cleanup_files(temp_path)


@router.get(
    "/download/{filename:path}",
    summary="변환된 Markdown 파일 다운로드",
    description="변환 결과로 생성된 Markdown 파일을 다운로드합니다.",
    operation_id="downloadMarkdown",
)
async def download_markdown(filename: str):
    """변환된 Markdown 파일을 다운로드한다."""
    # path traversal 방지
    safe_name = Path(filename).name
    file_path = OUTPUT_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
