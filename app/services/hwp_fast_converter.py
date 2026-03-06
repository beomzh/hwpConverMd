"""HWP 고속 변환기 — pyhwp XML 직접 파싱 방식

hwp5html(XSLT 변환)을 건너뛰고 pyhwp의 내부 XML 모델을 직접 파싱하여
Markdown으로 변환한다. 대용량 HWP 파일에서 10배 이상 빠르다.

구조:
    HWP (OLE2) → pyhwp xmlevents → XML → ElementTree → Markdown

기존 hwp5html 방식:
    HWP (OLE2) → hwp5html (XSLT) → HTML → BeautifulSoup → markdownify → Markdown
    ↑ XSLT 단계가 O(n²) 이상으로 대용량 파일에서 5분+ 소요

pyhwp 내부 XML 구조:
    <HwpDoc>
      <DocInfo>
        <CharShape bold="0" italic="0" basesize="1100" .../>
        <ParaShape align="center" .../>
        <BorderFill>
          <FillColorPattern background-color="#dcdcdc"/>
        </BorderFill>
      </DocInfo>
      <BodyText>
        <Section>
          <Paragraph parashape-id="5" style-id="0">
            <Text charshape-id="13" lang="ko">텍스트</Text>
            <ControlChar name="PARAGRAPH_BREAK"/>
            <TableControl>
              <TableBody rows="5" cols="8">
                <TableRow>
                  <TableCell col="0" row="0" colspan="1" rowspan="3"
                             borderfill-id="14">
                    <Paragraph>
                      <Text>셀 내용</Text>
                    </Paragraph>
                  </TableCell>
                </TableRow>
              </TableBody>
            </TableControl>
          </Paragraph>
        </Section>
      </BodyText>
    </HwpDoc>
"""

import io
import logging
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path

from app.core.exceptions import HwpConversionError


@contextmanager
def _suppress_stderr():
    """pyhwp의 'undefined XXXStyle value' 등 stderr print 경고를 억제한다."""
    with open(os.devnull, "w") as devnull:
        old_stderr = sys.stderr
        try:
            sys.stderr = devnull
            yield
        finally:
            sys.stderr = old_stderr

logger = logging.getLogger(__name__)


class HwpFastConverter:
    """pyhwp XML 직접 파싱으로 HWP를 Markdown으로 고속 변환한다."""

    @staticmethod
    def convert(hwp_path: str) -> str:
        """HWP 파일을 Markdown 문자열로 변환한다.

        Raises:
            HwpConversionError: 변환 실패 시
        """
        file_size = Path(hwp_path).stat().st_size
        file_size_mb = round(file_size / (1024 * 1024), 1)
        logger.info(f"HWP 고속 변환 시작: {hwp_path} ({file_size_mb}MB)")

        t0 = time.monotonic()

        # 1단계: pyhwp로 XML 덤프 (XSLT 없이 내부 모델 직접 출력)
        try:
            from hwp5.xmlmodel import Hwp5File
        except ImportError:
            raise HwpConversionError(
                "pyhwp가 설치되지 않았습니다: pip install pyhwp"
            )

        try:
            with _suppress_stderr():
                hwpfile = Hwp5File(hwp_path)
        except Exception as e:
            raise HwpConversionError(f"HWP 파일 열기 실패: {e}")

        t1 = time.monotonic()

        # XML 바이트 덤프
        try:
            xml_buf = io.BytesIO()
            with _suppress_stderr():
                hwpfile.xmlevents(embedbin=False).dump(xml_buf)
            xml_data = xml_buf.getvalue()
        except Exception as e:
            raise HwpConversionError(f"HWP XML 덤프 실패: {e}")

        t2 = time.monotonic()
        logger.info(
            f"HWP 고속 변환 — 파일 열기: {t1-t0:.2f}초, "
            f"XML 덤프: {t2-t1:.2f}초 ({len(xml_data)} bytes)"
        )

        # 2단계: XML 파싱
        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as e:
            raise HwpConversionError(f"HWP XML 파싱 실패: {e}")

        t3 = time.monotonic()

        # 3단계: DocInfo에서 CharShape/ParaShape/BorderFill 맵 구축
        charshapes = _load_charshapes(root)
        parashapes = _load_parashapes(root)
        border_fills = _load_border_fills(root)

        # 4단계: BodyText → Markdown 변환
        md_parts = []
        for body in root.iter("BodyText"):
            _walk_body(body, charshapes, parashapes, border_fills, md_parts)

        result = "\n\n".join(part for part in md_parts if part)
        result = _postprocess(result)

        t4 = time.monotonic()
        logger.info(
            f"HWP 고속 변환 완료 — XML 파싱: {t3-t2:.2f}초, "
            f"MD 변환: {t4-t3:.2f}초, 총: {t4-t0:.2f}초, "
            f"출력: {len(result)} chars"
        )

        return result.strip()


