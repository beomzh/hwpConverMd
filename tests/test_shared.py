"""shared.py 공통 유틸리티 단위 테스트"""

from app.services.shared import (
    hex_to_color_marker,
    is_sparse_layout_table,
    layout_table_to_text,
    merge_sparse_rows,
    postprocess_cleanup,
    postprocess_headings,
    sparse_layout_to_text,
    strip_pua,
)


# ─── hex_to_color_marker ────────────────────────────────────────────────────


def test_hex_to_color_marker_red():
    assert hex_to_color_marker("#FF0000") == "🟥"


def test_hex_to_color_marker_blue():
    assert hex_to_color_marker("#0000FF") == "🟦"


def test_hex_to_color_marker_green():
    assert hex_to_color_marker("#00FF00") == "🟩"


def test_hex_to_color_marker_gray_dark():
    assert hex_to_color_marker("#333333") == "⬛"


def test_hex_to_color_marker_gray_light():
    assert hex_to_color_marker("#999999") == "■"


def test_hex_to_color_marker_light_blue():
    # 밝은 파랑은 하트 이모지
    result = hex_to_color_marker("#99CCFF")
    assert result == "💙"


def test_hex_to_color_marker_argb():
    # ARGB 8자리 → RGB 6자리로 변환
    assert hex_to_color_marker("#FF0000FF") == "🟦"


def test_hex_to_color_marker_invalid():
    assert hex_to_color_marker("xyz") == "■"
    assert hex_to_color_marker("") == "■"


# ─── strip_pua ───────────────────────────────────────────────────────────────


def test_strip_pua():
    assert strip_pua("Hello\uE000World") == "HelloWorld"
    assert strip_pua("\uE001\uE002\uE003") == ""


def test_strip_pua_no_pua():
    assert strip_pua("정상 텍스트") == "정상 텍스트"


def test_strip_pua_whitespace():
    assert strip_pua("  \uE000  ") == ""


# ─── merge_sparse_rows ──────────────────────────────────────────────────────


def test_merge_sparse_rows_basic():
    # 겹치지 않는 셀만 병합 가능
    grid = [
        ["A", "", "C"],
        ["", "D", ""],  # sparse: 1 non-empty, B 위치 비어있어 병합 가능
    ]
    result = merge_sparse_rows(grid, 3)
    assert len(result) == 1
    assert result[0] == ["A", "D", "C"]


def test_merge_sparse_rows_no_merge():
    grid = [
        ["A", "B", "C"],
        ["D", "E", "F"],
    ]
    result = merge_sparse_rows(grid, 3)
    assert len(result) == 2


def test_merge_sparse_rows_empty():
    assert merge_sparse_rows([], 3) == []


def test_merge_sparse_rows_conflict():
    # 겹치는 셀이 있으면 병합하지 않음
    grid = [
        ["A", "B", ""],
        ["", "X", ""],  # B와 X 겹침
    ]
    result = merge_sparse_rows(grid, 3)
    assert len(result) == 2


# ─── layout_table_to_text ────────────────────────────────────────────────────


def test_layout_table_to_text():
    cells = [
        {"row": 0, "text": "부서A"},
        {"row": 0, "text": "부서B"},
        {"row": 1, "text": "담당C"},
    ]
    result = layout_table_to_text(cells)
    assert "부서A / 부서B" in result
    assert "담당C" in result


def test_layout_table_to_text_dedup():
    cells = [
        {"row": 0, "text": "중복"},
        {"row": 0, "text": "중복"},
        {"row": 0, "text": "다른텍스트"},
    ]
    result = layout_table_to_text(cells)
    assert result.count("중복") == 1


def test_layout_table_to_text_empty():
    cells = [
        {"row": 0, "text": ""},
        {"row": 0, "text": "  "},
    ]
    result = layout_table_to_text(cells)
    assert result == ""


# ─── postprocess_headings ────────────────────────────────────────────────────


def test_postprocess_headings_roman():
    text = "Ⅰ. 일반현황"
    result = postprocess_headings(text)
    assert result == "## Ⅰ. 일반현황"


def test_postprocess_headings_roman2():
    text = "Ⅲ. 기술 및 기능"
    result = postprocess_headings(text)
    assert result == "## Ⅲ. 기술 및 기능"


def test_postprocess_headings_roman_bold():
    # 볼드로 감싼 로마자도 인식하여 ## 헤딩 추가 (볼드 제거)
    text = "**Ⅰ. 일반현황**"
    result = postprocess_headings(text)
    assert result == "## Ⅰ. 일반현황"


def test_postprocess_headings_roman_bold2():
    text = "**Ⅴ. 프로젝트 관리**"
    result = postprocess_headings(text)
    assert result == "## Ⅴ. 프로젝트 관리"


