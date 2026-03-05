import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.exceptions import HwpxParsingError


class HwpxConverter:
    """HWPX(OWPML) 파일을 Markdown으로 변환한다.

    HWPX는 ZIP 아카이브로 내부에 XML 파일들을 포함한다.
    주요 구조:
        Contents/header.xml   - 문서 스타일 정의
        Contents/section0.xml - 본문 내용 (section1.xml, section2.xml ...)
        BinData/              - 이미지 등 바이너리 데이터

    HWPX 테이블 구조:
        <tbl colCnt rowCnt>
          <tr>
            <tc>
              <cellAddr colAddr="0" rowAddr="0"/>  ← 0-based 그리드 위치
              <cellSpan colSpan="1" rowSpan="1"/>  ← 병합 범위
              <subList>
                <p><run><t>셀 텍스트</t></run></p>
              </subList>
            </tc>
          </tr>
        </tbl>
    병합(rowSpan/colSpan > 1)된 셀은 시작 위치에만 존재하고,
    이후 행/열에는 해당 <tc>가 생략된다.
    """

    HEADING_STYLE_PATTERNS = {
        "개요 1": 1, "개요 2": 2, "개요 3": 3,
        "개요 4": 4, "개요 5": 5, "개요 6": 6, "개요 7": 7,
        "Outline 1": 1, "Outline 2": 2, "Outline 3": 3,
        "Outline 4": 4, "Outline 5": 5, "Outline 6": 6, "Outline 7": 7,
    }

    @staticmethod
    def convert(hwpx_path: str) -> str:
        """HWPX 파일을 Markdown 문자열로 변환한다."""
        try:
            with zipfile.ZipFile(hwpx_path, "r") as zf:
                styles = HwpxConverter._load_styles(zf)
                border_fills = HwpxConverter._load_border_fills(zf)

                section_files = sorted(
                    [n for n in zf.namelist()
                     if re.match(r"Contents/section\d+\.xml", n, re.IGNORECASE)]
                )
                if not section_files:
                    raise HwpxParsingError("HWPX 파일에서 section 파일을 찾을 수 없습니다.")

                md_parts = []
                for section_file in section_files:
                    xml_data = zf.read(section_file)
                    section_md = HwpxConverter._parse_section(
                        xml_data, styles, border_fills
                    )
                    if section_md.strip():
                        md_parts.append(section_md)

                result = "\n\n".join(md_parts).strip()
                return _postprocess(result)

        except zipfile.BadZipFile:
            raise HwpxParsingError("유효하지 않은 HWPX 파일입니다 (ZIP 형식 아님).")
        except ET.ParseError as e:
            raise HwpxParsingError(f"HWPX XML 파싱 실패: {e}")

    @staticmethod
    def _load_styles(zf: zipfile.ZipFile) -> dict:
        """header.xml에서 단락 스타일 정보를 로드한다."""
        styles = {}

        header_candidates = [
            n for n in zf.namelist()
            if re.match(r"Contents/header\.xml", n, re.IGNORECASE)
        ]
        if not header_candidates:
            return styles

        try:
            xml_data = zf.read(header_candidates[0])
            root = ET.fromstring(xml_data)
        except ET.ParseError:
            return styles

        for elem in root.iter():
            tag_local = _local_tag(elem.tag)

            if tag_local == "style":
                style_id = elem.get("id") or elem.get("paraPrIDRef")
                style_name = elem.get("name", "")
                if not style_name:
                    for child in elem:
                        if _local_tag(child.tag) == "name":
                            style_name = child.text or child.get("val", "")
                            break

                if style_id and style_name:
                    for pattern, level in HwpxConverter.HEADING_STYLE_PATTERNS.items():
                        if pattern in style_name:
                            styles[style_id] = level
                            break

                outline_level = elem.get("outlineLevel")
                if outline_level and style_id:
                    try:
                        level = int(outline_level)
                        if 1 <= level <= 7:
                            styles[style_id] = level
                    except ValueError:
                        pass

        return styles

    @staticmethod
    def _load_border_fills(zf: zipfile.ZipFile) -> dict:
        """header.xml에서 borderFill의 배경색 정보를 로드한다.

        HWPX 셀의 배경색은 tc[@borderFillIDRef] → header.xml의
        borderFill → fillBrush → winBrush[@faceColor] 로 참조된다.

        간트차트 등에서 사용하는 해치 패턴(CROSS_DIAGONAL 등)도 지원한다.
        해치 패턴이 있으면 hatchColor를 색상으로 사용한다.

        Returns:
            {borderFillID: hex_color} 딕셔너리 (흰색/없음 제외)
        """
        border_fills = {}

        header_candidates = [
            n for n in zf.namelist()
            if re.match(r"Contents/header\.xml", n, re.IGNORECASE)
        ]
        if not header_candidates:
            return border_fills

        try:
            xml_data = zf.read(header_candidates[0])
            root = ET.fromstring(xml_data)
        except ET.ParseError:
            return border_fills

        skip_colors = {"#ffffff", "#fff", "none", ""}

        for elem in root.iter():
            if _local_tag(elem.tag) != "borderFill":
                continue

            bf_id = elem.get("id", "")
            if not bf_id:
                continue

            for child in elem:
                if _local_tag(child.tag) != "fillBrush":
                    continue
                for gc in child:
                    if _local_tag(gc.tag) == "winBrush":
                        face_color = gc.get("faceColor", "none")
                        hatch_style = gc.get("hatchStyle", "NONE")
                        hatch_color = gc.get("hatchColor", "none")

                        # 해치 패턴이 있으면 hatchColor를 우선 사용
                        # (간트차트에서 CROSS_DIAGONAL 등으로 활성 기간 표시)
                        if hatch_style not in ("NONE", "none", ""):
                            if hatch_color.lower() not in skip_colors:
                                border_fills[bf_id] = hatch_color
                                continue

                        # 일반 솔리드 배경색
                        if face_color.lower() not in skip_colors:
                            border_fills[bf_id] = face_color

        return border_fills

    @staticmethod
    def _parse_section(xml_data: bytes, styles: dict, border_fills: dict = None) -> str:
        """section XML을 파싱하여 Markdown 문자열로 변환한다.

        재귀적 트리 탐색으로 요소 순서를 유지하고 중복을 방지한다.
        기존의 root.iter() 방식은 테이블 내부 <p>를 중복 처리하는 문제가 있었다.
        """
        root = ET.fromstring(xml_data)
        md_lines = []
        _walk_elements(root, styles, md_lines, border_fills or {})
        return "\n\n".join(line for line in md_lines if line)

    @staticmethod
    def _parse_paragraph(para_elem, styles: dict) -> str:
        """단락 요소를 Markdown 문자열로 변환한다.

        <p> 안에 <tbl>이 중첩된 경우, 테이블 내부의 텍스트는 건너뛴다.
        (테이블은 _walk_elements에서 별도 처리됨)
        """
        heading_level = 0
        style_id = para_elem.get("paraPrId") or para_elem.get("styleIDRef") or ""
        if style_id in styles:
            heading_level = styles[style_id]

        # <p> 안에 중첩된 <tbl>의 모든 자손을 set으로 수집 → O(1) 판별
        skip_elems = set()
        for desc in para_elem.iter():
            if _local_tag(desc.tag) == "tbl":
                for tbl_desc in desc.iter():
                    skip_elems.add(tbl_desc)

        text_parts = []
        for child in para_elem.iter():
            if child in skip_elems:
                continue

            tag_local = _local_tag(child.tag)

            if tag_local == "t" and child.text:
                run_elem = _find_parent_run(child, para_elem)
                text = child.text

                if run_elem is not None and run_elem not in skip_elems:
                    bold, italic = _get_char_properties(run_elem)
                    if bold and italic:
                        text = f"***{text}***"
                    elif bold:
                        text = f"**{text}**"
                    elif italic:
                        text = f"*{text}*"

                text_parts.append(text)

            elif tag_local in ("img", "pic", "image"):
                bin_id = child.get("binaryItemIDRef") or child.get("id") or ""
                if bin_id:
                    text_parts.append(f"![image](BinData/{bin_id})")

        full_text = "".join(text_parts)

        if not full_text.strip():
            return ""

        if heading_level:
            return f"{'#' * heading_level} {full_text.strip()}"

        return full_text.strip()

    @staticmethod
    def _parse_table(table_elem, border_fills: dict = None) -> str:
        """테이블 요소를 Markdown 테이블 문자열로 변환한다.

        HWPX의 cellAddr/cellSpan을 사용하여 정확한 2D 그리드를 구축한다.
        rowspan/colspan을 올바르게 처리한다.
        1열 테이블은 일반 텍스트로, 레이아웃 테이블(20열+)도 텍스트로 변환한다.
        빈 셀에 배경색이 있으면 색상 마커로 표시한다 (일정표, 간트 차트 등).
        """
        border_fills = border_fills or {}
        # tbl 속성에서 행/열 수 가져오기
        declared_cols = int(table_elem.get("colCnt", "0"))
        declared_rows = int(table_elem.get("rowCnt", "0"))

        # 모든 tc 요소 수집 (tr > tc 직접 자식만)
        all_cells = []
        for child in table_elem:
            if _local_tag(child.tag) == "tr":
                for tc in child:
                    if _local_tag(tc.tag) == "tc":
                        all_cells.append(tc)

        if not all_cells:
            return ""

        # cellAddr와 cellSpan 정보 추출
        cell_data = []
        max_col = 0
        max_row = 0

        for tc in all_cells:
            col_addr = 0
            row_addr = 0
            col_span = 1
            row_span = 1

            for child in tc:
                ctag = _local_tag(child.tag)
                if ctag == "cellAddr":
                    col_addr = int(child.get("colAddr", "0"))
                    row_addr = int(child.get("rowAddr", "0"))
                elif ctag == "cellSpan":
                    col_span = int(child.get("colSpan", "1"))
                    row_span = int(child.get("rowSpan", "1"))

            cell_text = _extract_cell_text(tc)

            # 빈 셀에 배경색이 있으면 색상 마커 표시 (일정표, 간트 차트)
            if not cell_text.strip() and border_fills:
                bf_ref = tc.get("borderFillIDRef", "")
                if bf_ref in border_fills:
                    cell_text = _hex_to_color_marker(border_fills[bf_ref])

            cell_data.append({
                "col": col_addr,
                "row": row_addr,
                "col_span": col_span,
                "row_span": row_span,
                "text": cell_text,
            })

            max_col = max(max_col, col_addr + col_span)
            max_row = max(max_row, row_addr + row_span)

        num_cols = max(declared_cols, max_col)
        num_rows = max(declared_rows, max_row)

        if num_cols == 0 or num_rows == 0:
            return ""

        # --- 1열 테이블 → 일반 텍스트로 변환 ---
        # 목차, 요약 박스 등 1열짜리 테이블은 마크다운 테이블이 아닌 일반 텍스트로
        if num_cols == 1:
            lines = []
            for cell in cell_data:
                text = cell["text"].strip()
                if text:
                    # 1열 테이블은 일반 텍스트이므로 \n을 \n\n으로 변환 (마크다운 단락)
                    text = text.replace("\n", "\n\n")
                    lines.append(text)
            return "\n\n".join(lines)

        # --- 레이아웃 테이블 (20열+) → 텍스트 ---
        # HWP/HWPX의 조직도/다이어그램은 수십 개의 열로 구성된 레이아웃 테이블
        if num_cols >= 20:
            return _layout_table_to_text(cell_data)

        # --- 2D 그리드 구축 (cellAddr 기반 정확한 위치 배치) ---
        grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]

        for cell in cell_data:
            r, c = cell["row"], cell["col"]
            if r < num_rows and c < num_cols:
                grid[r][c] = cell["text"]

        # --- 빈 행 제거 ---
        grid = [row for row in grid if any(cell.strip() for cell in row)]

        if not grid:
            return ""

        # --- 희소 데이터 행 병합 ---
        # rowspan으로 인해 빈 셀이 많은 행을 위 행에 병합
        grid = _merge_sparse_rows(grid, num_cols)

        if not grid:
            return ""

        # --- 열 수 통일 ---
        actual_cols = max(len(row) for row in grid)
        for row in grid:
            while len(row) < actual_cols:
                row.append("")

        # --- 파이프 문자 이스케이프 & 줄바꿈 → <br> 변환 ---
        for row in grid:
            for i, cell in enumerate(row):
                row[i] = cell.replace("|", "\\|").replace("\n", "<br>").strip()

        # --- 마크다운 테이블 생성 ---
        lines = []
        lines.append("| " + " | ".join(grid[0]) + " |")
        lines.append("| " + " | ".join(["---"] * actual_cols) + " |")
        for row in grid[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)


