from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app.core.exceptions import ConversionError
from app.services.converter import ConverterService
from app.utils.file_manager import cleanup_files, save_temp_file

router = APIRouter()


@router.post("/convert")
async def convert_file(file: UploadFile = File(...)):
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
        markdown_result = ConverterService.convert(temp_path)
        return {"filename": file.filename, "markdown": markdown_result}
    except ConversionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cleanup_files(temp_path)


@router.post("/convert/raw", response_class=PlainTextResponse)
async def convert_file_raw(file: UploadFile = File(...)):
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
        markdown_result = ConverterService.convert(temp_path)
        return PlainTextResponse(
            content=markdown_result,
            media_type="text/markdown; charset=utf-8",
        )
    except ConversionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cleanup_files(temp_path)