def test_postprocess_headings_level1():
    text = "1. 사업 개요"
    result = postprocess_headings(text)
    assert result == "### 1. 사업 개요"


def test_postprocess_headings_level1_long_skip():
    # 30자 초과 긴 문장은 제목이 아닌 번호 목록 → 헤딩 추가 안 함
    text = "1. 수요기관은 3점 이내의 순위별 점수차를 명시하여 차등점수제를 적용 요청하여야 한다."
    result = postprocess_headings(text)
    assert result == text  # 헤딩 추가 안 됨


def test_postprocess_headings_level2():
    text = "1.2 세부사항"
    result = postprocess_headings(text)
    assert result == "#### 1.2 세부사항"


def test_postprocess_headings_level3():
    text = "1.2.3 항목"
    result = postprocess_headings(text)
    assert result == "##### 1.2.3 항목"


def test_postprocess_headings_table_skip():
    text = "| 1. 제목 | 내용 |"
    result = postprocess_headings(text)
    assert result == text  # 테이블 행은 변환하지 않음


def test_postprocess_headings_existing_heading():
    text = "## 이미 헤딩"
    result = postprocess_headings(text)
    assert result == "## 이미 헤딩"


# ─── postprocess_cleanup ─────────────────────────────────────────────────────


def test_postprocess_cleanup_nbsp():
    text = "Hello\xa0World"
    result = postprocess_cleanup(text)
    assert "\xa0" not in result
    assert "Hello World" in result


def test_postprocess_cleanup_blank_lines():
    text = "A\n\n\n\n\nB"
    result = postprocess_cleanup(text)
    assert result == "A\n\nB"


def test_postprocess_cleanup_strip():
    text = "\n\n  내용  \n\n"
    result = postprocess_cleanup(text)
    assert result == "내용"


def test_postprocess_cleanup_bold_single_punct():
    # 단일 구두점 볼드 제거: **>** → >
    text = "< 누출 금지 정보 **>**"
    result = postprocess_cleanup(text)
    assert result == "< 누출 금지 정보 >"


def test_postprocess_cleanup_bold_single_dash():
    # **-** → -
    text = "**-** 망간 자료전송"
    result = postprocess_cleanup(text)
    assert result == "- 망간 자료전송"


def test_postprocess_cleanup_bold_bracket_fix():
    # 여는 괄호가 볼드 안에 있고 닫는 괄호가 볼드 밖인 경우 수정
    text = "**제6조(용역의 착수 및 수행**) 내용"
    result = postprocess_cleanup(text)
    assert result == "**제6조(용역의 착수 및 수행)** 내용"


def test_postprocess_cleanup_bold_angle_bracket_fix():
    text = "**<차등점수제 적용 방식**> 설명"
    result = postprocess_cleanup(text)
    assert result == "**<차등점수제 적용 방식>** 설명"


def test_postprocess_cleanup_bold_no_opener_no_fix():
    # 여는 괄호가 없으면 수정하지 않음
    text = "**볼드 텍스트**) 다음"
    result = postprocess_cleanup(text)
    assert result == "**볼드 텍스트**) 다음"


# ─── is_sparse_layout_table ──────────────────────────────────────────────────


def test_is_sparse_layout_table_true():
    # 3x3 테이블, 2개 셀만 비어있지 않음 (제목/내용 분리 레이아웃)
    grid = [
        ["", "제목", ""],
        ["내용 1\n내용 2", "", ""],
    ]
    assert is_sparse_layout_table(grid, 3) is True


def test_is_sparse_layout_table_false_data_table():
    # 일반 데이터 테이블 (대부분 셀이 채워짐)
    grid = [
        ["A", "B", "C"],
        ["D", "E", "F"],
    ]
    assert is_sparse_layout_table(grid, 3) is False


def test_is_sparse_layout_table_false_small():
    # 1행 테이블은 레이아웃 판정하지 않음
    grid = [["A", "", ""]]
    assert is_sparse_layout_table(grid, 3) is False


def test_is_sparse_layout_table_false_single_col():
    # 1열 테이블은 레이아웃 판정하지 않음
    grid = [["A"], ["B"]]
    assert is_sparse_layout_table(grid, 1) is False


# ─── sparse_layout_to_text ───────────────────────────────────────────────────


def test_sparse_layout_to_text():
    grid = [
        ["", "제목 텍스트", ""],
        ["항목 1\n항목 2", "", ""],
    ]
    result = sparse_layout_to_text(grid)
    assert "제목 텍스트" in result
    assert "항목 1" in result
    assert "항목 2" in result
    # 제목이 먼저 나와야 함 (행 순서 유지)
    assert result.index("제목 텍스트") < result.index("항목 1")
