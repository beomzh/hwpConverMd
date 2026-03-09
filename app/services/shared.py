"""HWP/HWPX 변환기 공통 유틸리티

세 변환기(hwp_fast_converter, hwpx_converter, hwp_converter)에서
동일하게 사용되는 함수들을 한 곳에 모아 중복을 제거한다.
"""

import re


# ─── 색상 마커 ────────────────────────────────────────────────────────────


def hex_to_color_marker(hex_color: str) -> str:
    """hex 색상 코드를 가장 가까운 색상 마커로 변환한다.

    일정표·간트 차트 등에서 색칠된 빈 셀을 시각적으로 구분하기 위해 사용.
    - 회색 계열: 밝기에 따라 ■ (짙은 회색) 또는 ⬛ (검은색)
    - 색상 계열: HSL 기반으로 가장 가까운 이모지 반환
    - 밝기(Lightness) 0.65 이상이면 밝은 색 이모지 사용
    """
    hex_color = hex_color.lstrip("#").lower()
    if len(hex_color) == 8:
        hex_color = hex_color[2:]  # ARGB → RGB
    if len(hex_color) != 6:
        return "■"
    r, g, b = (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )

    # 회색 계열 (R≈G≈B) — 임계값 20 이내만 회색 판정
    if abs(r - g) < 20 and abs(g - b) < 20 and abs(r - b) < 20:
        avg = (r + g + b) // 3
        if avg < 80:
            return "⬛"
        return "■"

    # HSL 기반 색상 판별을 위한 Hue·Lightness 계산
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    diff = max_c - min_c
    if diff == 0:
        return "■"

    lightness = (max_c + min_c) / 510.0

    if max_c == r:
        hue = 60 * (((g - b) / diff) % 6)
    elif max_c == g:
        hue = 60 * (((b - r) / diff) + 2)
    else:
        hue = 60 * (((r - g) / diff) + 4)

    is_light = lightness >= 0.65

    if hue < 15 or hue >= 345:
        return "❤️" if is_light else "🟥"
    elif hue < 45:
        return "🧡" if is_light else "🟧"
    elif hue < 70:
        return "💛" if is_light else "🟨"
    elif hue < 160:
        return "💚" if is_light else "🟩"
    elif hue < 260:
        return "💙" if is_light else "🟦"
    elif hue < 310:
        return "💜" if is_light else "🟪"
    else:
        return "❤️" if is_light else "🟥"


# ─── 텍스트 유틸리티 ──────────────────────────────────────────────────────


def strip_pua(text: str) -> str:
    """Private Use Area (U+E000-U+F8FF) 등 비표시 문자를 제거한다.

    HWP/HWPX 문서에서 Wingdings 등 특수 폰트 기호가
    PUA 코드포인트로 저장되어 빈 텍스트처럼 보이지만 문자열 비교에서
    truthy로 평가되는 문제를 방지한다.
    """
    return re.sub(r'[\uE000-\uF8FF]', '', text).strip()


# ─── 테이블 유틸리티 ──────────────────────────────────────────────────────


