"""REST API 통합 테스트"""

import base64

import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from app.main import app

TESTS_DIR = Path(__file__).parent


@pytest.mark.asyncio
async def test_health_check():
    """헬스체크 엔드포인트가 정상 응답하는지 확인"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_convert_hwp_api():
    """HWP 파일 업로드 → JSON 변환 응답 확인"""
    hwp_files = list(TESTS_DIR.glob("*.hwp"))
    if not hwp_files:
        pytest.skip("테스트용 HWP 파일이 없습니다")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(hwp_files[0], "rb") as f:
            response = await client.post(
                "/api/v1/convert",
                files={"file": (hwp_files[0].name, f, "application/octet-stream")},
            )

    assert response.status_code == 200
    data = response.json()
    assert "filename" in data
    assert "markdown" in data
    assert len(data["markdown"]) > 0
    print(f"\n--- API 변환 결과 (처음 300자) ---\n{data['markdown'][:300]}")


@pytest.mark.asyncio
async def test_convert_raw_api():
    """HWP 파일 업로드 → 순수 Markdown 텍스트 응답 확인"""
    hwp_files = list(TESTS_DIR.glob("*.hwp"))
    if not hwp_files:
        pytest.skip("테스트용 HWP 파일이 없습니다")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(hwp_files[0], "rb") as f:
            response = await client.post(
                "/api/v1/convert/raw",
                files={"file": (hwp_files[0].name, f, "application/octet-stream")},
            )

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert len(response.text) > 0


@pytest.mark.asyncio
async def test_upload_invalid_format():
    """지원하지 않는 형식 파일 업로드 시 400 에러 확인"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/convert",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 400
    assert "HWP" in response.json()["detail"]


@pytest.mark.asyncio
async def test_convert_base64_invalid_format():
    """Base64 엔드포인트 — 지원하지 않는 형식 시 400 에러 확인"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/convert/base64",
            json={
                "filename": "test.txt",
                "content_base64": base64.b64encode(b"hello").decode(),
            },
        )

    assert response.status_code == 400
    assert "HWP" in response.json()["detail"]


@pytest.mark.asyncio
async def test_convert_base64_invalid_base64():
    """Base64 엔드포인트 — 잘못된 Base64 문자열 시 400 에러 확인"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/convert/base64",
            json={
                "filename": "test.hwp",
                "content_base64": "!!!not-valid-base64!!!",
            },
        )

    assert response.status_code == 400
    assert "Base64" in response.json()["detail"]


@pytest.mark.asyncio
async def test_convert_base64_api():
    """Base64 엔드포인트 — HWP 파일 변환 확인"""
    hwp_files = list(TESTS_DIR.glob("*.hwp"))
    if not hwp_files:
        pytest.skip("테스트용 HWP 파일이 없습니다")

    with open(hwp_files[0], "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/convert/base64",
            json={
                "filename": hwp_files[0].name,
                "content_base64": content_b64,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "filename" in data
    assert "markdown" in data
    assert len(data["markdown"]) > 0