# ─── Tree Walk (중복 방지) ─────────────────────────────────────────────────

def _walk_elements(parent, styles, md_lines, border_fills=None):
    """요소 트리를 재귀적으로 탐색하여 Markdown으로 변환한다.

    기존의 root.iter() + _is_inside_table() 방식 대신
    직접 자식만 처리하여 테이블 내부 <p>의 중복을 원천 차단한다.

    처리 규칙:
      - <p>: 단락 텍스트 추출 → 중첩된 <tbl>이 있으면 별도 처리
      - <tbl>: 테이블 변환
      - 기타 컨테이너: 재귀 탐색
      - <tr>, <tc>, <subList>: 테이블 내부이므로 건너뜀
    """
    border_fills = border_fills or {}
    for child in parent:
        tag = _local_tag(child.tag)

        if tag == "p":
            # 이 단락에 중첩된 테이블이 있는지 확인
            nested_tables = list(_find_nested_tables(child))

            # 비-테이블 텍스트 추출
            para_md = HwpxConverter._parse_paragraph(child, styles)
            if para_md:
                md_lines.append(para_md)

            # 중첩된 테이블 처리 (문서 순서대로)
            for tbl in nested_tables:
                table_md = HwpxConverter._parse_table(tbl, border_fills)
                if table_md:
                    md_lines.append(table_md)

        elif tag == "tbl":
            # 섹션 직접 자식으로 있는 테이블 (드물지만 가능)
            table_md = HwpxConverter._parse_table(child, border_fills)
            if table_md:
                md_lines.append(table_md)

        elif tag in ("tr", "tc", "subList"):
            # 테이블 내부 요소는 건너뛰기 (이미 _parse_table에서 처리)
            pass

        else:
            # 컨테이너 요소 (sec, body 등) → 재귀
            _walk_elements(child, styles, md_lines, border_fills)