# ─── DocInfo 로더 ─────────────────────────────────────────────────────────


def _load_charshapes(root) -> dict:
    """DocInfo에서 CharShape 정보를 로드한다.

    CharShape는 0-based 인덱스로 참조된다.
    <Text charshape-id="N"> 의 N이 인덱스.

    Returns:
        {index: {"bold": bool, "italic": bool, "basesize": int}}
    """
    charshapes = {}
    idx = 0
    for elem in root.iter("CharShape"):
        charshapes[str(idx)] = {
            "bold": elem.get("bold", "0") == "1",
            "italic": elem.get("italic", "0") == "1",
            "basesize": int(elem.get("basesize", "1000")),
        }
        idx += 1
    return charshapes


def _load_parashapes(root) -> dict:
    """DocInfo에서 ParaShape 정보를 로드한다.

    Returns:
        {index: {"align": str}}
    """
    parashapes = {}
    idx = 0
    for elem in root.iter("ParaShape"):
        parashapes[str(idx)] = {
            "align": elem.get("align", "left"),
        }
        idx += 1
    return parashapes


def _load_border_fills(root) -> dict:
    """DocInfo에서 BorderFill의 배경색 정보를 로드한다.

    BorderFill은 1-based 인덱스로 참조된다.
    <TableCell borderfill-id="N"> 의 N이 인덱스.

    Returns:
        {borderfill_id: hex_color} (흰색 제외)
    """
    border_fills = {}
    skip_colors = {"#ffffff", "#fff", "none", ""}
    idx = 1  # 1-based
    for elem in root.iter("BorderFill"):
        for fcp in elem.iter("FillColorPattern"):
            bg = fcp.get("background-color", "")
            if bg.lower() not in skip_colors:
                border_fills[str(idx)] = bg
        idx += 1
    return border_fills


# ─── 본문 트리 탐색 ───────────────────────────────────────────────────────


def _walk_body(parent, charshapes, parashapes, border_fills, md_parts):
    """BodyText 트리를 재귀적으로 탐색하여 Markdown으로 변환한다.

    처리 규칙:
      - Paragraph: 텍스트 추출 (중첩 TableControl은 별도 처리)
      - TableControl: 테이블 변환
      - SectionDef, LineSeg 등 메타데이터: 건너뜀
      - 기타 컨테이너: 재귀 탐색
    """
    for child in parent:
        tag = child.tag

        if tag == "Paragraph":
            # 이 단락에 중첩된 TableControl이 있는지 확인
            nested_tables = list(_find_nested_tables(child))

            # 비-테이블 텍스트 추출
            para_md = _parse_paragraph(child, charshapes, parashapes)
            if para_md:
                md_parts.append(para_md)

            # 중첩된 테이블 처리
            for tbl_ctrl in nested_tables:
                table_md = _parse_table_control(tbl_ctrl, charshapes, border_fills)
                if table_md:
                    md_parts.append(table_md)

        elif tag == "TableControl":
            # 최상위에 직접 있는 TableControl (드물지만 가능)
            table_md = _parse_table_control(child, charshapes, border_fills)
            if table_md:
                md_parts.append(table_md)

        elif tag in ("TableBody", "TableRow", "TableCell"):
            # 테이블 내부 요소는 건너뜀 (이미 _parse_table_control에서 처리)
            pass

        elif tag in ("LineSeg", "ColumnsDef", "PageDef",
                      "FootnoteShape", "PageBorderFill",
                      "CharShapeIdxMap"):
            # 메타데이터 요소는 건너뜀
            pass

        else:
            # 컨테이너 요소 → 재귀
            _walk_body(child, charshapes, parashapes, border_fills, md_parts)


