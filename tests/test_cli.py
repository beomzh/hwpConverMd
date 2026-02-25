"""CLI 통합 테스트"""

import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = TESTS_DIR.parent


def test_cli_hwp_to_stdout():
    """CLI: HWP 파일을 표준출력으로 변환"""
    hwp_files = list(TESTS_DIR.glob("*.hwp"))
    if not hwp_files:
        pytest.skip("테스트용 HWP 파일이 없습니다")

    result = subprocess.run(
        [sys.executable, "-m", "app", str(hwp_files[0])],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )

    assert result.returncode == 0
    assert len(result.stdout) > 0
    print(f"\n--- CLI 변환 결과 (처음 300자) ---\n{result.stdout[:300]}")


def test_cli_hwp_to_file(tmp_path):
    """CLI: HWP 파일을 .md 파일로 변환"""
    hwp_files = list(TESTS_DIR.glob("*.hwp"))
    if not hwp_files:
        pytest.skip("테스트용 HWP 파일이 없습니다")

    output_file = tmp_path / "output.md"

    result = subprocess.run(
        [sys.executable, "-m", "app", str(hwp_files[0]), "-o", str(output_file)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )

    assert result.returncode == 0
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    assert len(content) > 0
    print(f"\n--- 파일 출력 결과 (처음 300자) ---\n{content[:300]}")


def test_cli_invalid_format(tmp_path):
    """CLI: 지원하지 않는 형식은 오류 코드 반환"""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("dummy")

    result = subprocess.run(
        [sys.executable, "-m", "app", str(txt_file)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )

    assert result.returncode != 0
    assert "지원하지 않는" in result.stderr


def test_cli_nonexistent_file():
    """CLI: 존재하지 않는 파일은 오류 코드 반환"""
    result = subprocess.run(
        [sys.executable, "-m", "app", "nonexistent.hwp"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )

    assert result.returncode != 0
    assert "찾을 수 없습니다" in result.stderr
