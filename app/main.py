from fastapi import FastAPI

from app.api.endpoints import router
from app.schemas import HealthResponse

app = FastAPI(
    title="HWP to Markdown API",
    description=(
        "HWP/HWPX 파일을 Markdown으로 변환하는 REST API입니다.\n\n"
        "## 기능\n"
        "- **HWP → Markdown**: 한글(HWP) 파일을 Markdown으로 변환\n"
        "- **HWPX → Markdown**: 한글(HWPX) 파일을 Markdown으로 변환\n"
        "- **JSON 응답**: 파일명과 Markdown 텍스트를 JSON으로 반환\n"
        "- **Raw 텍스트 응답**: 순수 Markdown 텍스트를 `text/markdown`으로 반환\n\n"
        "## 지원 형식\n"
        "| 확장자 | 형식 | 설명 |\n"
        "| --- | --- | --- |\n"
        "| `.hwp` | HWP | 한글 워드프로세서 바이너리 형식 |\n"
        "| `.hwpx` | HWPX | 한글 워드프로세서 XML 형식 (OWPML) |\n\n"
        "## 사용 방법\n"
        "1. Postman 또는 API Dog에서 `openapi.json`을 import하여 테스트\n"
        "2. 파일을 `multipart/form-data`로 업로드\n"
        "3. 변환 결과를 JSON 또는 Raw 텍스트로 수신"
    ),
    version="1.0.0",
    servers=[
        {
            "url": "http://localhost:8000",
            "description": "로컬 개발 서버",
        },
        {
            "url": "http://0.0.0.0:8000",
            "description": "Docker 컨테이너 서버",
        },
    ],
    openapi_tags=[
        {
            "name": "health",
            "description": "서비스 상태 확인",
        },
        {
            "name": "convert",
            "description": "HWP/HWPX 파일을 Markdown으로 변환하는 API",
        },
    ],
    contact={
        "name": "HWP Converter API",
    },
    license_info={
        "name": "MIT",
    },
)

app.include_router(router, prefix="/api/v1", tags=["convert"])


@app.get(
    "/",
    response_model=HealthResponse,
    summary="서비스 상태 확인 (Health Check)",
    description="서비스가 정상 동작 중인지 확인합니다. API의 기본 엔드포인트로, 서비스 상태를 간단히 확인할 수 있습니다.",
    operation_id="healthCheck",
    tags=["health"],
    responses={
        200: {
            "description": "서비스 정상 동작",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "service": "hwp-to-markdown",
                    }
                }
            },
        }
    },
)
def health_check():
    return {"status": "ok", "service": "hwp-to-markdown"}


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="k8s Probe 전용 Health Check",
    description="k8s liveness/readiness probe 전용 경량 엔드포인트. 변환 워커와 무관하게 즉시 응답합니다.",
    operation_id="k8sHealthCheck",
    tags=["health"],
)
def k8s_health():
    return {"status": "ok", "service": "hwp-to-markdown"}