def _find_nested_tables(paragraph):
    """Paragraph 안에 중첩된 TableControl 요소들을 찾는다.

    TableControl 내부에 다시 중첩된 테이블은 반환하지 않음
    (그것은 _parse_table_control 내부에서 처리).
    """
    for child in paragraph:
        if child.tag == "TableControl":
            yield child
            # 내부로 재귀하지 않음
        elif child.tag not in ("Text", "ControlChar", "CharShapeIdxMap"):
            # LineSeg 안에 TableControl이 있을 수 있으므로 재귀
            yield from _find_nested_tables(child)


# ─── 서식 병합 헬퍼 ───────────────────────────────────────────────────────


def _merge_and_format(segments, charshapes):
    """연속된 같은 서식(bold/italic)의 텍스트를 병합한 후 Markdown 마크업을 적용한다.

    HWP XML에서는 같은 단락 내에서도 글자마다 다른 CharShape를 가질 수 있다.
    예: <Text charshape-id="3">제안</Text><Text charshape-id="3">요청서</Text>
    이 둘을 각각 **제안****요청서** 로 감싸면 깨진 마크업이 된다.
    병합 후 **제안요청서** 로 올바르게 감싼다.

    Args:
        segments: [(text, charshape_id), ...]
        charshapes: CharShape 맵

    Returns:
        서식이 적용된 문자열
    """
    if not segments:
        return ""

    # 각 세그먼트의 bold/italic 상태 결정
    styled = []
    for text, cs_id in segments:
        cs = charshapes.get(cs_id, {})
        bold = cs.get("bold", False)
        italic = cs.get("italic", False)
        styled.append((text, bold, italic))

    # 연속된 같은 서식 상태의 텍스트를 병합
    merged = []
    for text, bold, italic in styled:
        if merged and merged[-1][1] == bold and merged[-1][2] == italic:
            merged[-1] = (merged[-1][0] + text, bold, italic)
        else:
            merged.append((text, bold, italic))

    # Markdown 마크업 적용 (공백은 마커 바깥으로 이동)
    parts = []
    for text, bold, italic in merged:
        stripped = text.strip()
        if not stripped:
            parts.append(text)  # 공백만 있는 세그먼트 → 그대로
            continue

        leading = text[:len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()):]

        if bold and italic:
            parts.append(f"{leading}***{stripped}***{trailing}")
        elif bold:
            parts.append(f"{leading}**{stripped}**{trailing}")
        elif italic:
            parts.append(f"{leading}*{stripped}*{trailing}")
        else:
            parts.append(text)

    return "".join(parts)


# ─── 단락 파싱 ────────────────────────────────────────────────────────────


def _parse_paragraph(para_elem, charshapes, parashapes):
    """Paragraph 요소를 Markdown 문자열로 변환한다.

    중첩 TableControl 내부의 텍스트는 건너뛴다.
    """
    # 테이블 내 자손 수집 (skip set)
    skip_elems = set()
    for desc in para_elem.iter():
        if desc.tag == "TableControl":
            for tbl_desc in desc.iter():
                skip_elems.add(tbl_desc)

    # (text, charshape_id) 세그먼트 수집
    segments = []
    for desc in para_elem.iter():
        if desc in skip_elems:
            continue
        if desc.tag == "Text" and desc.text:
            segments.append((desc.text, desc.get("charshape-id", "")))

    # 연속 같은 서식 병합 후 마크업 적용
    full_text = _merge_and_format(segments, charshapes)

    if not full_text.strip():
        return ""

    # 제목 레벨 감지는 _postprocess에서 번호 기반으로 처리
    return full_text.strip()


