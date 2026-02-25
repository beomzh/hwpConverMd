"""CLI 도구: HWP/HWPX 파일을 Markdown으로 변환

사용법:
    python -m app input.hwp
    python -m app input.hwp -o output.md
    python -m app input.hwpx -o output.md
"""

import argparse
import sys
from pathlib import Path

from app.core.exceptions import ConversionError
from app.services.converter import ConverterService


def main():
    parser = argparse.ArgumentParser(
        description="HWP/HWPX 파일을 Markdown으로 변환합니다."
    )
    parser.add_argument(
        "input",
        help="입력 파일 경로 (.hwp 또는 .hwpx)",
    )
    parser.add_argument(
        "-o", "--output",
        help="출력 파일 경로 (.md). 미지정 시 표준출력으로 출력",
        default=None,
    )

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.suffix.lower() not in (".hwp", ".hwpx"):
        print(
            f"오류: 지원하지 않는 파일 형식입니다: {input_path.suffix} "
            f"(.hwp 또는 .hwpx만 지원)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        markdown_text = ConverterService.convert(str(input_path))
    except ConversionError as e:
        print(f"변환 오류: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown_text, encoding="utf-8")
        print(f"변환 완료: {output_path}", file=sys.stderr)
    else:
        print(markdown_text)


if __name__ == "__main__":
    main()
