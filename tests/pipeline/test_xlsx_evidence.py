"""Synthetic tests for the bounded raw XLSX evidence reader.

Every fixture is assembled as a ZIP of hand-written OOXML text so the exact
lexical tokens under test survive into the archive. Writing these workbooks
through openpyxl would coerce the numbers to floats and destroy the very
evidence this module exists to preserve.
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

from finjuice.pipeline.ingest import xlsx_evidence
from finjuice.pipeline.ingest.xlsx_evidence import (
    EvidenceLimits,
    XlsxEvidenceError,
    XlsxEvidenceFormatError,
    XlsxEvidenceLimitError,
    XlsxEvidenceSecurityError,
    read_workbook_evidence,
)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
STRICT_MAIN_NS = "http://purl.oclc.org/ooxml/spreadsheetml/main"
STRICT_DOC_REL_NS = "http://purl.oclc.org/ooxml/officeDocument/relationships"
STRICT_PKG_REL_NS = "http://purl.oclc.org/ooxml/package/relationships"
FOREIGN_NS = "urn:example:not-ooxml"

ROOT_RELS = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{PKG_REL_NS}">
  <Relationship Id="rId1" Type="{DOC_REL_NS}/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook_xml(sheets: str, *, properties: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}">'
        f"{properties}<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels(entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">{entries}</Relationships>'
    )


def _sheet_xml(rows: str, *, dimension: str = "A1:D9") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{MAIN_NS}"><dimension ref="{dimension}"/>'
        f"<sheetData>{rows}</sheetData></worksheet>"
    )


def _zip_bytes(members: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


LEXEME_ROWS = (
    '<row r="1">'
    '<c r="A1" t="n"><v>1.234567890123456789e-400</v></c>'
    '<c r="B1"><v>123456789012345678901234567890.123456789</v></c>'
    '<c r="C1" s="4"><v>10.10</v></c>'
    '<c r="D1" t="s"><v>0</v></c>'
    "</row>"
    '<row r="2">'
    '<c r="A2"/>'
    '<c r="B2"><v></v></c>'
    '<c r="C2" t="inlineStr"><is><t></t></is></c>'
    '<c r="D2" t="s"><v>99</v></c>'
    "</row>"
    '<row r="3">'
    '<c r="A3" t="b"><v>0</v></c>'
    '<c r="B3" t="e"><v>#DIV/0!</v></c>'
    '<c r="C3"><f>SUM(A1:B1)</f><v>7</v></c>'
    '<c r="D3"><f t="shared" si="2" ref="D3:D4">A1*2</f></c>'
    "</row>"
    '<row r="4">'
    '<c r="A4" t="inlineStr"><is><r><rPr><b/></rPr><t>bold</t></r>'
    "<r><t> tail</t></r></is></c>"
    '<c r="B4" t="s"><v>1</v></c>'
    "</row>"
)

SHARED_STRINGS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<sst xmlns="{MAIN_NS}" count="2" uniqueCount="2">'
    "<si><t>plain shared</t></si>"
    "<si><r><rPr><i/></rPr><t>rich</t></r><r><t> shared</t></r></si>"
    "</sst>"
)


def _lexeme_workbook(*, properties: str = "") -> bytes:
    return _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml(
                '<sheet name="Ledger" sheetId="7" r:id="rIdA"/>', properties=properties
            ),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rIdS" Type="{DOC_REL_NS}/sharedStrings"'
                ' Target="sharedStrings.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml(LEXEME_ROWS),
            "xl/sharedStrings.xml": SHARED_STRINGS,
        }
    )


def test_extreme_numeric_lexemes_survive_without_float_conversion() -> None:
    evidence = read_workbook_evidence(_lexeme_workbook())

    sheet = evidence.sheet("Ledger")
    assert sheet is not None
    tiny = sheet.cell("A1")
    huge = sheet.cell("B1")
    scaled = sheet.cell("C1")
    assert tiny is not None and huge is not None and scaled is not None
    assert tiny.raw_value == "1.234567890123456789e-400"
    assert huge.raw_value == "123456789012345678901234567890.123456789"
    assert scaled.raw_value == "10.10"
    assert scaled.style_index == 4


def test_missing_empty_and_empty_inline_values_stay_distinguishable() -> None:
    sheet = read_workbook_evidence(_lexeme_workbook()).sheet("Ledger")

    assert sheet is not None
    missing = sheet.cell("A2")
    empty = sheet.cell("B2")
    inline_empty = sheet.cell("C2")
    assert missing is not None and empty is not None and inline_empty is not None
    assert (missing.value_state, missing.raw_value) == ("absent", None)
    assert (empty.value_state, empty.raw_value) == ("empty", "")
    assert inline_empty.value_state == "absent"
    assert inline_empty.inline_text is not None
    assert inline_empty.inline_text.plain_text == ""
    assert len(inline_empty.inline_text.runs) == 1


def test_boolean_and_error_cells_keep_their_raw_lexemes() -> None:
    sheet = read_workbook_evidence(_lexeme_workbook()).sheet("Ledger")

    assert sheet is not None
    boolean = sheet.cell("A3")
    error = sheet.cell("B3")
    assert boolean is not None and error is not None
    assert (boolean.cell_type, boolean.raw_value) == ("b", "0")
    assert (error.cell_type, error.raw_value) == ("e", "#DIV/0!")
    assert boolean.type_declared and error.type_declared


def test_formula_text_and_cached_value_are_captured_separately() -> None:
    sheet = read_workbook_evidence(_lexeme_workbook()).sheet("Ledger")

    assert sheet is not None
    cached = sheet.cell("C3")
    uncached = sheet.cell("D3")
    assert cached is not None and uncached is not None
    assert cached.formula is not None and cached.formula.text == "SUM(A1:B1)"
    assert (cached.value_state, cached.raw_value) == ("present", "7")
    assert uncached.formula is not None
    assert (uncached.formula.formula_type, uncached.formula.shared_index) == ("shared", 2)
    assert uncached.formula.reference == "D3:D4"
    assert (uncached.value_state, uncached.raw_value) == ("absent", None)


def test_shared_and_inline_rich_strings_preserve_runs_and_source() -> None:
    evidence = read_workbook_evidence(_lexeme_workbook())
    sheet = evidence.sheet("Ledger")

    assert sheet is not None
    plain = sheet.cell("D1")
    rich = sheet.cell("B4")
    inline = sheet.cell("A4")
    assert plain is not None and rich is not None and inline is not None
    assert plain.shared_text is not None and plain.shared_text.plain_text == "plain shared"
    assert rich.shared_text is not None and rich.shared_text.plain_text == "rich shared"
    assert rich.shared_text.runs[0].properties_xml == "<rPr><i/></rPr>"
    assert inline.inline_text is not None
    assert [run.text for run in inline.inline_text.runs] == ["bold", " tail"]
    assert inline.inline_text.runs[0].properties_xml == "<rPr><b/></rPr>"
    assert "<t>bold</t>" in inline.inline_text.source_xml
    assert evidence.shared_strings[0].source_xml == "<si><t>plain shared</t></si>"


def test_unresolvable_shared_string_cache_is_reported_not_fabricated() -> None:
    sheet = read_workbook_evidence(_lexeme_workbook()).sheet("Ledger")

    assert sheet is not None
    dangling = sheet.cell("D2")
    assert dangling is not None
    assert dangling.shared_string_index == 99
    assert dangling.shared_text_resolved is False
    assert dangling.shared_text is None
    assert dangling.raw_value == "99"


def test_cell_source_xml_retains_the_original_fragment() -> None:
    sheet = read_workbook_evidence(_lexeme_workbook()).sheet("Ledger")

    assert sheet is not None
    self_closed = sheet.cell("A2")
    styled = sheet.cell("C1")
    assert self_closed is not None and styled is not None
    assert self_closed.source_xml == '<c r="A2"/>'
    assert styled.source_xml == '<c r="C1" s="4"><v>10.10</v></c>'


def test_sheet_relationship_order_overrides_worksheet_file_numbering() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml(
                '<sheet name="Second" sheetId="2" r:id="rIdB"/>'
                '<sheet name="First" sheetId="1" r:id="rIdA"/>'
            ),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rIdB" Type="{DOC_REL_NS}/worksheet"'
                ' Target="/xl/worksheets/sheet9.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml('<row r="1"><c r="A1"><v>1</v></c></row>'),
            "xl/worksheets/sheet9.xml": _sheet_xml('<row r="1"><c r="A1"><v>9</v></c></row>'),
        }
    )

    evidence = read_workbook_evidence(data)

    assert [sheet.name for sheet in evidence.sheets] == ["Second", "First"]
    assert evidence.sheets[0].part_name == "xl/worksheets/sheet9.xml"
    assert evidence.sheets[0].ordinal == 0
    assert evidence.sheets[0].cells[0].raw_value == "9"
    assert evidence.sheets[1].part_name == "xl/worksheets/sheet1.xml"


def test_date1904_metadata_is_exposed_without_converting_serial_numbers() -> None:
    data = _lexeme_workbook(properties='<workbookPr date1904="1"/>')

    evidence = read_workbook_evidence(data)

    assert evidence.date1904 is True
    assert evidence.date1904_raw == "1"
    assert read_workbook_evidence(_lexeme_workbook()).date1904 is False


def test_repeated_reads_are_deterministic_and_leave_the_source_untouched(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic.xlsx"
    path.write_bytes(_lexeme_workbook())
    before = path.stat()

    first = read_workbook_evidence(path)
    second = read_workbook_evidence(path)
    after = path.stat()

    assert first == second
    assert first.source_size == len(path.read_bytes())
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["synthetic.xlsx"]


def test_malformed_sheet_xml_is_rejected() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": '<?xml version="1.0"?><worksheet><sheetData></worksheet>',
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_duplicate_cell_identity_is_rejected() -> None:
    rows = '<row r="1"><c r="A1"><v>1</v></c><c r="A1"><v>2</v></c></row>'
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml(rows),
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_duplicate_sheet_name_is_rejected() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml(
                '<sheet name="S" sheetId="1" r:id="rIdA"/><sheet name="S" sheetId="2" r:id="rIdB"/>'
            ),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rIdB" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet2.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml(""),
            "xl/worksheets/sheet2.xml": _sheet_xml(""),
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_external_relationship_target_is_never_followed() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="https://example.invalid/sheet1.xml" TargetMode="External"/>'
            ),
        }
    )

    with pytest.raises(XlsxEvidenceSecurityError):
        read_workbook_evidence(data)


def test_traversing_relationship_target_is_rejected() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="../../../etc/passwd"/>'
            ),
        }
    )

    with pytest.raises(XlsxEvidenceSecurityError):
        read_workbook_evidence(data)


def test_external_xml_entity_declaration_is_rejected() -> None:
    hostile = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE worksheet [<!ENTITY payload SYSTEM "file:///etc/passwd">]>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetData/></worksheet>'
    )
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": hostile,
        }
    )

    with pytest.raises(XlsxEvidenceSecurityError):
        read_workbook_evidence(data)


def test_compressed_bomb_is_refused_before_allocation() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", "0" * (4 * 1024 * 1024))
    limits = EvidenceLimits(max_part_bytes=64 * 1024, max_declared_total_bytes=128 * 1024)

    with pytest.raises(XlsxEvidenceLimitError):
        read_workbook_evidence(buffer.getvalue(), limits=limits)


def test_member_count_bound_is_enforced() -> None:
    members = {f"junk/{index}.bin": "x" for index in range(20)}
    members["_rels/.rels"] = ROOT_RELS

    with pytest.raises(XlsxEvidenceLimitError):
        read_workbook_evidence(_zip_bytes(members), limits=EvidenceLimits(max_members=8))


def test_traversing_archive_member_name_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("../escaped.xml", "<a/>")

    with pytest.raises(XlsxEvidenceSecurityError):
        read_workbook_evidence(buffer.getvalue())


def test_encrypted_container_is_rejected_without_leaking_contents() -> None:
    payload = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32

    with pytest.raises(XlsxEvidenceSecurityError) as excinfo:
        read_workbook_evidence(payload)

    assert "Encrypted" in str(excinfo.value)
    assert "\x00" not in str(excinfo.value)


def test_cell_without_a_reference_is_refused_rather_than_inferred() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml('<row r="1"><c><v>1</v></c></row>'),
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


EMPTY_CELL_ROWS = (
    '<row r="1"><c r="A1" t="n"><v>10.10</v></c></row>'
    '<row r="2"><c r="A2"/><c r="B2"><v></v></c></row>'
)


def _single_sheet_workbook(sheet_part: str | bytes) -> bytes:
    return _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": sheet_part,
        }
    )


def _encoded_sheet(declaration: str, encoding: str) -> bytes:
    body = (
        f"{declaration}"
        f'<worksheet xmlns="{MAIN_NS}"><dimension ref="A1:B2"/>'
        f"<sheetData>{EMPTY_CELL_ROWS}</sheetData></worksheet>"
    )
    return body.encode(encoding)


@pytest.mark.parametrize(
    ("declaration", "encoding"),
    [
        ("", "utf-16"),
        ('<?xml version="1.0" encoding="UTF-16"?>', "utf-16"),
        ('<?xml version="1.0" encoding="UTF-16"?>', "utf-16-be"),
        ("", "utf-16-le"),
        ('<?xml version="1.0" encoding="ISO-8859-1"?>', "latin-1"),
    ],
)
def test_non_utf8_worksheet_part_is_refused_instead_of_yielding_wrong_evidence(
    declaration: str, encoding: str
) -> None:
    """Expat would accept these, but recorded byte spans are UTF-8 offsets."""
    data = _single_sheet_workbook(_encoded_sheet(declaration, encoding))

    with pytest.raises(XlsxEvidenceFormatError) as excinfo:
        read_workbook_evidence(data)

    message = str(excinfo.value)
    assert "encoding" in message
    assert "\x00" not in message
    assert "worksheets/sheet1.xml" not in message


def test_utf8_bom_worksheet_part_keeps_byte_exact_empty_cell_evidence() -> None:
    """The one legal non-plain prefix must still produce exact fragments."""
    data = _single_sheet_workbook(_encoded_sheet("", "utf-8-sig"))

    evidence = read_workbook_evidence(data)

    sheet = evidence.sheet("S")
    assert sheet is not None
    absent = sheet.cell("A2")
    empty = sheet.cell("B2")
    assert absent is not None and empty is not None
    assert (absent.value_state, absent.raw_value) == ("absent", None)
    assert (empty.value_state, empty.raw_value) == ("empty", "")
    assert absent.source_xml == '<c r="A2"/>'
    assert empty.source_xml == '<c r="B2"><v></v></c>'
    assert "\x00" not in empty.source_xml


def test_malformed_zip_container_stays_inside_the_evidence_error_family() -> None:
    with pytest.raises(XlsxEvidenceError) as excinfo:
        read_workbook_evidence(b"PKmalformed")

    assert isinstance(excinfo.value, XlsxEvidenceFormatError)
    assert "malformed" not in str(excinfo.value)


def test_truncated_central_directory_is_normalized_to_a_format_error() -> None:
    payload = _lexeme_workbook()[:-24]

    with pytest.raises(XlsxEvidenceError) as excinfo:
        read_workbook_evidence(payload)

    assert isinstance(excinfo.value, XlsxEvidenceFormatError)


@pytest.mark.parametrize(
    "limits",
    [
        EvidenceLimits(max_part_bytes=-2),
        EvidenceLimits(max_members=0),
        EvidenceLimits(max_source_bytes=-1),
        EvidenceLimits(max_xml_depth=True),
    ],
)
def test_non_positive_or_boolean_limits_are_refused_before_reading(
    limits: EvidenceLimits,
) -> None:
    """A negative bound would otherwise turn into an unbounded ``read(-1)``."""
    with pytest.raises(XlsxEvidenceLimitError) as excinfo:
        read_workbook_evidence(_lexeme_workbook(), limits=limits)

    assert "positive integers" in str(excinfo.value)


def test_source_file_read_stops_one_byte_past_the_configured_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "oversized.xlsx"
    staged.write_bytes(b"PK" + b"\x00" * 8192)
    consumed = 0
    real_read = os.read

    def counting_read(descriptor: int, size: int) -> bytes:
        nonlocal consumed
        chunk = real_read(descriptor, size)
        consumed += len(chunk)
        return chunk

    monkeypatch.setattr(os, "read", counting_read)
    with pytest.raises(XlsxEvidenceLimitError):
        read_workbook_evidence(staged, limits=EvidenceLimits(max_source_bytes=64))

    assert 0 < consumed <= 65


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFOs")
def test_fifo_source_is_refused_without_blocking_on_a_writer(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe.xlsx"
    os.mkfifo(fifo)

    with pytest.raises(XlsxEvidenceFormatError) as excinfo:
        read_workbook_evidence(fifo)

    assert "regular file" in str(excinfo.value)


def test_directory_source_is_refused_after_the_descriptor_is_opened(tmp_path: Path) -> None:
    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(tmp_path)


def test_root_relationship_parsing_receives_the_caller_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = EvidenceLimits(max_xml_depth=12)
    seen: list[tuple[str, EvidenceLimits]] = []
    original = xlsx_evidence._read_relationships

    def recording(reader: object, part_name: str, passed: EvidenceLimits) -> dict[str, object]:
        seen.append((part_name, passed))
        return original(reader, part_name, passed)  # type: ignore[arg-type]

    monkeypatch.setattr(xlsx_evidence, "_read_relationships", recording)
    read_workbook_evidence(_lexeme_workbook(), limits=limits)

    assert seen[0][0] == ""
    assert seen[0][1] is limits


def test_root_relationship_depth_bound_is_enforced_by_the_caller_limits() -> None:
    with pytest.raises(XlsxEvidenceLimitError):
        read_workbook_evidence(_lexeme_workbook(), limits=EvidenceLimits(max_xml_depth=1))


def test_declared_chartsheet_relationship_fails_closed() -> None:
    """An unsupported sheet part must never vanish from the evidence silently."""
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml(
                '<sheet name="Ledger" sheetId="1" r:id="rIdA"/>'
                '<sheet name="Chart" sheetId="2" r:id="rIdC"/>'
            ),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rIdC" Type="{DOC_REL_NS}/chartsheet"'
                ' Target="chartsheets/sheet1.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml('<row r="1"><c r="A1"><v>1</v></c></row>'),
            "xl/chartsheets/sheet1.xml": f'<chartsheet xmlns="{MAIN_NS}"/>',
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_sheet_relationship_pointing_at_shared_strings_fails_closed() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdS"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdS" Type="{DOC_REL_NS}/sharedStrings"'
                ' Target="sharedStrings.xml"/>'
            ),
            "xl/sharedStrings.xml": SHARED_STRINGS,
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_foreign_namespace_relationship_type_is_not_read_as_ooxml() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<Relationships xmlns="{PKG_REL_NS}">'
                f'<Relationship Id="rId1" Type="{FOREIGN_NS}/officeDocument"'
                ' Target="xl/workbook.xml"/></Relationships>'
            ),
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_foreign_namespace_worksheet_root_is_not_read_as_ooxml() -> None:
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{FOREIGN_NS}"><sheetData>'
        '<row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>'
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(_single_sheet_workbook(sheet))


def test_worksheet_without_sheet_data_fails_closed_rather_than_reading_empty() -> None:
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{MAIN_NS}"><dimension ref="A1:A1"/></worksheet>'
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(_single_sheet_workbook(sheet))


def test_workbook_root_in_a_foreign_namespace_is_refused() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<workbook xmlns="{FOREIGN_NS}" xmlns:r="{DOC_REL_NS}">'
                '<sheets><sheet name="S" sheetId="1" r:id="rIdA"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml('<row r="1"><c r="A1"><v>1</v></c></row>'),
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_shared_string_root_in_a_foreign_namespace_is_refused() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": _workbook_xml('<sheet name="S" sheetId="1" r:id="rIdA"/>'),
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rIdS" Type="{DOC_REL_NS}/sharedStrings"'
                ' Target="sharedStrings.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml('<row r="1"><c r="A1" t="s"><v>0</v></c></row>'),
            "xl/sharedStrings.xml": f'<sst xmlns="{FOREIGN_NS}"><si><t>x</t></si></sst>',
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_foreign_namespace_identity_attribute_never_shadows_the_ooxml_one() -> None:
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}" xmlns:evil="{FOREIGN_NS}">'
        '<sheets><sheet name="S" sheetId="1" evil:id="rIdBogus" r:id="rIdA"/></sheets>'
        "</workbook>"
    )
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rIdBogus" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/decoy.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml('<row r="1"><c r="A1"><v>1</v></c></row>'),
            "xl/worksheets/decoy.xml": _sheet_xml('<row r="1"><c r="A1"><v>999</v></c></row>'),
        }
    )

    evidence = read_workbook_evidence(data)

    sheet = evidence.sheet("S")
    assert sheet is not None
    assert sheet.relationship_id == "rIdA"
    assert sheet.part_name == "xl/worksheets/sheet1.xml"


def test_conflicting_relationship_namespaced_identities_are_refused_not_guessed() -> None:
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}" xmlns:sr="{STRICT_DOC_REL_NS}">'
        '<sheets><sheet name="S" sheetId="1" r:id="rIdA" sr:id="rIdB"/></sheets>'
        "</workbook>"
    )
    data = _zip_bytes(
        {
            "_rels/.rels": ROOT_RELS,
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": _workbook_rels(
                f'<Relationship Id="rIdA" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rIdB" Type="{DOC_REL_NS}/worksheet"'
                ' Target="worksheets/decoy.xml"/>'
            ),
            "xl/worksheets/sheet1.xml": _sheet_xml('<row r="1"><c r="A1"><v>1</v></c></row>'),
            "xl/worksheets/decoy.xml": _sheet_xml('<row r="1"><c r="A1"><v>2</v></c></row>'),
        }
    )

    with pytest.raises(XlsxEvidenceFormatError):
        read_workbook_evidence(data)


def test_strict_namespace_workbook_with_absolute_root_target_is_supported() -> None:
    data = _zip_bytes(
        {
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<Relationships xmlns="{STRICT_PKG_REL_NS}">'
                f'<Relationship Id="rId1" Type="{STRICT_DOC_REL_NS}/officeDocument"'
                ' Target="/xl/workbook.xml"/></Relationships>'
            ),
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<workbook xmlns="{STRICT_MAIN_NS}" xmlns:r="{STRICT_DOC_REL_NS}">'
                '<sheets><sheet name="Strict" sheetId="1" r:id="rIdA"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<Relationships xmlns="{STRICT_PKG_REL_NS}">'
                f'<Relationship Id="rIdA" Type="{STRICT_DOC_REL_NS}/worksheet"'
                ' Target="worksheets/sheet1.xml"/></Relationships>'
            ),
            "xl/worksheets/sheet1.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<worksheet xmlns="{STRICT_MAIN_NS}"><sheetData>'
                '<row r="1"><c r="A1"><v>00.50</v></c></row></sheetData></worksheet>'
            ),
        }
    )

    evidence = read_workbook_evidence(data)

    sheet = evidence.sheet("Strict")
    assert sheet is not None
    assert evidence.workbook_part == "xl/workbook.xml"
    cell = sheet.cell("A1")
    assert cell is not None
    assert cell.raw_value == "00.50"
