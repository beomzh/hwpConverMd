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

                section_files = sorted(
                    [n for n in zf.namelist()
                     if re.match(r"Contents/section\d+\.xml", n, re.IGNORECASE)]
                )
                if not section_files:
                    raise HwpxParsingError("HWPX 파일에서 section 파일을 찾을 수 없습니다.")

                md_parts = []
                for section_file in section_files:
                    xml_data = zf.read(section_file)
                    section_md = HwpxConverter._parse_section(xml_data, styles)
                    if section_md.strip():
                        md_parts.append(section_md)

                return "\n\n".join(md_parts).strip()

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
    def _parse_section(xml_data: bytes, styles: dict) -> str:
        """section XML을 파싱하여 Markdown 문자열로 변환한다."""
        root = ET.fromstring(xml_data)
        md_lines = []

        for elem in root.iter():
            tag_local = _local_tag(elem.tag)

            if tag_local == "tbl":
                table_md = HwpxConverter._parse_table(elem)
                if table_md:
                    md_lines.append(table_md)
                continue

            if tag_local == "p":
                if _is_inside_table(elem, root):
                    continue

                para_md = HwpxConverter._parse_paragraph(elem, styles)
                md_lines.append(para_md)

        return "\n\n".join(md_lines)

    @staticmethod
    def _parse_paragraph(para_elem, styles: dict) -> str:
        """단락 요소를 Markdown 문자열로 변환한다."""
        heading_level = 0
        style_id = para_elem.get("paraPrId") or para_elem.get("styleIDRef") or ""
        if style_id in styles:
            heading_level = styles[style_id]

        text_parts = []
        for child in para_elem.iter():
            tag_local = _local_tag(child.tag)

            if tag_local == "t" and child.text:
                run_elem = _find_parent_run(child, para_elem)
                text = child.text

                if run_elem is not None:
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
    def _parse_table(table_elem) -> str:
        """테이블 요소를 Markdown 테이블 문자열로 변환한다."""
        rows = []

        for child in table_elem.iter():
            tag_local = _local_tag(child.tag)

            if tag_local == "tr":
                cells = []
                for tc in child:
                    if _local_tag(tc.tag) == "tc":
                        cell_text = _extract_all_text(tc)
                        cell_text = cell_text.replace("|", "\\|")
                        cells.append(cell_text.strip())
                if cells:
                    rows.append(cells)

        if not rows:
            return ""

        max_cols = max(len(row) for row in rows)
        for row in rows:
            while len(row) < max_cols:
                row.append("")

        lines = []
        lines.append("| " + " | ".join(rows[0]) + " |")
        lines.append("| " + " | ".join(["---"] * max_cols) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)


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


def _is_inside_table(p_elem, root) -> bool:
    """단락이 테이블 셀 내부에 있는지 확인한다."""
    parent_map = {child: parent for parent in root.iter() for child in parent}
    current = p_elem
    while current in parent_map:
        current = parent_map[current]
        if _local_tag(current.tag) in ("tc", "tbl"):
            return True
    return False
