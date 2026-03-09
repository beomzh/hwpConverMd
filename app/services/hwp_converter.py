import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as md

from app.core.exceptions import HwpConversionError
from app.services.shared import (
    hex_to_color_marker,
    postprocess_cleanup,
    postprocess_headings,
)

logger = logging.getLogger(__name__)

# hwp5html 타임아웃 (초), 환경변수로 설정 가능, 기본 180초
HWP5HTML_TIMEOUT = int(os.environ.get("HWP5HTML_TIMEOUT", "300"))


class HwpConverter:
    @staticmethod
    async def convert(hwp_path: str) -> str:
        """HWP 파일을 Markdown 문자열로 변환한다.

        hwp5html로 HWP->HTML 변환 후 markdownify로 HTML->MD 변환.
        테이블은 커스텀 파서로 별도 처리한다.
        타임아웃 시 부분 출력이 있으면 그것을 사용한다.
        """
        file_size = Path(hwp_path).stat().st_size
        file_size_mb = round(file_size / (1024 * 1024), 1)
        logger.info(f"HWP 변환 시작: {hwp_path} ({file_size_mb}MB)")

        with tempfile.TemporaryDirectory() as output_dir:
            timed_out = False
            try:
                proc = await asyncio.create_subprocess_exec(
                    "hwp5html", "--output", output_dir, hwp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=HWP5HTML_TIMEOUT
                )
                if proc.returncode != 0:
                    raise HwpConversionError(
                        f"hwp5html 변환 실패: {stderr.decode()[:500]}"
                    )
            except FileNotFoundError:
                raise HwpConversionError(
                    "hwp5html 명령어를 찾을 수 없습니다. "
                    "pyhwp를 설치하세요: pip install pyhwp"
                )
            except asyncio.TimeoutError:
                timed_out = True
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                logger.warning(
                    f"hwp5html 타임아웃 ({HWP5HTML_TIMEOUT}초): {hwp_path} "
                    f"({file_size_mb}MB) — 부분 출력 확인 중..."
                )

            # 타임아웃이어도 부분 출력이 있으면 사용
            html_file = _find_html_output(output_dir)
            if html_file is None:
                if timed_out:
                    raise HwpConversionError(
                        f"hwp5html 변환 시간 초과 ({HWP5HTML_TIMEOUT}초), "
                        f"부분 출력도 없음 ({file_size_mb}MB)"
                    )
                raise HwpConversionError(
                    f"hwp5html 출력에서 HTML 파일을 찾을 수 없습니다: "
                    f"{list(Path(output_dir).iterdir())}"
                )

            html_size = html_file.stat().st_size
            if html_size == 0:
                raise HwpConversionError(
                    f"hwp5html 출력이 빈 파일입니다 ({file_size_mb}MB). "
                    f"이 HWP 파일을 변환할 수 없습니다."
                )

            if timed_out:
                logger.info(
                    f"타임아웃이지만 부분 출력 사용: {html_file.name} "
                    f"({html_size} bytes)"
                )

            html_content = html_file.read_text(encoding="utf-8")

            # 0. CSS에서 셀 배경색 정보 추출 (일정표 등 색칠된 셀 처리용)
            css_file = Path(output_dir) / "styles.css"
            bg_map = {}
            if css_file.exists():
                bg_map = _parse_css_backgrounds(
                    css_file.read_text(encoding="utf-8")
                )

            # 1. HTML 테이블을 커스텀 파서로 먼저 변환 → placeholder 치환
            html_content, table_map = _convert_html_tables(
                html_content, bg_map
            )

            # 2. 테이블이 제거된 HTML을 markdownify로 변환
            markdown_text = md(html_content, heading_style="ATX")

            # 3. placeholder를 마크다운 테이블로 복원
            #    markdownify가 언더스코어를 \_로 이스케이프하므로 양쪽 모두 매칭
            for placeholder, table_md in table_map.items():
                escaped = placeholder.replace("_", r"\_")
                markdown_text = markdown_text.replace(escaped, f"\n\n{table_md}\n\n")
                markdown_text = markdown_text.replace(placeholder, f"\n\n{table_md}\n\n")

            # 4. 후처리
            markdown_text = _postprocess(markdown_text)

            return markdown_text.strip()