def _find_nested_tables(elem):
    """요소 안에 직접/간접적으로 중첩된 <tbl> 요소들을 찾는다.

    tbl 내부에 다시 중첩된 테이블은 반환하지 않는다
    (그것은 _parse_table 내부에서 처리).
    """
    for child in elem:
        tag = _local_tag(child.tag)
        if tag == "tbl":
            yield child
            # tbl 내부로는 재귀하지 않음 (중첩 테이블은 _extract_cell_text에서 처리)
        else:
            yield from _find_nested_tables(child)


# ─── 셀 텍스트 추출 ─────────────────────────────────────────────────────────

def _extract_cell_text(tc_elem) -> str:
    """tc 요소에서 텍스트를 추출한다.

    subList 내의 여러 p 요소를 <br>로 연결한다 (마크다운 테이블 셀 내 줄바꿈).
    중첩 테이블이 있으면 텍스트로 플래튼한다.
    """
    paragraphs = []
    found_sublist = False

    for child in tc_elem:
        if _local_tag(child.tag) != "subList":
            continue
        found_sublist = True

        for p_elem in child:
            if _local_tag(p_elem.tag) != "p":
                continue

            # 중첩 테이블 확인
            skip_elems = set()
            nested_tbls = []
            for d in p_elem.iter():
                if _local_tag(d.tag) == "tbl":
                    nested_tbls.append(d)
                    for td in d.iter():
                        skip_elems.add(td)

            # 테이블 제외 텍스트 추출
            parts = []
            for d in p_elem.iter():
                if d in skip_elems:
                    continue
                if _local_tag(d.tag) == "t" and d.text:
                    parts.append(d.text)

            text = "".join(parts)
            if text.strip():
                paragraphs.append(text.strip())

            # 중첩 테이블을 텍스트로 플래튼
            for tbl in nested_tbls:
                flat = _flatten_nested_table(tbl)
                if flat.strip():
                    paragraphs.append(flat.strip())

    if not found_sublist:
        # Fallback: subList 없이 직접 텍스트가 있는 경우
        text = _extract_all_text(tc_elem)
        if text.strip():
            return text.strip()

    if not paragraphs:
        return ""

    if len(paragraphs) == 1:
        return paragraphs[0]

    # 여러 단락의 결합 방식 결정:
    #   - 총 글자수가 짧으면 (≤30자): 셀 폭이 좁아 줄바꿈된 것 → 공백으로 결합
    #     예) "민원정보" + "분석과" → "민원정보 분석과"
    #     예) "사업" + "책임자" → "사업 책임자"
    #   - 총 글자수가 길면: 의미 있는 별도 단락 → \n으로 결합 (테이블에서 <br> 변환)
    #     예) "□ 사업명: ..." + "□ 사업예산: ..." → 줄바꿈 유지
    total_len = sum(len(p) for p in paragraphs)
    if total_len <= 30:
        return " ".join(paragraphs)
    else:
        return "\n".join(paragraphs)