# ─── 테이블 파싱 ──────────────────────────────────────────────────────────


def _parse_table_control(table_ctrl, charshapes, border_fills):
    """TableControl 요소를 Markdown 테이블로 변환한다."""
    # TableBody 찾기
    table_body = None
    for child in table_ctrl:
        if child.tag == "TableBody":
            table_body = child
            break

    if table_body is None:
        # TableBody를 iter로 찾기 (깊이가 더 있을 수 있음)
        for elem in table_ctrl.iter("TableBody"):
            table_body = elem
            break

    if table_body is None:
        return ""

    declared_rows = int(table_body.get("rows", "0"))
    declared_cols = int(table_body.get("cols", "0"))

    # 모든 TableCell 수집 (TableRow > TableCell 직접 자식만)
    all_cells = []
    for child in table_body:
        if child.tag == "TableRow":
            for tc in child:
                if tc.tag == "TableCell":
                    all_cells.append(tc)

    if not all_cells:
        return ""

    # 셀 데이터 추출
    cell_data = []
    max_col = 0
    max_row = 0

    for tc in all_cells:
        col = int(tc.get("col", "0"))
        row = int(tc.get("row", "0"))
        colspan = int(tc.get("colspan", "1"))
        rowspan = int(tc.get("rowspan", "1"))
        bf_id = tc.get("borderfill-id", "")

        cell_text = _extract_cell_text(tc, charshapes)

        # 빈 셀에 배경색이 있으면 색상 마커 표시
        if not cell_text.strip() and bf_id in border_fills:
            cell_text = _hex_to_color_marker(border_fills[bf_id])

        cell_data.append({
            "col": col,
            "row": row,
            "col_span": colspan,
            "row_span": rowspan,
            "text": cell_text,
        })

        max_col = max(max_col, col + colspan)
        max_row = max(max_row, row + rowspan)

    num_cols = max(declared_cols, max_col)
    num_rows = max(declared_rows, max_row)

    if num_cols == 0 or num_rows == 0:
        return ""

    # --- 1열 테이블 → 일반 텍스트 ---
    if num_cols == 1:
        lines = []
        for cell in cell_data:
            text = cell["text"].strip()
            if text:
                text = text.replace("\n", "\n\n")
                lines.append(text)
        return "\n\n".join(lines)

    # --- 레이아웃 테이블 (20열+) → 텍스트 ---
    if num_cols >= 20:
        return _layout_table_to_text(cell_data)

    # --- 2D 그리드 구축 ---
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
    grid = _merge_sparse_rows(grid, num_cols)

    if not grid:
        return ""

    # --- 열 수 통일 ---
    actual_cols = max(len(row) for row in grid)
    for row in grid:
        while len(row) < actual_cols:
            row.append("")

    # --- 파이프 이스케이프 & 줄바꿈 → <br> ---
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


def _collect_cell_paragraphs(parent):
    """TableCell 내부에서 모든 Paragraph 요소를 수집한다.

    HWP5에서 TableCell 구조:
      - TableCell > Paragraph              (일반)
      - TableCell > ColumnSet > Paragraph  (다단 레이아웃)

    직접 자식 Paragraph와 ColumnSet 등 컨테이너 내부의 Paragraph를
    모두 재귀적으로 찾아 반환한다.
    TableControl 내부로는 재귀하지 않음 (Paragraph 내에서 별도 처리).
    """
    for child in parent:
        if child.tag == "Paragraph":
            yield child
        elif child.tag in ("TableControl", "Text", "ControlChar",
                            "LineSeg", "CharShapeIdxMap"):
            pass  # 리프/메타데이터 요소 → 건너뜀
        else:
            # ColumnSet 등 컨테이너 → 재귀
            yield from _collect_cell_paragraphs(child)


