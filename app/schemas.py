from typing import List

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """서비스 상태 확인 응답"""

    status: str = Field(..., description="서비스 상태")
    service: str = Field(..., description="서비스 이름")

    model_config = {
        "json_schema_extra": {
            "examples": [{"status": "ok", "service": "hwp-to-markdown"}]
        }
    }


class ConvertResult(BaseModel):
    """개별 파일 변환 결과"""

    filename: str = Field(..., description="업로드한 원본 파일명")
    markdown: str = Field(default="", description="변환된 Markdown 텍스트")
    download_url: str = Field(
        default="",
        description="변환된 Markdown 파일 다운로드 URL",
    )
    error: str = Field(
        default="",
        description="변환 실패 시 에러 메시지 (성공 시 빈 문자열)",
    )


class ConvertResponse(BaseModel):
    """HWP/HWPX → Markdown 변환 결과 (단일 또는 다중 파일)"""

    results: List[ConvertResult] = Field(
        ..., description="파일별 변환 결과 목록"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "results": [
                        {
                            "filename": "보고서.hwp",
                            "markdown": "# 보고서 제목\n\n본문 내용입니다.",
                            "download_url": "/api/v1/download/a1b2c3d4",
                            "error": "",
                        }
                    ]
                }
            ]
        }
    }


class ErrorResponse(BaseModel):
    """에러 응답"""

    detail: str = Field(..., description="에러 메시지")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"detail": "HWP 또는 HWPX 파일만 업로드 가능합니다."}
            ]
        }
    }
