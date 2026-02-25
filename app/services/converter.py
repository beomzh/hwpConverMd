from pathlib import Path

from app.core.exceptions import UnsupportedFormatError
from app.services.hwp_converter import HwpConverter
from app.services.hwpx_converter import HwpxConverter


class ConverterService:
    """파일 확장자에 따라 적절한 변환기로 라우팅하는 디스패처"""

    @staticmethod
    def convert(file_path: str) -> str:
        ext = Path(file_path).suffix.lower()

        if ext == ".hwp":
            return HwpConverter.convert(file_path)
        elif ext == ".hwpx":
            return HwpxConverter.convert(file_path)
        else:
            raise UnsupportedFormatError(
                f"지원하지 않는 파일 형식입니다: {ext} "
                f"(.hwp 또는 .hwpx만 지원)"
            )