def _extract_cell_text(tc_elem, charshapes) -> str:
    """TableCell 요소에서 텍스트를 추출한다.

    HWP5 XML에서 TableCell은 Paragraph를 직접 자식으로 가지거나,
    ColumnSet 등의 컨테이너 내부에 Paragraph를 포함할 수 있다.
    여러 Paragraph는 \\n으로 연결 (테이블에서 <br>로 변환됨).
    중첩 테이블이 있으면 텍스트로 플래튼한다.
    """
    paragraphs = []

    for child in _collect_cell_paragraphs(tc_elem):
        # 중첩 테이블 확인
        skip_elems = set()
        nested_tbls = []
        for desc in child.iter():
            if desc.tag == "TableControl":
                nested_tbls.append(desc)
                for td in desc.iter():
                    skip_elems.add(td)

        # 테이블 제외 텍스트 추출 (서식 병합)
        segments = []
        for desc in child.iter():
            if desc in skip_elems:
                continue
            if desc.tag == "Text" and desc.text:
                segments.append((desc.text, desc.get("charshape-id", "")))

        text = _merge_and_format(segments, charshapes)
        if text.strip():
            paragraphs.append(text.strip())

        # 중첩 테이블 플래튼
        for tbl_ctrl in nested_tbls:
            flat = _flatten_nested_table(tbl_ctrl, charshapes)
            if flat.strip():
                paragraphs.append(flat.strip())

    if not paragraphs:
        return ""

    if len(paragraphs) == 1:
        return paragraphs[0]

    # 결합 방식 결정 (hwpx_converter와 동일 로직)
    total_len = sum(len(p) for p in paragraphs)
    if total_len <= 30:
        return " ".join(paragraphs)
    else:
        return "\n".join(paragraphs)


def _flatten_nested_table(tbl_ctrl, charshapes) -> str:
    """중첩 TableControl을 읽기 좋은 텍스트로 변환한다."""
    rows = []
    for table_body in tbl_ctrl.iter("TableBody"):
        for table_row in table_body:
            if table_row.tag != "TableRow":
                continue
            cells = []
            for tc in table_row:
                if tc.tag == "TableCell":
                    text = _extract_cell_text(tc, charshapes).strip()
                    cells.append(text)
            rows.append(cells)

    # 빈 행 제거
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""

    # 열 수 통일
    max_cols = max(len(r) for r in rows) if rows else 0
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    if len(rows) == 1:
        non_empty = [c for c in rows[0] if c.strip()]
        return " / ".join(non_empty) if non_empty else ""

    if max_cols <= 1:
        return "\n".join(c.strip() for r in rows for c in r if c.strip())

    # 헤더 판단
    first_row = rows[0]
    data_rows = rows[1:]
    clean_first = [_strip_pua(c) for c in first_row]
    non_empty_first = [c for c in clean_first if c]
    all_short = all(len(c) <= 30 for c in clean_first)
    has_enough_cols = len(non_empty_first) >= 2

    if all_short and has_enough_cols:
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
        result_lines = []
        for row in rows:
            non_empty = [_strip_pua(c) for c in row if _strip_pua(c)]
            if non_empty:
                result_lines.append(" / ".join(non_empty))
        return "\n".join(result_lines) if result_lines else ""


# ─── 테이블 후처리 ────────────────────────────────────────────────────────


def _merge_sparse_rows(grid, num_cols):
    """비어있지 않은 셀이 매우 적은 행을 위 행에 병합한다.

    rowspan으로 인해 빈 셀이 많은 행에서 발생하는 문제를 해결한다.
    (hwpx_converter._merge_sparse_rows와 동일 로직)
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


def _layout_table_to_text(cell_data):
    """레이아웃 테이블(20열+)을 텍스트로 변환한다.

    (hwpx_converter._layout_table_to_text와 동일 로직)
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


# ─── 유틸리티 ─────────────────────────────────────────────────────────────


def _strip_pua(text: str) -> str:
    """Private Use Area (U+E000-U+F8FF) 등 비표시 문자를 제거한다."""
    return re.sub(r'[\uE000-\uF8FF]', '', text).strip()