def _flatten_nested_table(tbl_elem) -> str:
    """중첩 테이블을 읽기 좋은 텍스트로 변환한다.

    개선 사항:
    - 각 행을 줄바꿈(\\n)으로 구분 (테이블 셀에서 <br>로 변환됨)
    - 첫 행이 헤더이면 데이터 행에 "헤더: 값" 형태로 레이블 추가
    - 기존의 " / " + " | " 한 줄 나열 대신 행 단위 줄바꿈으로 가독성 향상
    """
    rows = []
    for child in tbl_elem:
        if _local_tag(child.tag) != "tr":
            continue
        cells = []
        for tc in child:
            if _local_tag(tc.tag) == "tc":
                text = _extract_cell_text(tc).strip()
                cells.append(text)
        rows.append(cells)

    # 빈 행 제거
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""

    # 열 수 통일 (패딩)
    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    # --- 1행만 있으면 단순 연결 ---
    if len(rows) == 1:
        non_empty = [c for c in rows[0] if c.strip()]
        return " / ".join(non_empty) if non_empty else ""

    # --- 1열 테이블: 텍스트만 연결 ---
    if max_cols <= 1:
        return "\n".join(c.strip() for r in rows for c in r if c.strip())

    # --- 첫 행이 헤더인지 판단 ---
    first_row = rows[0]
    data_rows = rows[1:]

    # PUA(Private Use Area) 문자 제거 후 실제 텍스트 있는 셀만 카운트
    clean_first = [_strip_pua(c) for c in first_row]
    non_empty_first = [c for c in clean_first if c]
    all_short = all(len(c) <= 30 for c in clean_first)
    has_enough_cols = len(non_empty_first) >= 2

    if all_short and has_enough_cols:
        # 헤더 레이블 포맷: ▸ 헤더1: 값1, 헤더2: 값2
        headers = clean_first
        result_lines = []
        for row in data_rows:
            parts = []
            for i in range(max_cols):
                val = _strip_pua(row[i]) if i < len(row) else ""
                header = headers[i] if i < len(headers) else ""
                if not val:
                    continue
                if header:
                    parts.append(f"{header}: {val}")
                else:
                    parts.append(val)
            if parts:
                result_lines.append("▸ " + ", ".join(parts))
        return "\n".join(result_lines) if result_lines else ""
    else:
        # 헤더 없이 행별 줄바꿈 (기존보다 가독성 향상)
        result_lines = []
        for row in rows:
            non_empty = [_strip_pua(c) for c in row if _strip_pua(c)]
            if non_empty:
                result_lines.append(" / ".join(non_empty))
        return "\n".join(result_lines) if result_lines else ""


