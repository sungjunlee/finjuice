"""Bounded, source-preserving raw evidence reader for XLSX (OOXML) workbooks.

The reader captures workbook, sheet, and cell evidence straight from the
original package parts so that lexical numeric text survives untouched. It
never converts values to :class:`float`, never evaluates formulas, never
extracts archive members to disk, and never follows external relationship
targets. Monetary interpretation, date-system conversion, currency, owner, and
account attribution all belong to downstream consumers.
"""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import re
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal
from xml.parsers import expat

__all__ = [
    "CellEvidence",
    "EvidenceLimits",
    "FormulaEvidence",
    "RichText",
    "SheetEvidence",
    "TextRun",
    "WorkbookEvidence",
    "XlsxEvidenceError",
    "XlsxEvidenceFormatError",
    "XlsxEvidenceLimitError",
    "XlsxEvidenceSecurityError",
    "read_workbook_evidence",
]


class XlsxEvidenceError(ValueError):
    """Base error for raw XLSX evidence capture."""


class XlsxEvidenceFormatError(XlsxEvidenceError):
    """A package part is malformed or carries an ambiguous identity."""


class XlsxEvidenceLimitError(XlsxEvidenceError):
    """A package exceeds a configured finite capture bound."""


class XlsxEvidenceSecurityError(XlsxEvidenceError):
    """A package requests an unsafe, external, or encrypted resource."""


ValueState = Literal["absent", "empty", "present"]

_NS_SEPARATOR: Final = "\x01"
_REF_RE: Final = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$")
_INT_RE: Final = re.compile(r"^(?:0|[1-9][0-9]*)$")
_WINDOWS_DRIVE_RE: Final = re.compile(r"^[A-Za-z]:")
_OFFICE_DOCUMENT_TYPE: Final = "officeDocument"
_SHARED_STRINGS_TYPE: Final = "sharedStrings"
_WORKSHEET_TYPE: Final = "worksheet"
_TRUE_TOKENS: Final = frozenset({"1", "true", "on"})
_FALSE_TOKENS: Final = frozenset({"0", "false", "off"})
_OLE_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_READ_CHUNK_BYTES: Final = 1024 * 1024

# Both the transitional and the strict OOXML namespaces are canonical. Any
# other namespace is foreign and must never be interpreted by local name.
_MAIN_NS: Final = frozenset(
    {
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "http://purl.oclc.org/ooxml/spreadsheetml/main",
    }
)
_PKG_RELS_NS: Final = frozenset(
    {
        "http://schemas.openxmlformats.org/package/2006/relationships",
        "http://purl.oclc.org/ooxml/package/relationships",
    }
)
_DOC_RELS_NS: Final = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)

