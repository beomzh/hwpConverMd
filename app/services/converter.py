import asyncio
import logging
import os
from pathlib import Path

from app.core.exceptions import UnsupportedFormatError
from app.services.hwp_converter import HwpConverter
from app.services.hwp_fast_converter import HwpFastConverter
from app.services.hwpx_converter import HwpxConverter

logger = logging.getLogger(__name__)

# 매직 바이트 상수
OLE2_MAGIC = b'\xd0\xcf\x11\xe0'   # OLE2 Compound Binary (HWP5)
ZIP_MAGIC = b'\x50\x4b\x03\x04'    # ZIP archive (HWPX)

# 고속 변환 비활성화 플래그 (환경변수로 제어)
# HWP_FAST_DISABLE=1 로 설정하면 기존 hwp5html 방식만 사용
FAST_DISABLE = os.environ.get("HWP_FAST_DISABLE", "0") == "1"


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
    async def convert(file_path: str) -> str:
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
            return await ConverterService._convert_hwp(file_path)
        else:  # hwpx (CPU-bound, executor에서 실행)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, HwpxConverter.convert, file_path
            )

    @staticmethod
    async def _convert_hwp(file_path: str) -> str:
        """HWP 파일 변환: 고속 경로 우선, 실패 시 hwp5html 폴백.

        고속 경로 (HwpFastConverter):
            pyhwp XML 직접 파싱 → Markdown (XSLT 건너뜀)
            대부분의 HWP 파일에서 10배 이상 빠름

        폴백 경로 (HwpConverter):
            hwp5html → HTML → markdownify → Markdown
            고속 경로 실패 시 안전하게 폴백
        """
        if not FAST_DISABLE:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, HwpFastConverter.convert, file_path
                )
                # 결과가 충분히 있는지 검증 (빈 결과면 폴백)
                if result and len(result.strip()) > 10:
                    return result
                else:
                    logger.warning(
                        f"고속 변환 결과가 너무 짧음 ({len(result)} chars), "
                        f"hwp5html 폴백"
                    )
            except Exception as e:
                logger.warning(
                    f"고속 변환 실패, hwp5html 폴백: {type(e).__name__}: {e}"
                )

        # 폴백: 기존 hwp5html 방식
        return await HwpConverter.convert(file_path)
