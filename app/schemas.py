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


class ConvertResponse(BaseModel):
    """HWP/HWPX → Markdown 변환 결과 (JSON)"""

    filename: str = Field(..., description="업로드한 원본 파일명")
    markdown: str = Field(..., description="변환된 Markdown 텍스트")
    download_url: str = Field(
        default="",
        description="변환된 Markdown 파일 다운로드 URL",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filename": "보고서.hwp",
                    "markdown": "# 보고서 제목\n\n## 1. 개요\n\n본문 내용입니다.",
                    "download_url": "/api/v1/download/보고서_a1b2c3d4.md",
                }
            ]
        }
    }


class Base64ConvertRequest(BaseModel):
    """Base64 인코딩된 HWP/HWPX 파일 변환 요청

    Flowise, n8n 등 외부 시스템에서 JSON으로 파일을 전송할 때 사용합니다.
    """

    filename: str = Field(
        ...,
        description="원본 파일명 (.hwp 또는 .hwpx 확장자 필수)",
    )
    content_base64: str = Field(
        ...,
        description="파일 내용을 Base64로 인코딩한 문자열",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filename": "보고서.hwp",
                    "content_base64": "0M8R4KGxGuEAAAAA...",
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
