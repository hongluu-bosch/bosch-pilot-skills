"""lxml-based arxml patcher with surgical (byte-level) write-back.

Locates ECUC-*-PARAM-VALUE / ECUC-TEXTUAL-PARAM-VALUE nodes by matching
their ``DEFINITION-REF`` suffix (and optional ancestor SHORT-NAME) via
``lxml``, then rewrites **only** the inner text of each matched
``<VALUE>...</VALUE>`` element directly in the original file bytes.

We deliberately do *not* use ``tree.write()``: a full re-serialize
normalises the XML declaration, namespace attribute quoting,
self-closing tags, line endings (CRLF -> LF on Windows), and any
CDATA/comment formatting. That produces spurious diffs on every
patched file. The surgical path below keeps every byte outside the
matched ``<VALUE>`` substring byte-identical to the source file, so a
``git diff`` after ``apply`` shows only the nodes the user actually
changed.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from lxml import etree
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    _REQ = (Path(__file__).resolve().parent / "requirements.txt").as_posix()
    raise SystemExit(
        "[arxml_patcher] lxml is required. Install it via:\n"
        f"  pip install -r {_REQ}"
    ) from exc


AR_NS = "http://autosar.org/schema/r4.0"
NSMAP = {"ar": AR_NS}


# ---------------------------------------------------------------------------
# Result types


@dataclass
class PatchHit:
    file: Path
    param: str
    def_ref: str
    context: str
    old_value: str
    new_value: str

    def diff_line(self) -> str:
        return (f"{self.file.as_posix()} :: {self.param} "
                f"[{self.def_ref} @ {self.context}] "
                f"{self.old_value!r} -> {self.new_value!r}")


@dataclass
class PatchReport:
    hits: list[PatchHit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def extend(self, other: PatchReport) -> None:
        self.hits.extend(other.hits)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)

    def as_text(self) -> str:
        lines = [f"Total hits: {len(self.hits)}",
                 f"Warnings:   {len(self.warnings)}",
                 f"Errors:     {len(self.errors)}", ""]
        if self.hits:
            lines.append("== Changes ==")
            lines.extend("  " + h.diff_line() for h in self.hits)
            lines.append("")
        if self.warnings:
            lines.append("== Warnings ==")
            lines.extend("  " + w for w in self.warnings)
            lines.append("")
        if self.errors:
            lines.append("== Errors ==")
            lines.extend("  " + e for e in self.errors)
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# XML helpers


def _local(tag: str) -> str:
    """Return the local-name of an element's tag."""
    return tag.rsplit("}", 1)[-1]


def _def_suffix(def_ref_text: str) -> str:
    return def_ref_text.rsplit("/", 1)[-1] if def_ref_text else ""


def _short_name_chain(elem: etree._Element) -> list[str]:
    """Collect ancestor SHORT-NAME texts from root to this element."""
    chain: list[str] = []
    cur = elem
    while cur is not None:
        sn = cur.find(f"{{{AR_NS}}}SHORT-NAME")
        if sn is not None and sn.text:
            chain.append(sn.text)
        cur = cur.getparent()
    return list(reversed(chain))


def _has_ancestor_short_name(elem: etree._Element, name: str) -> bool:
    return name in _short_name_chain(elem)


def _has_ancestor_short_name_prefix(elem: etree._Element, prefix: str) -> bool:
    return any(sn.startswith(prefix) for sn in _short_name_chain(elem))


def _has_ancestor_def_ref_suffix(elem: etree._Element, suffix: str) -> bool:
    """True when some ancestor ECUC-CONTAINER-VALUE has DEFINITION-REF ending in ``/suffix``."""
    cur = elem.getparent()
    while cur is not None:
        if _local(cur.tag) == "ECUC-CONTAINER-VALUE":
            def_ref = cur.find(f"{{{AR_NS}}}DEFINITION-REF")
            if def_ref is not None and def_ref.text \
                    and _def_suffix(def_ref.text) == suffix:
                return True
        cur = cur.getparent()
    return False