_UTF8_BOM: Final = b"\xef\xbb\xbf"
_REJECTED_BOMS: Final = (b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00", b"\xfe\xff", b"\xff\xfe")
_DECL_ENCODING_RE: Final = re.compile(
    rb"""^<\?xml[^>]{0,400}?encoding\s*=\s*["\']([\w.:+-]+)["\']"""
)
_SUPPORTED_ENCODINGS: Final = frozenset({"utf-8", "utf8", "us-ascii", "ascii"})
_LIMIT_FIELDS: Final = (
    "max_source_bytes",
    "max_members",
    "max_declared_total_bytes",
    "max_part_bytes",
    "max_sheets",
    "max_shared_strings",
    "max_cells_per_sheet",
    "max_xml_depth",
)


@dataclass(frozen=True)
class EvidenceLimits:
    """Finite bounds that keep a hostile or oversized package non-allocating."""

    max_source_bytes: int = 64 * 1024 * 1024
    max_members: int = 512
    max_declared_total_bytes: int = 64 * 1024 * 1024
    max_part_bytes: int = 16 * 1024 * 1024
    max_sheets: int = 64
    max_shared_strings: int = 200_000
    max_cells_per_sheet: int = 500_000
    max_xml_depth: int = 64


DEFAULT_EVIDENCE_LIMITS: Final = EvidenceLimits()


@dataclass(frozen=True)
class TextRun:
    """One formatting run of a shared or inline string."""

    text: str
    properties_xml: str | None


@dataclass(frozen=True)
class RichText:
    """A string item preserved as ordered runs plus its raw source fragment."""

    runs: tuple[TextRun, ...]
    plain_text: str
    source_xml: str


@dataclass(frozen=True)
class FormulaEvidence:
    """A formula definition captured verbatim and never evaluated."""

    text: str
    formula_type: str | None
    shared_index: int | None
    reference: str | None
    source_xml: str


@dataclass(frozen=True)
class CellEvidence:
    """Raw cell facts with the original ``<v>`` lexeme left unconverted."""

    reference: str
    column: str
    row: int
    cell_type: str
    type_declared: bool
    style_index: int | None
    value_state: ValueState
    raw_value: str | None
    formula: FormulaEvidence | None
    inline_text: RichText | None
    shared_string_index: int | None
    shared_text: RichText | None
    shared_text_resolved: bool
    source_xml: str


@dataclass(frozen=True)
class SheetEvidence:
    """One worksheet resolved through workbook relationships, not file order."""

    name: str
    sheet_id: str | None
    relationship_id: str
    part_name: str
    state: str
    ordinal: int
    dimension: str | None
    cells: tuple[CellEvidence, ...]

    def cell(self, reference: str) -> CellEvidence | None:
        """Return the cell at ``reference`` or ``None`` when it is absent."""
        for candidate in self.cells:
            if candidate.reference == reference:
                return candidate
        return None


@dataclass(frozen=True)
class WorkbookEvidence:
    """Whole-workbook evidence bound to the digest of the original bytes."""

    sheets: tuple[SheetEvidence, ...]
    date1904: bool
    date1904_raw: str | None
    shared_strings: tuple[RichText, ...]
    workbook_part: str
    source_size: int
    source_sha256: str

    def sheet(self, name: str) -> SheetEvidence | None:
        """Return the sheet named ``name`` or ``None`` when it is absent."""
        for candidate in self.sheets:
            if candidate.name == name:
                return candidate
        return None


@dataclass
class _Node:
    """A parsed element plus the byte span of its original serialization."""

    tag: str
    attrs: dict[str, str]
    start: int
    end: int = -1
    text_parts: list[str] = field(default_factory=list)
    children: list[_Node] = field(default_factory=list)


@dataclass(frozen=True)
class _Part:
    """A decoded package part with its raw bytes and parsed element tree."""

    name: str
    data: bytes
    encoding: str
    root: _Node


@dataclass(frozen=True)
class _Relationship:
    """One OPC relationship as declared, without any target resolution."""

    rel_id: str
    rel_type: str
    target: str
    external: bool


def read_workbook_evidence(
    source: Path | bytes,
    *,
    limits: EvidenceLimits = DEFAULT_EVIDENCE_LIMITS,
) -> WorkbookEvidence:
    """Capture read-only raw evidence from an XLSX package.

    Args:
        source: A local path to read, or the workbook bytes themselves.
        limits: Finite capture bounds applied to the package and its parts.

    Returns:
        Deterministic workbook evidence with unconverted cell lexemes.

    Raises:
        XlsxEvidenceError: The package is malformed, unsafe, or over a bound.
    """
    _validate_limits(limits)
    data = _load_source(source, limits)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError) as exc:
        raise XlsxEvidenceFormatError("Workbook is not a readable OOXML package.") from exc
    with archive:
        reader = _PackageReader(archive, limits)
        return _read_package(reader, data, limits)


def _validate_limits(limits: EvidenceLimits) -> None:
    """Refuse capture bounds that are not finite positive integers."""
    for name in _LIMIT_FIELDS:
        value = getattr(limits, name, None)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise XlsxEvidenceLimitError("Capture bounds must be positive integers.")


def _load_source(source: Path | bytes, limits: EvidenceLimits) -> bytes:
    """Return the workbook bytes after size and container sanity checks."""
    data = source if isinstance(source, bytes) else _read_file(source, limits)
    if len(data) > limits.max_source_bytes:
        raise XlsxEvidenceLimitError("Workbook exceeds the configured source byte bound.")
    if data.startswith(_OLE_MAGIC):
        raise XlsxEvidenceSecurityError("Encrypted or legacy container workbooks are unsupported.")
    if not data.startswith(b"PK"):
        raise XlsxEvidenceFormatError("Workbook is not an OOXML package.")
    return data


