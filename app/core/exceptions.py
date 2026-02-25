class ConversionError(Exception):
    """변환 실패 시 발생하는 기본 예외"""
    pass


class UnsupportedFormatError(ConversionError):
    """지원하지 않는 파일 형식"""
    pass


class HwpConversionError(ConversionError):
    """HWP 파일 변환 실패"""
    pass


class HwpxParsingError(ConversionError):
    """HWPX 파일 파싱 실패"""
    pass