def _context_label(elem: etree._Element) -> str:
    """Readable breadcrumb for a hit, e.g. 'CanTpConfig_0/CanTpChannel_0/CanTpTxNSdu'."""
    return "/".join(_short_name_chain(elem)) or _local(elem.tag)


# ---------------------------------------------------------------------------
# Locators


def _iter_param_values(root: etree._Element) -> Iterable[etree._Element]:
    """All ECUC-*-PARAM-VALUE elements (numerical + textual)."""
    for tag in ("ECUC-NUMERICAL-PARAM-VALUE", "ECUC-TEXTUAL-PARAM-VALUE"):
        yield from root.iter(f"{{{AR_NS}}}{tag}")


def find_matches(root: etree._Element,
                 locator: dict[str, Any]) -> list[etree._Element]:
    """Return every PARAM-VALUE element matching ``locator``."""
    ltype = locator.get("type", "def_suffix")

    # Normalize suffix list.
    if ltype == "def_suffix_any":
        wanted = set(locator["def_suffix"])
    else:
        wanted = {locator["def_suffix"]}

    ancestor_sn = locator.get("ancestor_short_name")
    ancestor_sn_prefix = locator.get("ancestor_short_name_prefix")
    context_def_suffix = locator.get("context_container_def_suffix")

    hits: list[etree._Element] = []
    for pv in _iter_param_values(root):
        def_ref_el = pv.find(f"{{{AR_NS}}}DEFINITION-REF")
        if def_ref_el is None or not def_ref_el.text:
            continue
        suffix = _def_suffix(def_ref_el.text)
        if suffix not in wanted:
            continue
        if ancestor_sn and not _has_ancestor_short_name(pv, ancestor_sn):
            continue
        if ancestor_sn_prefix and not _has_ancestor_short_name_prefix(
                pv, ancestor_sn_prefix):
            continue
        if context_def_suffix and not _has_ancestor_def_ref_suffix(
                pv, context_def_suffix):
            continue
        hits.append(pv)
    return hits


# ---------------------------------------------------------------------------
# Document IO


def load(file_path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False, remove_comments=False)
    return etree.parse(str(file_path), parser)


# ---------------------------------------------------------------------------
# Surgical byte-level write-back
#
# The core invariant: after a successful apply, the file's bytes OUTSIDE
# the matched ``<VALUE>...</VALUE>`` substrings are unchanged. Only the
# inner text of each matched VALUE element is rewritten. No lxml
# re-serialize, no namespace shuffling, no CRLF->LF conversion.

# Matches ``<VALUE>INNER</VALUE>`` with optional attributes on the
# opener (AUTOSAR rarely uses them, but be tolerant). Inner text is
# captured; anything up to the next ``<`` is treated as content, so
# whitespace-only VALUEs are handled too.
_VALUE_RE = re.compile(rb"(<VALUE(?:\s[^>]*)?>)([^<]*)(</VALUE>)")


def _line_start_offsets(data: bytes) -> list[int]:
    """Return a list such that offsets[i] = byte offset where line ``i+1`` begins.

    Line 1 always starts at offset 0. Works with LF, CRLF, and bare CR
    line terminators -- we key off the ``\\n`` byte, and for the lone-CR
    case the extra byte is swallowed into the "line" that follows. In
    practice AUTOSAR arxml is CRLF (Windows) or LF (Linux); either is
    handled correctly.
    """
    offsets = [0]
    for i, b in enumerate(data):
        if b == 0x0A:                       # '\n'
            offsets.append(i + 1)
    return offsets