def _read_file(path: Path, limits: EvidenceLimits) -> bytes:
    """Read a regular local file through one descriptor that cannot block."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise XlsxEvidenceFormatError("Workbook path could not be opened.") from exc
    try:
        return _read_descriptor(descriptor, limits)
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int, limits: EvidenceLimits) -> bytes:
    """Read at most one byte past the source bound from an open descriptor."""
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise XlsxEvidenceFormatError("Workbook path must be a regular file.")
    budget = limits.max_source_bytes + 1
    chunks: list[bytes] = []
    total = 0
    while total < budget:
        try:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, budget - total))
        except OSError as exc:
            raise XlsxEvidenceFormatError("Workbook could not be read.") from exc
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > limits.max_source_bytes:
        raise XlsxEvidenceLimitError("Workbook exceeds the configured source byte bound.")
    return b"".join(chunks)


def _read_package(reader: _PackageReader, data: bytes, limits: EvidenceLimits) -> WorkbookEvidence:
    """Resolve the workbook part and assemble evidence for every worksheet."""
    workbook_part = _find_workbook_part(reader, limits)
    workbook = reader.part(workbook_part, limits)
    _require_root(workbook, "workbook", _MAIN_NS)
    relationships = _read_relationships(reader, workbook_part, limits)
    shared = _read_shared_strings(reader, workbook_part, relationships, limits)
    entries = _sheet_entries(workbook, relationships, workbook_part, limits)
    sheets = tuple(
        _read_sheet(reader, entry, ordinal, shared, limits) for ordinal, entry in enumerate(entries)
    )
    raw_flag = _date1904_raw(workbook)
    return WorkbookEvidence(
        sheets=sheets,
        date1904=_parse_bool_attribute(raw_flag),
        date1904_raw=raw_flag,
        shared_strings=shared,
        workbook_part=workbook_part,
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest(),
    )


class _PackageReader:
    """Bounded, read-only accessor over the ZIP members of a package."""

    def __init__(self, archive: zipfile.ZipFile, limits: EvidenceLimits) -> None:
        _validate_archive(archive, limits)
        self._archive = archive

    def read(self, name: str, limits: EvidenceLimits) -> bytes:
        """Return part bytes, refusing anything past the per-part bound."""
        try:
            with self._archive.open(name) as handle:
                data = handle.read(limits.max_part_bytes + 1)
        except KeyError as exc:
            raise XlsxEvidenceFormatError("A required package part is missing.") from exc
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as exc:
            raise XlsxEvidenceFormatError("A package part could not be decompressed.") from exc
        if len(data) > limits.max_part_bytes:
            raise XlsxEvidenceLimitError("A package part exceeds the configured byte bound.")
        return data

    def has(self, name: str) -> bool:
        """Report whether the archive declares ``name`` as a member."""
        try:
            self._archive.getinfo(name)
        except KeyError:
            return False
        return True

    def part(self, name: str, limits: EvidenceLimits) -> _Part:
        """Return the parsed element tree and raw bytes for one part."""
        data = self.read(name, limits)
        root, encoding = _parse_xml(data, limits)
        return _Part(name=name, data=data, encoding=encoding, root=root)


def _validate_archive(archive: zipfile.ZipFile, limits: EvidenceLimits) -> None:
    """Reject encrypted, duplicated, unsafe, or oversized archive members."""
    infos = archive.infolist()
    if len(infos) > limits.max_members:
        raise XlsxEvidenceLimitError("Package exceeds the configured member count bound.")
    names = [info.filename for info in infos]
    if len(set(names)) != len(names):
        raise XlsxEvidenceFormatError("Package declares duplicate archive entries.")
    declared = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise XlsxEvidenceSecurityError("Encrypted package members are unsupported.")
        _validate_member_name(info.filename)
        if info.file_size > limits.max_part_bytes:
            raise XlsxEvidenceLimitError("A package part exceeds the configured byte bound.")
        declared += info.file_size
    if declared > limits.max_declared_total_bytes:
        raise XlsxEvidenceLimitError("Package exceeds the configured uncompressed byte bound.")


def _validate_member_name(name: str) -> None:
    """Refuse absolute, traversing, or platform-ambiguous member names."""
    if not name or name.endswith("/"):
        return
    if name.startswith("/") or "\\" in name or _WINDOWS_DRIVE_RE.match(name):
        raise XlsxEvidenceSecurityError("Package member name is absolute or platform-unsafe.")
    if ".." in name.split("/"):
        raise XlsxEvidenceSecurityError("Package member name traverses outside the package.")


def _parse_xml(data: bytes, limits: EvidenceLimits) -> tuple[_Node, str]:
    """Parse one part into a span-annotated tree, rejecting DTDs and entities."""
    _assert_utf8_part(data)
    builder = _SpanParser(data, limits)
    return builder.parse()


def _assert_utf8_part(data: bytes) -> None:
    """Reject encodings whose byte spans would not survive fragment capture.

    Expat happily accepts a UTF-16 part, but every recorded span is a byte
    offset that this reader slices and decodes itself. Rather than emit
    silently wrong evidence, refuse the part before parsing it at all.
    """
    if data.startswith(_REJECTED_BOMS):
        raise XlsxEvidenceFormatError("Package part uses an unsupported text encoding.")
    body = data[len(_UTF8_BOM) :] if data.startswith(_UTF8_BOM) else data
    if b"\x00" in body[:4]:
        raise XlsxEvidenceFormatError("Package part uses an unsupported text encoding.")
    declared = _DECL_ENCODING_RE.match(body)
    if declared is None:
        return
    if declared.group(1).decode("ascii", "replace").lower() not in _SUPPORTED_ENCODINGS:
        raise XlsxEvidenceFormatError("Package part uses an unsupported text encoding.")


class _SpanParser:
    """Expat driver that records the exact byte span of every element."""

    def __init__(self, data: bytes, limits: EvidenceLimits) -> None:
        self._data = data
        self._limits = limits
        self._stack: list[_Node] = []
        self._root: _Node | None = None
        self._encoding = "utf-8"
        self._parser = expat.ParserCreate(namespace_separator=_NS_SEPARATOR)

    def parse(self) -> tuple[_Node, str]:
        """Return the parsed root element and the declared part encoding."""
        self._install_handlers()
        try:
            self._parser.Parse(self._data, True)
        except expat.ExpatError as exc:
            raise XlsxEvidenceFormatError("Package part XML is malformed.") from exc
        if self._root is None or self._stack:
            raise XlsxEvidenceFormatError("Package part XML has no complete root element.")
        return self._root, self._encoding

    def _install_handlers(self) -> None:
        self._parser.XmlDeclHandler = self._declaration
        self._parser.StartElementHandler = self._start
        self._parser.EndElementHandler = self._end
        self._parser.CharacterDataHandler = self._characters
        self._parser.StartDoctypeDeclHandler = self._reject_doctype
        self._parser.EntityDeclHandler = self._reject_entity
        self._parser.ExternalEntityRefHandler = self._reject_external

    def _declaration(self, version: str, encoding: str | None, standalone: int) -> None:
        if encoding and encoding.lower() not in _SUPPORTED_ENCODINGS:
            raise XlsxEvidenceFormatError("Package part uses an unsupported text encoding.")

    def _start(self, name: str, attrs: dict[str, str]) -> None:
        if len(self._stack) >= self._limits.max_xml_depth:
            raise XlsxEvidenceLimitError("Package part XML nesting exceeds the capture bound.")
        self._stack.append(_Node(tag=name, attrs=dict(attrs), start=self._parser.CurrentByteIndex))

    def _end(self, name: str) -> None:
        node = self._stack.pop()
        node.end = self._element_end(node)
        if self._stack:
            self._stack[-1].children.append(node)
        else:
            self._root = node

    def _element_end(self, node: _Node) -> int:
        """Return the end offset, allowing for empty-element tags."""
        start_tag_end = _tag_end(self._data, node.start)
        if self._data[start_tag_end - 2 : start_tag_end - 1] == b"/":
            return start_tag_end
        return _tag_end(self._data, self._parser.CurrentByteIndex)

    def _characters(self, text: str) -> None:
        if self._stack:
            self._stack[-1].text_parts.append(text)

    def _reject_doctype(self, *args: object) -> None:
        raise XlsxEvidenceSecurityError("Package part XML declares an unsupported DTD.")

    def _reject_entity(self, *args: object) -> None:
        raise XlsxEvidenceSecurityError("Package part XML declares an unsupported entity.")

    def _reject_external(self, *args: object) -> int:
        raise XlsxEvidenceSecurityError("Package part XML references an external entity.")


def _tag_end(data: bytes, index: int) -> int:
    """Return the byte offset just past the tag beginning at ``index``.

    Attribute values may legally contain ``>``, so quoting is tracked.
    """
    quote = 0
    for offset in range(index, len(data)):
        byte = data[offset]
        if quote:
            if byte == quote:
                quote = 0
        elif byte in (0x22, 0x27):
            quote = byte
        elif byte == 0x3E:
            return offset + 1
    raise XlsxEvidenceFormatError("Package part XML has an unterminated tag.")


def _qname(tag: str) -> tuple[str, str]:
    """Split an expat tag into its namespace URI and its local name."""
    namespace, separator, local = tag.rpartition(_NS_SEPARATOR)
    return (namespace if separator else "", local)


def _is_element(node: _Node, name: str, namespaces: frozenset[str]) -> bool:
    """Report whether ``node`` is ``name`` in one of the accepted namespaces."""
    namespace, local = _qname(node.tag)
    return local == name and namespace in namespaces


def _require_root(part: _Part, name: str, namespaces: frozenset[str]) -> _Node:
    """Return the part root after asserting its namespace and local name."""
    if not _is_element(part.root, name, namespaces):
        raise XlsxEvidenceFormatError("Package part declares an unexpected root element.")
    return part.root


def _attr(node: _Node, name: str) -> str | None:
    """Return an unprefixed attribute declared directly on ``node``."""
    return node.attrs.get(name)


def _ns_attr(node: _Node, name: str, namespaces: frozenset[str]) -> str | None:
    """Return a namespace-qualified attribute, refusing ambiguous duplicates."""
    values = [
        value
        for key, value in node.attrs.items()
        if _qname(key) in {(namespace, name) for namespace in namespaces}
    ]
    if not values:
        return None
    if len(set(values)) != 1:
        raise XlsxEvidenceFormatError("Element declares conflicting qualified attributes.")
    return values[0]


def _rel_type_matches(rel_type: str, suffix: str) -> bool:
    """Report whether a relationship type is the canonical OOXML ``suffix``."""
    return any(rel_type == f"{base}/{suffix}" for base in _DOC_RELS_NS)


def _children(node: _Node, name: str, namespaces: frozenset[str] = _MAIN_NS) -> list[_Node]:
    """Return direct child elements matching ``name`` in ``namespaces``."""
    return [child for child in node.children if _is_element(child, name, namespaces)]


def _text(node: _Node) -> str:
    """Return the verbatim character data directly inside ``node``."""
    return "".join(node.text_parts)


def _fragment(part: _Part, node: _Node) -> str:
    """Return the original serialized bytes of ``node`` decoded strictly."""
    raw = part.data[node.start : node.end]
    try:
        return raw.decode(part.encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise XlsxEvidenceFormatError("Package part uses an undecodable encoding.") from exc


def _parse_bool_attribute(value: str | None) -> bool:
    """Interpret an OOXML boolean attribute, defaulting to false when absent."""
    if value is None:
        return False
    token = value.strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    raise XlsxEvidenceFormatError("Workbook declares an unrecognized boolean attribute.")


def _parse_index(value: str | None, message: str) -> int | None:
    """Parse a non-negative integer attribute, refusing malformed input."""
    if value is None:
        return None
    if _INT_RE.fullmatch(value) is None:
        raise XlsxEvidenceFormatError(message)
    return int(value)


def _rels_part(part_name: str) -> str:
    """Return the OPC relationships part that describes ``part_name``."""
    if not part_name:
        return "_rels/.rels"
    directory = posixpath.dirname(part_name)
    return posixpath.join(directory, "_rels", posixpath.basename(part_name) + ".rels")


def _read_relationships(
    reader: _PackageReader,
    part_name: str,
    limits: EvidenceLimits,
) -> dict[str, _Relationship]:
    """Parse the relationships declared for ``part_name``."""
    rels_name = _rels_part(part_name)
    if not reader.has(rels_name):
        raise XlsxEvidenceFormatError("A required relationships part is missing.")
    root = _require_root(reader.part(rels_name, limits), "Relationships", _PKG_RELS_NS)
    relationships: dict[str, _Relationship] = {}
    for child in _children(root, "Relationship", _PKG_RELS_NS):
        relationship = _relationship_from(child)
        if relationship.rel_id in relationships:
            raise XlsxEvidenceFormatError("Package declares duplicate relationship identities.")
        relationships[relationship.rel_id] = relationship
    return relationships


def _relationship_from(node: _Node) -> _Relationship:
    """Build one relationship record from its declaring element."""
    rel_id = _attr(node, "Id")
    rel_type = _attr(node, "Type")
    target = _attr(node, "Target")
    if not rel_id or not rel_type or target is None:
        raise XlsxEvidenceFormatError("Package declares an incomplete relationship.")
    mode = (_attr(node, "TargetMode") or "Internal").strip()
    return _Relationship(
        rel_id=rel_id, rel_type=rel_type, target=target, external=mode == "External"
    )


def _resolve_part(base_part: str, relationship: _Relationship) -> str:
    """Resolve an internal relationship target to a package part name."""
    if relationship.external:
        raise XlsxEvidenceSecurityError("External relationship targets are never followed.")
    target = relationship.target
    if "://" in target or target.startswith("//"):
        raise XlsxEvidenceSecurityError("External relationship targets are never followed.")
    base = "" if target.startswith("/") else posixpath.dirname(base_part)
    candidate = posixpath.normpath(posixpath.join(base, target.lstrip("/")))
    if candidate in {"", ".", ".."} or candidate.startswith(("../", "/")):
        raise XlsxEvidenceSecurityError("Relationship target escapes the package root.")
    _validate_member_name(candidate)
    return candidate


def _find_workbook_part(reader: _PackageReader, limits: EvidenceLimits) -> str:
    """Locate the workbook part through the package root relationships."""
    relationships = _read_relationships(reader, "", limits)
    matches = [
        rel
        for rel in relationships.values()
        if _rel_type_matches(rel.rel_type, _OFFICE_DOCUMENT_TYPE)
    ]
    if len(matches) != 1:
        raise XlsxEvidenceFormatError("Package does not declare exactly one workbook part.")
    return _resolve_part("", matches[0])


def _date1904_raw(workbook: _Part) -> str | None:
    """Return the raw ``date1904`` attribute without converting any date."""
    properties = _children(workbook.root, "workbookPr")
    if len(properties) > 1:
        raise XlsxEvidenceFormatError("Workbook declares conflicting workbook properties.")
    if not properties:
        return None
    return _attr(properties[0], "date1904")


@dataclass(frozen=True)
class _SheetEntry:
    """A workbook sheet declaration paired with its resolved part name."""

    name: str
    sheet_id: str | None
    relationship_id: str
    part_name: str
    state: str


def _sheet_entries(
    workbook: _Part,
    relationships: dict[str, _Relationship],
    workbook_part: str,
    limits: EvidenceLimits,
) -> list[_SheetEntry]:
    """Resolve every declared sheet through its relationship, not file order."""
    containers = _children(workbook.root, "sheets")
    if len(containers) != 1:
        raise XlsxEvidenceFormatError("Workbook does not declare exactly one sheet list.")
    nodes = _children(containers[0], "sheet")
    if len(nodes) > limits.max_sheets:
        raise XlsxEvidenceLimitError("Workbook exceeds the configured sheet count bound.")
    entries = [_sheet_entry(node, relationships, workbook_part) for node in nodes]
    _assert_unique_sheets(entries)
    return entries


def _sheet_entry(
    node: _Node,
    relationships: dict[str, _Relationship],
    workbook_part: str,
) -> _SheetEntry:
    """Build one sheet entry, requiring an explicit relationship reference."""
    name = _attr(node, "name")
    rel_id = _ns_attr(node, "id", _DOC_RELS_NS)
    if not name or not rel_id:
        raise XlsxEvidenceFormatError("Workbook declares a sheet without a name or relationship.")
    relationship = relationships.get(rel_id)
    if relationship is None:
        raise XlsxEvidenceFormatError("Workbook references an undeclared sheet relationship.")
    if not _rel_type_matches(relationship.rel_type, _WORKSHEET_TYPE):
        raise XlsxEvidenceFormatError("Workbook declares a sheet part that is not a worksheet.")
    return _SheetEntry(
        name=name,
        sheet_id=_attr(node, "sheetId"),
        relationship_id=rel_id,
        part_name=_resolve_part(workbook_part, relationship),
        state=_attr(node, "state") or "visible",
    )


def _assert_unique_sheets(entries: list[_SheetEntry]) -> None:
    """Refuse workbooks whose sheet names, ids, or parts collide."""
    for values in (
        [entry.name for entry in entries],
        [entry.relationship_id for entry in entries],
        [entry.part_name for entry in entries],
        [entry.sheet_id for entry in entries if entry.sheet_id is not None],
    ):
        if len(set(values)) != len(values):
            raise XlsxEvidenceFormatError("Workbook declares conflicting sheet identities.")


def _read_shared_strings(
    reader: _PackageReader,
    workbook_part: str,
    relationships: dict[str, _Relationship],
    limits: EvidenceLimits,
) -> tuple[RichText, ...]:
    """Parse the shared string table when the workbook relates to one."""
    matches = [
        rel
        for rel in relationships.values()
        if _rel_type_matches(rel.rel_type, _SHARED_STRINGS_TYPE)
    ]
    if not matches:
        return ()
    if len(matches) > 1:
        raise XlsxEvidenceFormatError("Workbook declares conflicting shared string parts.")
    part = reader.part(_resolve_part(workbook_part, matches[0]), limits)
    items = _children(_require_root(part, "sst", _MAIN_NS), "si")
    if len(items) > limits.max_shared_strings:
        raise XlsxEvidenceLimitError("Shared string table exceeds the configured bound.")
    return tuple(_rich_text(part, item) for item in items)


def _rich_text(part: _Part, node: _Node) -> RichText:
    """Capture a string item as ordered runs plus its raw source fragment."""
    runs: list[TextRun] = []
    for child in node.children:
        if _is_element(child, "t", _MAIN_NS):
            runs.append(TextRun(text=_text(child), properties_xml=None))
        elif _is_element(child, "r", _MAIN_NS):
            runs.append(_text_run(part, child))
    return RichText(
        runs=tuple(runs),
        plain_text="".join(run.text for run in runs),
        source_xml=_fragment(part, node),
    )


def _text_run(part: _Part, node: _Node) -> TextRun:
    """Capture one formatting run with its properties kept as raw XML."""
    properties = _children(node, "rPr")
    text = "".join(_text(child) for child in _children(node, "t"))
    return TextRun(
        text=text,
        properties_xml=_fragment(part, properties[0]) if properties else None,
    )


def _read_sheet(
    reader: _PackageReader,
    entry: _SheetEntry,
    ordinal: int,
    shared: tuple[RichText, ...],
    limits: EvidenceLimits,
) -> SheetEvidence:
    """Capture cell evidence for one worksheet part."""
    part = reader.part(entry.part_name, limits)
    dimensions = _children(_require_root(part, "worksheet", _MAIN_NS), "dimension")
    cells = _sheet_cells(part, shared, limits)
    return SheetEvidence(
        name=entry.name,
        sheet_id=entry.sheet_id,
        relationship_id=entry.relationship_id,
        part_name=entry.part_name,
        state=entry.state,
        ordinal=ordinal,
        dimension=_attr(dimensions[0], "ref") if dimensions else None,
        cells=cells,
    )


def _sheet_cells(
    part: _Part,
    shared: tuple[RichText, ...],
    limits: EvidenceLimits,
) -> tuple[CellEvidence, ...]:
    """Walk sheet rows and capture every cell exactly once."""
    containers = _children(part.root, "sheetData")
    if len(containers) != 1:
        raise XlsxEvidenceFormatError("Worksheet does not declare exactly one sheet data block.")
    sink = _CellSink()
    for row in _children(containers[0], "row"):
        _collect_row(part, row, shared, sink, limits)
    return tuple(sink.cells)


@dataclass
class _CellSink:
    """Accumulated cells plus the identities already claimed by one sheet."""

    cells: list[CellEvidence] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    rows: set[int] = field(default_factory=set)


def _collect_row(
    part: _Part,
    row: _Node,
    shared: tuple[RichText, ...],
    sink: _CellSink,
    limits: EvidenceLimits,
) -> None:
    """Capture one row, refusing duplicate row or cell identities."""
    declared_row = _parse_index(_attr(row, "r"), "Worksheet declares a malformed row index.")
    if declared_row is not None:
        if declared_row in sink.rows:
            raise XlsxEvidenceFormatError("Worksheet declares conflicting row identities.")
        sink.rows.add(declared_row)
    for node in _children(row, "c"):
        cell = _parse_cell(part, node, shared)
        if cell.reference in sink.seen:
            raise XlsxEvidenceFormatError("Worksheet declares conflicting cell identities.")
        if declared_row is not None and cell.row != declared_row:
            raise XlsxEvidenceFormatError("Worksheet cell reference disagrees with its row.")
        sink.seen.add(cell.reference)
        sink.cells.append(cell)
        if len(sink.cells) > limits.max_cells_per_sheet:
            raise XlsxEvidenceLimitError("Worksheet exceeds the configured cell count bound.")


def _parse_cell(part: _Part, node: _Node, shared: tuple[RichText, ...]) -> CellEvidence:
    """Capture one cell without converting, evaluating, or inferring anything."""
    reference = _attr(node, "r")
    match = _REF_RE.fullmatch(reference) if reference else None
    if reference is None or match is None:
        raise XlsxEvidenceFormatError("Worksheet declares a cell without a usable reference.")
    declared_type = _attr(node, "t")
    value_state, raw_value = _cell_value(node)
    index, resolved = _shared_lookup(declared_type, raw_value, shared)
    return CellEvidence(
        reference=reference,
        column=match.group(1),
        row=int(match.group(2)),
        cell_type=declared_type or "n",
        type_declared=declared_type is not None,
        style_index=_parse_index(_attr(node, "s"), "Worksheet declares a malformed style index."),
        value_state=value_state,
        raw_value=raw_value,
        formula=_cell_formula(part, node),
        inline_text=_cell_inline_text(part, node),
        shared_string_index=index,
        shared_text=shared[index] if resolved and index is not None else None,
        shared_text_resolved=resolved,
        source_xml=_fragment(part, node),
    )


def _cell_value(node: _Node) -> tuple[ValueState, str | None]:
    """Return the raw ``<v>`` lexeme, distinguishing absent from empty."""
    values = _children(node, "v")
    if len(values) > 1:
        raise XlsxEvidenceFormatError("Worksheet cell declares conflicting cached values.")
    if not values:
        return "absent", None
    raw = _text(values[0])
    return ("empty" if raw == "" else "present"), raw


def _cell_formula(part: _Part, node: _Node) -> FormulaEvidence | None:
    """Capture a formula definition verbatim; formulas are never executed."""
    formulas = _children(node, "f")
    if len(formulas) > 1:
        raise XlsxEvidenceFormatError("Worksheet cell declares conflicting formulas.")
    if not formulas:
        return None
    formula = formulas[0]
    return FormulaEvidence(
        text=_text(formula),
        formula_type=_attr(formula, "t"),
        shared_index=_parse_index(
            _attr(formula, "si"), "Worksheet declares a malformed shared formula index."
        ),
        reference=_attr(formula, "ref"),
        source_xml=_fragment(part, formula),
    )


def _cell_inline_text(part: _Part, node: _Node) -> RichText | None:
    """Capture an inline string, keeping an empty inline string distinguishable."""
    inline = _children(node, "is")
    if len(inline) > 1:
        raise XlsxEvidenceFormatError("Worksheet cell declares conflicting inline strings.")
    return _rich_text(part, inline[0]) if inline else None


def _shared_lookup(
    declared_type: str | None,
    raw_value: str | None,
    shared: tuple[RichText, ...],
) -> tuple[int | None, bool]:
    """Resolve a shared string index, leaving unusable caches unresolved."""
    if declared_type != "s" or raw_value is None:
        return None, False
    if _INT_RE.fullmatch(raw_value) is None:
        return None, False
    index = int(raw_value)
    return index, index < len(shared)