def _find_html_output(output_dir: str):
    """hwp5html 출력 디렉토리에서 HTML 파일을 찾는다.

    Returns:
        Path 객체 또는 None
    """
    for name in ("index.xhtml", "index.html"):
        p = Path(output_dir) / name
        if p.exists():
            return p
    html_files = list(Path(output_dir).glob("*.xhtml")) + list(
        Path(output_dir).glob("*.html")
    )
    return html_files[0] if html_files else None


def _parse_css_backgrounds(css: str) -> dict:
    """CSS에서 borderfill 클래스의 background-color를 추출한다.

    Returns:
        {클래스명: 배경색(소문자 hex)} 딕셔너리
    """
    bg_map = {}
    for m in re.finditer(
        r"\.(borderfill-\d+)\s*\{[^}]*background-color:\s*(#[0-9a-fA-F]+)",
        css,
    ):
        bg_map[m.group(1)] = m.group(2).lower()
    return bg_map


def _convert_html_tables(html: str, bg_map: dict = None) -> tuple:
    """HTML 내 모든 <table> 요소를 마크다운 테이블로 변환하고 placeholder로 치환한다.

    연속된 레이아웃 테이블(조직도 등)이 같은 내용을 반복하면 중복 제거한다.

    Returns:
        (치환된 HTML 문자열, {placeholder: 마크다운 테이블} 딕셔너리)
    """
    soup = BeautifulSoup(html, "html.parser")
    table_map = {}
    prev_layout_texts = None  # 직전 레이아웃 테이블의 텍스트 집합 (중복 제거용)

    for i, table in enumerate(soup.find_all("table")):
        # 이미 decompose된 테이블(중첩 테이블의 내부 테이블)은 건너뛰기
        if table.parent is None:
            continue
        is_layout = _is_layout_table(table)
        table_md = _html_table_to_markdown(table, bg_map or {})

        # 연속된 레이아웃 테이블 중복 제거
        if is_layout and table_md:
            current_texts = {
                t.strip()
                for line in table_md.split("\n")
                for t in line.split("/")
                if t.strip()
            }
            if (
                prev_layout_texts
                and current_texts
                and current_texts.issubset(prev_layout_texts)
            ):
                table.decompose()
                continue
            prev_layout_texts = current_texts
        elif not is_layout:
            prev_layout_texts = None

        placeholder = f"<!--TABLE_PLACEHOLDER_{i}-->"
        table_map[placeholder] = table_md
        table.replace_with(placeholder)

    return str(soup), table_map


def _is_layout_table(table) -> bool:
    """테이블이 비주얼 레이아웃 테이블(조직도, 다이어그램 등)인지 판별한다.

    HWP는 조직도/다이어그램을 수백 개의 작은 셀로 구성된 레이아웃 테이블로 표현한다.
    열 수가 20 이상이면 데이터 테이블이 아닌 레이아웃 테이블로 판정한다.
    """
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        col_count = sum(int(c.get("colspan", 1)) for c in cells)
        if col_count >= 20:
            return True
    return False


def _flatten_nested_tables(table) -> None:
    """테이블 셀 내부의 중첩 테이블을 텍스트로 변환한다.

    HWP 문서에서 셀 안에 또 다른 테이블이 들어가는 경우가 있다.
    이를 그대로 두면 외부 테이블의 find_all('tr')이 내부 테이블 행까지
    포착하여 열 수가 맞지 않는 문제가 발생한다.

    내부 테이블의 각 행을 " / "로 연결한 텍스트 줄로 변환하고,
    내부 테이블(및 부모 <p>)을 새 <p> 태그들로 교체한다.
    """
    for inner_table in table.find_all("table"):
        inner_rows = inner_table.find_all("tr")
        if not inner_rows:
            continue

        text_lines = []
        for inner_tr in inner_rows:
            cells = inner_tr.find_all(["td", "th"])
            parts = []
            for c in cells:
                t = c.get_text(strip=True)
                if t:
                    parts.append(t)
            if parts:
                text_lines.append(" / ".join(parts))

        if not text_lines:
            continue

        # 내부 테이블이 <p> 안에 있으면(직접 또는 <span> 등 중첩),
        # 부모 <p>를 통째로 교체해야 find_all("p")에서 중복 텍스트가 발생하지 않음
        insert_point = inner_table
        ancestor = inner_table.parent
        while ancestor and ancestor.name not in ("td", "th", "table"):
            if ancestor.name == "p":
                insert_point = ancestor
                break
            ancestor = ancestor.parent

        # 새 <p> 태그를 삽입 지점 앞에 생성
        temp_soup = BeautifulSoup("<div></div>", "html.parser")
        for line in text_lines:
            p_tag = temp_soup.new_tag("p")
            p_tag.string = line
            insert_point.insert_before(p_tag)

        # 삽입 지점(내부 테이블 또는 부모 <p>) 제거
        insert_point.decompose()