# ─── 기본 유틸리티 ──────────────────────────────────────────────────────────

def _local_tag(tag: str) -> str:
    """'{namespace}localname' 형태의 태그에서 localname만 추출한다."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_all_text(elem) -> str:
    """요소 하위의 모든 hp:t 텍스트를 추출한다."""
    parts = []
    for child in elem.iter():
        if _local_tag(child.tag) == "t" and child.text:
            parts.append(child.text)
    return "".join(parts)


def _strip_pua(text: str) -> str:
    """Private Use Area (U+E000-U+F8FF) 등 비표시 문자를 제거한다.

    HWP/HWPX 문서에서 Wingdings 등 특수 폰트 기호가
    PUA 코드포인트로 저장되어 빈 텍스트처럼 보이지만 문자열 비교에서
    truthy로 평가되는 문제를 방지한다.
    """
    return re.sub(r'[\uE000-\uF8FF]', '', text).strip()


def _find_parent_run(t_elem, para_elem):
    """t 요소의 부모 run 요소를 찾는다."""
    for run in para_elem.iter():
        if _local_tag(run.tag) == "run":
            for child in run.iter():
                if child is t_elem:
                    return run
    return None


def _get_char_properties(run_elem) -> tuple:
    """run 요소에서 bold/italic 속성을 확인한다."""
    bold = False
    italic = False

    for child in run_elem.iter():
        tag_local = _local_tag(child.tag)

        if tag_local == "rPr":
            for prop in child.iter():
                prop_tag = _local_tag(prop.tag)
                if prop_tag == "bold":
                    bold = True
                elif prop_tag == "italic":
                    italic = True

    return bold, italic


# ─── 테이블 후처리 ──────────────────────────────────────────────────────────

def _merge_sparse_rows(grid, num_cols):
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
            # 겹치는 셀이 없으면 합치기
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


def _layout_table_to_text(cell_data):
    """레이아웃 테이블(20열+)을 텍스트로 변환한다.

    조직도/다이어그램 등 수십 열의 레이아웃 테이블은
    마크다운 테이블로 변환하면 읽을 수 없으므로 텍스트로 추출한다.
    중복 텍스트는 제거한다.
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