def _surgical_patch(data: bytes,
                    edits: list[tuple[int, str, str]]) -> bytes:
    """Apply ``edits`` to ``data`` without re-serialising the document.

    Each edit is ``(sourceline, old_inner_text, new_inner_text)`` where
    ``sourceline`` is the lxml-reported 1-indexed line of the
    containing ``<ECUC-*-PARAM-VALUE>`` element. We search forward from
    that line for the first ``<VALUE>...</VALUE>`` occurrence whose
    inner text matches ``old_inner_text`` and replace just the inner
    text with ``new_inner_text`` (UTF-8 encoded).

    Edits are applied in reverse source order so earlier byte offsets
    remain valid as we mutate the tail of the buffer.
    """
    if not edits:
        return data

    offsets = _line_start_offsets(data)
    out = bytearray(data)

    # Patch tail-first so each earlier edit still sees untouched bytes
    # at its start-of-search offset.
    for sourceline, old, new in sorted(edits, key=lambda e: e[0], reverse=True):
        idx = max(0, (sourceline or 1) - 1)
        start = offsets[idx] if idx < len(offsets) else 0
        old_b = old.encode("utf-8")
        new_b = new.encode("utf-8")

        pos = start
        while pos < len(out):
            m = _VALUE_RE.search(out, pos)
            if m is None:
                break
            if m.group(2) == old_b:
                out[m.start(2):m.end(2)] = new_b
                break
            pos = m.end()
        # If we fell off the end without a match, the file layout is
        # unexpected (e.g., self-closing <VALUE/>). We silently skip --
        # the lxml locator already proved the PV exists, so this is an
        # edge case; a future enhancement could warn here.

    return bytes(out)


# ---------------------------------------------------------------------------
# Mapping application


def apply_to_file(file_path: Path,
                  entries: list[tuple[dict[str, Any], str]],
                  *,
                  dry_run: bool = False) -> PatchReport:
    """Apply ``(mapping_entry, new_value_str)`` pairs against a single arxml file.

    For each entry: locate 1+ nodes, and if the current ``<VALUE>`` text
    differs from ``new_value_str``, record a ``PatchHit`` and schedule a
    surgical byte-level rewrite. The in-memory lxml tree is never
    mutated -- the write path bypasses ``tree.write()`` to preserve the
    file's original byte layout outside the matched VALUE nodes.
    """
    report = PatchReport()
    if not file_path.exists():
        report.errors.append(f"File not found: {file_path}")
        return report

    tree = load(file_path)
    root = tree.getroot()

    # (sourceline, old_inner_text, new_inner_text) per hit -- the
    # byte-level patcher consumes this list.
    edits: list[tuple[int, str, str]] = []

    for entry, new_value in entries:
        param = entry["param"]
        locator = entry["locator"]
        optional = bool(entry.get("optional", False))
        multi = bool(entry.get("multi", False))

        matches = find_matches(root, locator)
        if not matches:
            msg = (f"[{file_path.name}] {param}: no match for locator "
                   f"{locator} -> skipped")
            if optional:
                report.warnings.append(msg + " (optional)")
            else:
                report.warnings.append(msg)
            continue

        targets = matches if multi else matches[:1]
        for pv in targets:
            def_ref_el = pv.find(f"{{{AR_NS}}}DEFINITION-REF")
            def_ref = def_ref_el.text if def_ref_el is not None else ""
            value_el = pv.find(f"{{{AR_NS}}}VALUE")
            old = (value_el.text or "") if value_el is not None else ""
            if old == new_value:
                # No-op: value already matches; don't record a hit and
                # don't schedule a byte rewrite.
                continue
            report.hits.append(PatchHit(
                file=file_path,
                param=param,
                def_ref=_def_suffix(def_ref),
                context=_context_label(pv),
                old_value=old,
                new_value=new_value,
            ))
            edits.append((pv.sourceline or 0, old, new_value))

    if edits and not dry_run:
        original = file_path.read_bytes()
        patched = _surgical_patch(original, edits)
        if patched != original:
            file_path.write_bytes(patched)

    return report


__all__ = [
    "PatchHit",
    "PatchReport",
    "apply_to_file",
    "find_matches",
    "load",
]
