"""변환 서비스 단위 테스트"""

import pytest

from app.core.exceptions import UnsupportedFormatError
from app.services.converter import ConverterService


@pytest.mark.asyncio
async def test_convert_hwp_file(hwp_file):
    """HWP 파일이 정상적으로 Markdown으로 변환되는지 확인"""
    result = await ConverterService.convert(str(hwp_file))
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\n--- HWP 변환 결과 (처음 500자) ---\n{result[:500]}")


@pytest.mark.asyncio
async def test_convert_hwpx_file(hwpx_file):
    """HWPX 파일이 정상적으로 Markdown으로 변환되는지 확인"""
    result = await ConverterService.convert(str(hwpx_file))
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\n--- HWPX 변환 결과 (처음 500자) ---\n{result[:500]}")


@pytest.mark.asyncio
async def test_unsupported_format(sample_txt):
    """지원하지 않는 형식 파일은 예외를 발생시키는지 확인"""
    with pytest.raises(UnsupportedFormatError):
        await ConverterService.convert(str(sample_txt))


@pytest.mark.asyncio
async def test_convert_nonexistent_file():
    """존재하지 않는 파일은 예외를 발생시키는지 확인"""
    with pytest.raises(Exception):
        await ConverterService.convert("/nonexistent/file.hwp")
