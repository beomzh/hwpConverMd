import logging
from pathlib import Path

from app.core.exceptions import UnsupportedFormatError
from app.services.hwp_converter import HwpConverter
from app.services.hwpx_converter import HwpxConverter

logger = logging.getLogger(__name__)

# 매직 바이트 상수
OLE2_MAGIC = b'\xd0\xcf\x11\xe0'   # OLE2 Compound Binary (HWP5)
ZIP_MAGIC = b'\x50\x4b\x03\x04'    # ZIP archive (HWPX)


class ConverterService:
    """매직 바이트 + 확장자 기반으로 적절한 변환기로 라우팅하는 디스패처"""

    @staticmethod
    def _detect_format(file_path: str) -> str:
        """파일의 첫 4바이트(매직 바이트)로 실제 포맷을 감지한다.

        Returns:
            "hwp"  — OLE2 Compound Binary (HWP5)
            "hwpx" — ZIP archive (HWPX/OOXML)
            None   — 판별 불가 (확장자 기반 폴백 필요)
        """
        try:
            with open(file_path, "rb") as f:
                header = f.read(4)
            if header[:4] == OLE2_MAGIC:
                return "hwp"
            if header[:4] == ZIP_MAGIC:
                return "hwpx"
        except Exception as e:
            logger.warning(f"매직 바이트 읽기 실패: {e}")
        return None

    @staticmethod
    def convert(file_path: str) -> str:
        ext = Path(file_path).suffix.lower()

        # 확장자 1차 검증: .hwp / .hwpx 만 허용
        if ext not in (".hwp", ".hwpx"):
            raise UnsupportedFormatError(
                f"지원하지 않는 파일 형식입니다: {ext} "
                f"(.hwp 또는 .hwpx만 지원)"
            )

        # 매직 바이트로 실제 포맷 감지
        detected = ConverterService._detect_format(file_path)

        if detected and detected != ext.lstrip("."):
            logger.info(
                f"포맷 자동 보정: 확장자={ext}, 실제={detected} → "
                f"{detected} 변환기 사용"
            )

        # 최종 포맷 결정: 매직 바이트 우선, 폴백은 확장자
        fmt = detected or ext.lstrip(".")

        if fmt == "hwp":
            return HwpConverter.convert(file_path)
        else:  # hwpx
            return HwpxConverter.convert(file_path)