# ─── 색상 마커 ─────────────────────────────────────────────────────────────

def _hex_to_color_marker(hex_color: str) -> str:
    """hex 색상 코드를 가장 가까운 색상 마커로 변환한다.

    진한 색 → 채워진 사각형 이모지 (🟦), 연한 색 → 한국어 색상명 ([하늘색]) 으로 구분.
    일정표·간트 차트 등에서 색칠된 빈 셀을 시각적으로 구분하기 위해 사용.
    (HWP 컨버터의 동일 함수와 일치)
    """
    hex_color = hex_color.lstrip("#").lower()
    if len(hex_color) == 8:
        # ARGB 형식 (#AARRGGBB) → RGB만 사용
        hex_color = hex_color[2:]
    if len(hex_color) != 6:
        return "■"
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)

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

    # Lightness (0.0 ~ 1.0)
    lightness = (max_c + min_c) / 510.0

    # Hue (0 ~ 360)
    if max_c == r:
        hue = 60 * (((g - b) / diff) % 6)
    elif max_c == g:
        hue = 60 * (((b - r) / diff) + 2)
    else:
        hue = 60 * (((r - g) / diff) + 4)

    is_light = lightness >= 0.65

    # 진한 색 → 사각형 이모지, 연한 색 → hex 코드
    if hue < 15 or hue >= 345:
        return "#FFC0CB" if is_light else "🟥"
    elif hue < 45:
        return "#F4A460" if is_light else "🟧"
    elif hue < 70:
        return "#FFD700" if is_light else "🟨"
    elif hue < 160:
        return "#90EE90" if is_light else "🟩"
    elif hue < 260:
        return "#87CEEB" if is_light else "🟦"
    elif hue < 310:
        return "#9370DB" if is_light else "🟪"
    else:
        return "#FF69B4" if is_light else "🟥"


# ─── 후처리 ─────────────────────────────────────────────────────────────────

def _postprocess(text: str) -> str:
    """변환된 Markdown을 정리한다."""
    # --- 번호 기반 제목/소제목 헤딩 추가 ---
    # "1.2.3 제목" → "#### 1.2.3 제목" (3단계)
    # "1.2 제목"   → "### 1.2 제목"   (2단계)
    # "1. 제목"    → "## 1. 제목"     (1단계)
    # 테이블 행(|)과 이미 # 마크가 있는 줄은 제외
    heading_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        # 테이블 행이거나 이미 헤딩인 줄은 건너뛰기
        if '|' in stripped or stripped.startswith('#'):
            heading_lines.append(line)
            continue
        # 3단계: N.N.N 형식 (예: 1.2.3 또는 1.2.3.)
        if re.match(r'^\d+\.\d+\.\d+\.?\s+\S', stripped):
            heading_lines.append(f'#### {stripped}')
        # 2단계: N.N 형식 (예: 1.2 또는 1.2.)
        elif re.match(r'^\d+\.\d+\.?\s+\S', stripped):
            heading_lines.append(f'### {stripped}')
        # 1단계: N. 형식 (예: 1. 또는 1.)
        elif re.match(r'^\d+\.\s+\S', stripped):
            heading_lines.append(f'## {stripped}')
        else:
            heading_lines.append(line)
    text = '\n'.join(heading_lines)

    # 과도한 빈 줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
