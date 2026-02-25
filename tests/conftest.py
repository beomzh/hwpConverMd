import pytest
from pathlib import Path

TESTS_DIR = Path(__file__).parent


@pytest.fixture
def hwp_file():
    """tests 디렉토리의 HWP 테스트 파일 경로를 반환한다."""
    files = list(TESTS_DIR.glob("*.hwp"))
    if not files:
        pytest.skip("테스트용 HWP 파일이 없습니다")
    return files[0]


@pytest.fixture
def hwpx_file():
    """tests 디렉토리의 HWPX 테스트 파일 경로를 반환한다."""
    files = list(TESTS_DIR.glob("*.hwpx"))
    if not files:
        pytest.skip("테스트용 HWPX 파일이 없습니다")
    return files[0]


@pytest.fixture
def sample_txt(tmp_path):
    """잘못된 형식의 텍스트 파일을 생성한다."""
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("이것은 텍스트 파일입니다.")
    return txt_file