def _html_table_to_markdown(table, bg_map: dict = None) -> str:
    """BeautifulSoup <table> 요소를 마크다운 테이블 문자열로 변환한다.

    rowspan/colspan을 처리하여 올바른 2D 그리드를 구축한다.
    다중 행 헤더는 단일 행으로 병합한다.
    1열짜리 테이블(목차 등)은 일반 텍스트로 변환한다.
    중첩 테이블은 텍스트로 플래튼한다.
    """
    # --- 사전 처리: 중첩 테이블 플래튼 ---
    _flatten_nested_tables(table)

    rows = table.find_all("tr")
    if not rows:
        return ""

    # --- 0단계: 1열 테이블 감지 (목차 등) → 일반 텍스트로 변환 ---
    is_single_col = True
    for tr in rows:
        cells = tr.find_all(["td", "th"])
        col_count = sum(int(c.get("colspan", 1)) for c in cells)
        if col_count > 1:
            is_single_col = False
            break

    if is_single_col:
        lines = []
        for tr in rows:
            cell = tr.find(["td", "th"])
            if cell:
                paragraphs = cell.find_all("p")
                if paragraphs:
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if text:
                            lines.append(text)
                else:
                    text = cell.get_text(strip=True)
                    if text:
                        lines.append(text)
        return "\n\n".join(lines)

    # --- 0.5단계: 레이아웃 테이블 감지 (조직도, 다이어그램 등) ---
    # HWP의 비주얼 레이아웃 테이블은 열 수가 매우 많음 (20+)
    max_cols_in_table = 0
    for tr in rows:
        cells = tr.find_all(["td", "th"])
        col_count = sum(int(c.get("colspan", 1)) for c in cells)
        max_cols_in_table = max(max_cols_in_table, col_count)

    if max_cols_in_table >= 20:
        return _layout_table_to_text(rows)

    # --- 1단계: 첫 행의 최대 rowspan으로 헤더 행 수 결정 ---
    first_row_cells = rows[0].find_all(["td", "th"])
    header_row_count = 1
    for cell in first_row_cells:
        rs = int(cell.get("rowspan", 1))
        if rs > header_row_count:
            header_row_count = rs

    # --- 1.5단계: 전체 행 배경색 감지 (행 전체가 같은 색이면 마커 제외) ---
    skip_colors = {"#ffffff", "#fff"}
    full_color_rows = set()
    if bg_map:
        for row_idx, tr in enumerate(rows):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            colored = 0
            for cell in cells:
                for c in cell.get("class", []):
                    if c in bg_map and bg_map[c] not in skip_colors:
                        colored += 1
                        break
            if colored == len(cells):
                full_color_rows.add(row_idx)

    # --- 2단계: 2D 그리드 구축 (rowspan/colspan 처리) ---
    grid = []
    occupied = set()  # set of (row, col) — 이전 rowspan/colspan이 차지한 셀

    for row_idx, tr in enumerate(rows):
        cells = tr.find_all(["td", "th"])
        col_idx = 0
        grid_row = []

        # 전체 행이 같은 색이면 → 색상 마커 미적용
        row_bg_map = None if row_idx in full_color_rows else (bg_map or {})

        for cell in cells:
            # 이미 점유된 셀 건너뛰기
            while (row_idx, col_idx) in occupied:
                grid_row.append("")
                col_idx += 1

            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))

            # colspan > 1: 큰 공백으로 구분된 텍스트 분리 시도
            split_parts = _try_split_cell(cell, colspan) if colspan > 1 else []

            if split_parts:
                for idx in range(colspan):
                    if idx < len(split_parts):
                        grid_row.append(split_parts[idx])
                    else:
                        grid_row.append("")
            else:
                cell_text = _extract_cell_text(cell, row_bg_map)
                grid_row.append(cell_text)
                for c in range(1, colspan):
                    grid_row.append("")

            # rowspan 처리: 아래 행 점유 마킹
            for r in range(1, rowspan):
                for c in range(colspan):
                    occupied.add((row_idx + r, col_idx + c))

            col_idx += colspan

        # 남은 점유 셀 처리
        while (row_idx, col_idx) in occupied:
            grid_row.append("")
            col_idx += 1

        grid.append(grid_row)

    if not grid:
        return ""

    # --- 3단계: 열 수 통일 ---
    max_cols = max(len(row) for row in grid)
    for row in grid:
        while len(row) < max_cols:
            row.append("")

    # --- 3.5단계: 헤더 하위 행 병합 ---
    # rowspan 차이로 분리된 하위 헤더 행들을 합친다.
    # 예: row1=[물품식별번호, 제품규격, ...], row2=[..., 라이센스적용범위]
    #   → 비어 있지 않은 셀이 겹치지 않으면 하나로 합침
    if header_row_count > 2:
        merged_sub = [list(grid[1])]
        for r in range(2, header_row_count):
            last = merged_sub[-1]
            current = grid[r]
            can_merge = all(
                not (last[c] and current[c]) for c in range(max_cols)
            )
            if can_merge:
                for c in range(max_cols):
                    if current[c]:
                        last[c] = current[c]
            else:
                merged_sub.append(list(current))
        grid = [grid[0]] + merged_sub + grid[header_row_count:]

    # --- 3.6단계: 희소 데이터 행 병합 ---
    # 비어있지 않은 셀이 매우 적은 행(예: "16 Core"만 있는 행)을
    # 바로 위 행에 병합한다 (겹치지 않는 경우에만).
    sparse_threshold = max(1, max_cols // 3)
    merged_grid = [grid[0]]  # 첫 행(헤더)은 유지
    for r_idx in range(1, len(grid)):
        row = grid[r_idx]
        non_empty = sum(1 for c in row if c.strip())
        if non_empty <= sparse_threshold and non_empty > 0 and merged_grid:
            prev = merged_grid[-1]
            # 겹치는 셀이 없으면 합치기
            can_merge = all(
                not (prev[c].strip() and row[c].strip()) for c in range(max_cols)
            )
            if can_merge:
                for c in range(max_cols):
                    if row[c].strip():
                        prev[c] = row[c]
                continue
        merged_grid.append(row)
    grid = merged_grid

    # --- 4단계: 마크다운 테이블 생성 ---
    # 표준 마크다운: 구분선은 반드시 첫 행 바로 다음에 위치해야 렌더링됨
    lines = []

    # 첫 행 (헤더)
    lines.append("| " + " | ".join(grid[0]) + " |")

    # 구분선 (반드시 2번째 줄)
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")

    # 나머지 행 (다중 헤더의 하위 행 + 데이터 행)
    for row in grid[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _layout_table_to_text(rows) -> str:
    """HWP 비주얼 레이아웃 테이블(조직도 등)을 일반 텍스트로 변환한다.

    HWP는 조직도/다이어그램을 수백 개의 작은 셀로 구성된 레이아웃 테이블로 표현한다.
    이런 테이블은 마크다운 테이블로 변환하면 읽을 수 없으므로 텍스트로 추출한다.

    고스트 셀 감지:
      HWP가 생성하는 레이아웃 테이블에서 colspan=1인 셀에 모든 텍스트가
      합쳐져 들어가는 경우가 있다. 이를 고스트 셀이라 하고, 다른 셀 텍스트를
      3개 이상 포함하면 건너뛴다.
    """
    seen_texts = set()
    lines = []

    for tr in rows:
        cells = tr.find_all(["td", "th"])

        # 셀 데이터 수집: (텍스트, colspan)
        normal_parts = []   # colspan > 1인 일반 셀
        ghost_candidates = []  # colspan == 1인 후보 셀

        for cell in cells:
            text = cell.get_text(strip=True)
            if not text:
                continue
            cs = int(cell.get("colspan", 1))
            if cs > 1:
                normal_parts.append(text)
            else:
                ghost_candidates.append(text)

        # 고스트 셀 필터링: colspan=1 셀이 다른 셀 텍스트를 3개 이상 포함하면 건너뜀
        filtered_ghost = []
        for gt in ghost_candidates:
            if normal_parts:
                contained = sum(1 for nt in normal_parts if nt in gt)
                if contained >= 3:
                    continue  # 고스트 셀
            filtered_ghost.append(gt)

        # 중복 텍스트 제거 (이전 행에서 이미 출력된 텍스트)
        row_texts = []
        for text in filtered_ghost + normal_parts:
            if text not in seen_texts:
                row_texts.append(text)
                seen_texts.add(text)

        if row_texts:
            lines.append(" / ".join(row_texts))

    return "\n\n".join(lines)


def _try_split_cell(cell, colspan: int) -> list:
    """colspan > 1인 셀에서 큰 공백으로 구분된 텍스트를 분리한다.

    "업체명:          직책:          작성자 성명:        (서명)"
    → ["업체명:", "직책:", "작성자 성명:", "(서명)"]

    Returns:
        분리된 텍스트 리스트 (분리 불가능하면 빈 리스트)
    """
    if colspan <= 1:
        return []

    # 셀의 원본 텍스트를 공백 보존 상태로 추출
    raw_text = cell.get_text()
    # \xa0 (nbsp), \u3000 (전각 공백) → 일반 공백으로 통일
    raw_text = raw_text.replace("\xa0", " ").replace("\u3000", " ")
    raw_text = raw_text.replace("\n", " ").replace("\r", "")
    raw_text = raw_text.strip()

    if not raw_text:
        return []

    # 3개 이상의 연속 공백으로 분리
    parts = re.split(r" {3,}", raw_text)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        return []

    # 파이프 문자 이스케이프
    parts = [p.replace("|", "\\|") for p in parts]

    return parts


def _extract_cell_text(cell, bg_map: dict = None) -> str:
    """<td>/<th> 요소에서 텍스트를 추출한다.

    - 내부의 여러 <p> 태그를 <br>로 연결하여 셀 내 줄바꿈을 유지한다.
    - 파이프 문자(|)를 이스케이프한다.
    - 줄바꿈을 공백으로 치환한다.
    - 빈 셀에 배경색이 있으면 ■ 로 표시한다 (일정표 등).
    """
    paragraphs = cell.find_all("p")
    if paragraphs:
        parts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text:
                parts.append(text)
        # 여러 문단이면 <br>로 연결 (마크다운 테이블 셀 내 줄바꿈)
        cell_text = "<br>".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
    else:
        cell_text = cell.get_text(strip=True)

    # 줄바꿈과 불필요한 공백 정리
    cell_text = cell_text.replace("\n", " ").replace("\r", "")
    cell_text = re.sub(r"(?<!<br)(?<=>)\s+|\s+(?=<br>)", " ", cell_text)
    cell_text = re.sub(r"  +", " ", cell_text).strip()

    # 빈 셀인데 배경색이 있으면 색상별 이모지 표시 (일정표, 간트 차트 등)
    if not cell_text and bg_map:
        skip_colors = {"#ffffff", "#fff"}
        cls_list = cell.get("class", [])
        for c in cls_list:
            if c in bg_map and bg_map[c] not in skip_colors:
                cell_text = hex_to_color_marker(bg_map[c])
                break

    # 파이프 문자 이스케이프
    cell_text = cell_text.replace("|", "\\|")

    return cell_text


def _postprocess(text: str) -> str:
    """변환된 Markdown을 정리한다."""
    # XML/XHTML 선언 제거 (hwp5html 출력 고유)
    text = re.sub(r'<\?xml[^?]*\?>', '', text)
    text = re.sub(
        r'^\s*xml version=["\'][^"\']*["\'] encoding=["\'][^"\']*["\']\??',
        '', text, flags=re.IGNORECASE,
    )

    # DOCTYPE 및 HTML 태그 잔여물 제거
    text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(
        r'</?(?:html|head|body|meta|link|title)[^>]*>',
        '', text, flags=re.IGNORECASE,
    )

    # 공통 후처리: 헤딩 추가 + nbsp/빈줄 정리
    text = postprocess_headings(text)
    return postprocess_cleanup(text)