def merge_sparse_rows(grid, num_cols):
    """비어있지 않은 셀이 매우 적은 행을 위 행에 병합한다.

    rowspan으로 인해 빈 셀이 많은 행에서 발생하는 문제를 해결한다.
    예: 첫 행에 rowSpan=3인 셀이 있으면 2,3행의 해당 열은 비어 있다.
        이런 행에서 non-empty 셀이 적으면 위 행에 병합하여 가독성을 높인다.
    """
    if not grid:
        return grid

    sparse_threshold = max(1, num_cols // 3)
    merged = [list(grid[0])]

    for row in grid[1:]:
        non_empty = sum(1 for c in row if c.strip())
        if non_empty <= sparse_threshold and non_empty > 0 and merged:
            prev = merged[-1]
            can_merge = all(
                not (prev[c].strip() and row[c].strip())
                for c in range(min(len(prev), len(row), num_cols))
            )
            if can_merge:
                for c in range(min(len(prev), len(row), num_cols)):
                    if row[c].strip():
                        prev[c] = row[c]
                continue
        merged.append(list(row))

    return merged


def is_sparse_layout_table(grid, num_cols):
    """행별로 비어있지 않은 셀이 최대 1개인 희소 테이블인지 판별한다.

    레이아웃용 테이블(제목과 내용이 다른 행/열에 분산)은
    마크다운 테이블로 변환하면 의미를 잃으므로 텍스트 추출이 더 적절하다.

    조건:
      - 2행 이상, 2열 이상
      - 비어있지 않은 셀 비율 40% 미만
      - 행당 평균 비어있지 않은 셀 ≤ 1개 (= 총 비어있지 않은 셀 ≤ 행 수)
    """
    if not grid or len(grid) < 2 or num_cols < 2:
        return False

    data_rows = len(grid)
    total_cells = data_rows * num_cols
    non_empty = sum(1 for row in grid for cell in row if cell.strip())

    if total_cells == 0:
        return False

    fill_ratio = non_empty / total_cells
    return fill_ratio < 0.4 and non_empty <= data_rows


def sparse_layout_to_text(grid):
    """희소 레이아웃 테이블을 텍스트로 변환한다.

    각 행의 비어있지 않은 셀들을 순서대로 추출하여
    행 순서를 유지한 텍스트로 변환한다.
    """
    lines = []
    for row in grid:
        for cell in row:
            text = cell.strip()
            if text:
                # 셀 내 줄바꿈은 단락 구분으로 변환
                text = text.replace("\n", "\n\n")
                lines.append(text)
    return "\n\n".join(lines)


def layout_table_to_text(cell_data):
    """레이아웃 테이블(20열+)을 텍스트로 변환한다.

    조직도/다이어그램 등 수십 열의 레이아웃 테이블은
    마크다운 테이블로 변환하면 읽을 수 없으므로 텍스트로 추출한다.
    중복 텍스트는 제거한다.

    Args:
        cell_data: [{"row": int, "text": str, ...}, ...]
    """
    seen = set()
    lines = []
    current_row = -1
    row_parts = []

    for cell in cell_data:
        if cell["row"] != current_row:
            if row_parts:
                lines.append(" / ".join(row_parts))
            row_parts = []
            current_row = cell["row"]

        text = cell["text"].strip()
        if text and text not in seen:
            row_parts.append(text)
            seen.add(text)

    if row_parts:
        lines.append(" / ".join(row_parts))

    return "\n\n".join(lines)


# ─── Markdown 후처리 ─────────────────────────────────────────────────────


def postprocess_headings(text: str) -> str:
    """번호 기반 제목/소제목에 Markdown 헤딩을 추가한다.

    "Ⅰ. 제목"     → "## Ⅰ. 제목"     (로마자 대분류)
    "**Ⅰ. 제목**" → "## Ⅰ. 제목"     (볼드 로마자도 인식)
    "1. 제목"      → "### 1. 제목"     (1단계)
    "1.2 제목"     → "#### 1.2 제목"   (2단계)
    "1.2.3 제목"   → "##### 1.2.3 제목" (3단계)
    테이블 행(|)과 이미 # 마크가 있는 줄은 제외.
    긴 문장(30자 초과)은 제목이 아닌 번호 목록으로 판단하여 제외.
    """
    # 번호 뒤 내용이 이 길이를 초과하면 제목이 아닌 목록 항목으로 간주
    _MAX_HEADING_CONTENT = 30

    heading_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if '|' in stripped or stripped.startswith('#'):
            heading_lines.append(line)
            continue
        # 볼드 마커 제거하여 패턴 매칭용 텍스트 생성
        bare = stripped.strip('*').strip()
        # 로마자 대분류: Ⅰ. Ⅱ. Ⅲ. 등 (볼드 포함)
        if re.match(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ][\.\s]', bare):
            heading_lines.append(f'## {bare}')
        # 3단계: N.N.N 형식
        elif re.match(r'^\d+\.\d+\.\d+\.?\s+\S', stripped):
            content = re.sub(r'^\d+\.\d+\.\d+\.?\s+', '', stripped)
            if len(content) <= _MAX_HEADING_CONTENT:
                heading_lines.append(f'##### {stripped}')
            else:
                heading_lines.append(line)
        # 2단계: N.N 형식
        elif re.match(r'^\d+\.\d+\.?\s+\S', stripped):
            content = re.sub(r'^\d+\.\d+\.?\s+', '', stripped)
            if len(content) <= _MAX_HEADING_CONTENT:
                heading_lines.append(f'#### {stripped}')
            else:
                heading_lines.append(line)
        # 1단계: N. 형식
        elif re.match(r'^\d+\.\s+\S', stripped):
            content = re.sub(r'^\d+\.\s+', '', stripped)
            if len(content) <= _MAX_HEADING_CONTENT:
                heading_lines.append(f'### {stripped}')
            else:
                heading_lines.append(line)
        else:
            heading_lines.append(line)
    return '\n'.join(heading_lines)


def postprocess_cleanup(text: str) -> str:
    """공통 후처리: nbsp 제거, 과도한 빈 줄 정리, 볼드 깨짐 수정."""
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\n{3,}', '\n\n', text)

    # --- 볼드 마크업 깨짐 수정 ---
    # 1) 단일 구두점 볼드 제거: **>** → >, **-** → -, **)** → ) 등
    text = re.sub(r'\*\*([^\w\s])\*\*', r'\1', text)

    # 2) 여는 괄호가 볼드 안에 있는데 닫는 괄호가 볼드 밖인 경우 수정
    #    **제6조(용역의 착수 및 수행**) → **제6조(용역의 착수 및 수행)**
    def _fix_bold_bracket(m):
        inner = m.group(1)
        bracket = m.group(2)
        openers = {'(': ')', '<': '>', '[': ']', '「': '」'}
        opener = {v: k for k, v in openers.items()}.get(bracket)
        if opener and opener in inner:
            return f'**{inner}{bracket}**'
        return m.group(0)

    text = re.sub(
        r'\*\*((?:(?!\*\*).)+?)\*\*([)>\]」])',
        _fix_bold_bracket, text,
    )

    return text.strip()