def _hex_to_color_marker(hex_color: str) -> str:
    """hex 색상 코드를 가장 가까운 색상 마커로 변환한다.

    (hwpx_converter._hex_to_color_marker와 동일 로직)
    """
    hex_color = hex_color.lstrip("#").lower()
    if len(hex_color) == 8:
        hex_color = hex_color[2:]  # ARGB → RGB
    if len(hex_color) != 6:
        return "■"
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)

    if abs(r - g) < 20 and abs(g - b) < 20 and abs(r - b) < 20:
        avg = (r + g + b) // 3
        if avg < 80:
            return "⬛"
        return "■"

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


# ─── 후처리 ───────────────────────────────────────────────────────────────


def _postprocess(text: str) -> str:
    """변환된 Markdown을 정리한다.

    (hwp_converter._postprocess 및 hwpx_converter._postprocess와 동일 로직)
    """
    # 유효하지 않은 공백 문자 제거
    text = text.replace('\xa0', ' ')

    # --- Bold 마크업 정리 ---
    # 1단계: 연속 **** 제거 — **text1****text2** → **text1text2**
    while '****' in text:
        text = text.replace('****', '')

    # 2단계: 볼드 내부 선행/후행 공백 교정 & 빈 볼드 제거
    #   ** text**  → (공백)**text**   선행 공백을 마커 바깥으로
    #   **text **  → **text**(공백)   후행 공백을 마커 바깥으로
    #   **   **    → (공백)           공백만 감싼 볼드 제거
    def _fix_bold(m):
        inner = m.group(1)
        stripped = inner.strip()
        if not stripped:
            return ' ' if inner else ''
        leading = inner[:len(inner) - len(inner.lstrip())]
        trailing = inner[len(inner.rstrip()):]
        return f'{leading}**{stripped}**{trailing}'

    text = re.sub(r'\*\*((?:(?!\*\*).){1,200}?)\*\*', _fix_bold, text)

    # 3단계: 위 처리로 재발생 가능한 **** 및 빈 볼드 재정리
    while '****' in text:
        text = text.replace('****', '')
    text = re.sub(r'\*\*\s*\*\*', ' ', text)

    # 4단계: 짝이 없는 stray ** 제거 (줄 단위, 테이블 제외)
    #   목차 등 ** 마커 과다한 줄 → 모든 ** 제거
    #   추진배경** 3       → 추진배경 3        (줄 중간 stray **)
    #   3**. 제안서         → 3. 제안서          (번호 사이 stray **)
    #   *(**점)*            → *(점)*             (이탤릭 내부 stray **)
    cleaned_lines = []
    for line in text.split('\n'):
        if '|' in line or '**' not in line:
            cleaned_lines.append(line)
            continue
        star_count = line.count('**')
        if star_count > 8:
            # ** 마커가 과다한 줄 (목차 등) → 모든 ** 제거
            cleaned_lines.append(line.replace('**', ''))
            continue
        # 유효한 **...** 쌍의 위치를 수집
        valid = set()
        for m in re.finditer(
            r'\*\*((?:(?!\*\*).){1,200}?)\*\*', line
        ):
            valid.update(range(m.start(), m.start() + 2))
            valid.update(range(m.end() - 2, m.end()))
        # 유효하지 않은 ** 제거
        new_chars = []
        i = 0
        while i < len(line):
            if (i + 1 < len(line)
                    and line[i] == '*' and line[i + 1] == '*'
                    and i not in valid):
                i += 2  # stray ** 건너뜀
            else:
                new_chars.append(line[i])
                i += 1
        cleaned_lines.append(''.join(new_chars))
    text = '\n'.join(cleaned_lines)

    # --- 목차(TOC) 줄 분리 ---
    # HWP에서 목차가 한 줄로 합쳐지는 경우 각 항목을 개별 줄로 분리
    #   "순    서Ⅰ. 사업 개요    1. 사업 개요1    2. 추진배경2" →
    #     순    서
    #     Ⅰ. 사업 개요
    #     1. 사업 개요1
    #     2. 추진배경2
    _ROMAN = 'Ⅰ-Ⅹⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ'
    _CIRCLED_NUMS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳' \
                    '➀➁➂➃➄➅➆➇➈➉' \
                    '❶❷❸❹❺❻❼❽❾❿' \
                    '➊➋➌➍➎➏➐➑➒➓'

    def _is_toc_line(line: str) -> bool:
        """목차 줄인지 판별한다 (번호 항목 3개 이상 또는 로마숫자 2개 이상)."""
        # ** 제거 후 분석 (볼드 마커가 판별을 방해하지 않도록)
        s = line.replace('**', '').strip()
        if not s or '|' in s:
            return False
        # 로마숫자 구분자 개수
        roman_cnt = len(re.findall(rf'[{_ROMAN}]+\.', s))
        if roman_cnt >= 2:
            return True
        # 숫자 번호 항목 개수 (N. 형태)
        num_cnt = len(re.findall(r'(?:^|\s)\d+\.(?:\d+\.)*\s', s))
        if num_cnt >= 3:
            return True
        # 로마숫자 1개 + 숫자 번호 2개 이상
        if roman_cnt >= 1 and num_cnt >= 2:
            return True
        # 원문자 항목 2개 이상 + 숫자 번호
        circled_cnt = sum(1 for ch in s if ch in _CIRCLED_NUMS)
        if circled_cnt >= 2 and num_cnt >= 1:
            return True
        return False

    def _split_toc_line(line: str) -> str:
        """목차 줄을 개별 항목 줄로 분리한다.

        TOC 줄의 **를 먼저 제거한 뒤 분리한다
        (목차에서 볼드는 의미 없으며, ** 가 분리 패턴 매칭을 방해).
        """
        line = line.replace('**', '')
        # '순서' / '순    서' 뒤에 바로 로마숫자가 오면 분리
        line = re.sub(
            rf'(순\s*서)\s*([{_ROMAN}])',
            r'\1\n\2',
            line,
        )
        # 로마숫자 섹션 앞에서 분리 (페이지번호 뒤 공백 1개 이상)
        line = re.sub(
            rf'(\d)\s+([{_ROMAN}]+\.)',
            r'\1\n\2',
            line,
        )
        # 로마숫자 섹션 앞에서 분리 (한글/문자 뒤 공백 2개 이상)
        line = re.sub(
            rf'([가-힣a-zA-Z)）])\s{{2,}}([{_ROMAN}]+\.)',
            r'\1\n\2',
            line,
        )
        # 숫자 항목 앞에서 분리: 페이지번호/한글/문자 + 공백 2개 이상 + 번호
        line = re.sub(
            r'([\d가-힣a-zA-Z)）])\s{2,}(\d+\.\s)',
            r'\1\n\2',
            line,
        )
        # 원문자 항목 앞에서 분리: 공백 2개 이상 + 원문자
        line = re.sub(
            rf'(\S)\s{{2,}}([{_CIRCLED_NUMS}])',
            r'\1\n\2',
            line,
        )
        return line

    toc_lines = []
    for line in text.split('\n'):
        if _is_toc_line(line):
            toc_lines.append(_split_toc_line(line))
        else:
            toc_lines.append(line)
    text = '\n'.join(toc_lines)

    # --- 번호 기반 제목/소제목 헤딩 추가 ---
    heading_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if '|' in stripped or stripped.startswith('#'):
            heading_lines.append(line)
            continue
        # 3단계: N.N.N 형식
        if re.match(r'^\d+\.\d+\.\d+\.?\s+\S', stripped):
            heading_lines.append(f'#### {stripped}')
        # 2단계: N.N 형식
        elif re.match(r'^\d+\.\d+\.?\s+\S', stripped):
            heading_lines.append(f'### {stripped}')
        # 1단계: N. 형식
        elif re.match(r'^\d+\.\s+\S', stripped):
            heading_lines.append(f'## {stripped}')
        else:
            heading_lines.append(line)
    text = '\n'.join(heading_lines)

    # 과도한 빈 줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
