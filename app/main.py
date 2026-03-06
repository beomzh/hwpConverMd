import asyncio
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.endpoints import router
from app.schemas import HealthResponse
from app.utils.file_manager import cleanup_old_outputs

logger = logging.getLogger(__name__)


# ── 서버 시작/종료 시 실행 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 기동 시 오래된 output 정리 + 주기적 정리 태스크 시작"""
    cleanup_old_outputs()

    async def _periodic_cleanup():
        while True:
            await asyncio.sleep(3600 * 12)  # 12시간마다
            cleanup_old_outputs()

    task = asyncio.create_task(_periodic_cleanup())
    yield
    task.cancel()


app = FastAPI(
    title="HWP to Markdown API",
    lifespan=lifespan,
    description=(
        "*License: MIT*\n\n"
        "HWP/HWPX 파일을 Markdown으로 변환하는 REST API입니다.\n\n"
        "---\n\n"
        "## 기능\n"
        "- **HWP → Markdown**: 한글(HWP) 파일을 Markdown으로 변환\n"
        "- **HWPX → Markdown**: 한글(HWPX) 파일을 Markdown으로 변환\n"
        "- **다중 파일 동시 변환**: 여러 파일을 한 번에 업로드 가능\n"
        "- **두 가지 전송 방식**: `multipart/form-data`(파일) 또는 `application/json`(Base64)\n"
        "- **JSON / Raw 텍스트 응답**: 용도에 맞게 선택 가능\n\n"
        "## 지원 형식\n"
        "| 확장자 | 형식 | 설명 |\n"
        "| --- | --- | --- |\n"
        "| `.hwp` | HWP | 한글 워드프로세서 바이너리 형식 |\n"
        "| `.hwpx` | HWPX | 한글 워드프로세서 XML 형식 (OWPML) |\n\n"
        "## 전송 방식\n"
        "모든 변환 엔드포인트는 두 가지 방식을 동시에 지원합니다:\n\n"
        "**1. 파일 업로드** (`multipart/form-data`)\n"
        "```\ncurl -X POST /api/v1/convert -F file=@보고서.hwp\n```\n\n"
        "**2. Base64 JSON** (`application/json`)\n"
        '```json\n{"filename": "보고서.hwp", "content_base64": "0M8R4..."}\n```'
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
)

app.include_router(router, prefix="/api/v1", tags=["convert"])


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 검증 실패 시 사람이 읽기 쉬운 400 에러를 반환한다.

    - 422 대신 400 Bad Request 로 통일
    - 바이너리 데이터가 content_base64 필드로 전달되면 기본 핸들러가
      bytes → UTF-8 디코딩에 실패하므로, 입력값을 포함하지 않는
      간결한 에러 메시지만 반환한다.
    """
    messages = []
    for err in exc.errors():
        loc = " → ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "알 수 없는 오류")
        messages.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(
        status_code=400,
        content={"detail": "; ".join(messages)},
    )


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
