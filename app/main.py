from fastapi import FastAPI

from app.api.endpoints import router

app = FastAPI(
    title="HWP to Markdown API",
    description="HWP/HWPX 파일을 Markdown으로 변환하는 REST API",
    version="1.0.0",
)

app.include_router(router, prefix="/api/v1", tags=["convert"])


@app.get("/")
def health_check():
    return {"status": "ok", "service": "hwp-to-markdown"}
