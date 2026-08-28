import argparse
import datetime as dt
import hashlib
from html import escape, unescape
import json
import os
from datetime import timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


REQUIRED_MD_HEADINGS = [
    "## Summary",
    "## Confirmed Findings",
    "## Open Questions",
    "## Suspected But Unconfirmed Issues",
    "## Risk Summary",
    "## Suggested Next Actions",
]

HTML_REPORT_VARIANTS = {
    "en": {
        "suffix": ".html",
        "defaultTitle": "Static Code Review Report",
        "metadataLabels": {
            "date": "Date",
            "ruleVersion": "Rule Version",
            "aiModel": "AI Model",
        },
        "requiredSnippets": [
            "Confirmed Findings",
            "Open Questions",
            "Suspected But Unconfirmed Issues",
            "Risk Summary",
            "Suggested Next Actions",
            "Function",
            "Location",
            "Evidence",
            "Functional Impact",
            "Reasoning",
            "Suggested Action",
            "Rule Version",
            "AI Model",
        ],
    },
    "zh-CN": {
        "suffix": ".zh-CN.html",
        "defaultTitle": "静态代码审查报告",
        "metadataLabels": {
            "date": "日期",
            "ruleVersion": "规则版本",
            "aiModel": "AI 模型",
        },
        "requiredSnippets": [
            "已确认问题",
            "待确认问题",
            "疑似但未确认的问题",
            "风险总结",
            "建议的后续操作",
            "函数",
            "位置",
            "证据",
            "功能影响",
            "定级理由",
            "建议操作",
            "规则版本",
            "AI 模型",
        ],
    },
}

DEFAULT_REPORT_BASE_NAME = "static-code-review-report.current-file"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path: Path):
    return path.read_text(encoding="utf-8")


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write(path: Path, content: str):
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent), newline="\n") as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload):
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def existing_report_set_paths(report_base: Path):
    html_paths = html_report_paths(report_base)
    report_paths = [path for path in html_paths.values()]
    markdown_path = artifact_path(report_base, ".md")
    report_paths.append(markdown_path)
    return [path for path in report_paths if path.exists()]


def build_archived_report_path(archive_root: Path, original_path: Path, archive_stamp: str) -> Path:
    if original_path.name.endswith(".zh-CN.html"):
        base_name = original_path.name[: -len(".zh-CN.html")]
        archived_name = f"{base_name}.archived.{archive_stamp}.zh-CN.html"
    else:
        archived_name = f"{original_path.stem}.archived.{archive_stamp}{original_path.suffix}"
    return archive_root / archived_name


def archive_existing_report_sets(report_bases):
    existing_paths = []
    seen_paths = set()

    for report_base in report_bases:
        for path in existing_report_set_paths(report_base):
            normalized = str(path.resolve())
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            existing_paths.append(path)

    if not existing_paths:
        return None

    archive_dir = report_base.parent / "archive"
    ensure_dir(archive_dir)
    archive_stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    moved_files = []

    for path in existing_paths:
        destination = build_archived_report_path(archive_dir, path, archive_stamp)
        shutil.move(str(path), str(destination))
        moved_files.append(str(destination))

    return {
        "archiveDir": str(archive_dir),
        "movedFiles": moved_files,
    }


def archive_existing_report_set(report_base: Path):
    return archive_existing_report_sets([report_base])


def utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def parse_utc_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_report_timestamp(value: str) -> str:
    return parse_utc_iso(value).strftime("%Y-%m-%d %H:%M:%S UTC")


def source_metadata(source_path: Path):
    resolved = source_path.resolve()
    return {
        "sourcePath": str(resolved),
        "sourceSha256": sha256_text(resolved.read_text(encoding="utf-8")),
        "sourceModifiedAt": dt.datetime.fromtimestamp(resolved.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def review_input_metadata(review_input_path: Path, review_text: str):
    resolved = review_input_path.resolve()
    return {
        "reviewInputPath": str(resolved),
        "reviewInputSha256": sha256_text(review_text),
    }


def skip_c_trivia(text: str, index: int) -> int:
    length = len(text)
    while index < length:
        if text.startswith("//", index):
            newline_index = text.find("\n", index)
            if newline_index == -1:
                return length
            index = newline_index + 1
            continue
        if text.startswith("/*", index):
            comment_end = text.find("*/", index + 2)
            if comment_end == -1:
                return length
            index = comment_end + 2
            continue
        if text[index].isspace():
            index += 1
            continue
        break
    return index


def find_matching_delimiter(text: str, start_index: int, opening: str, closing: str) -> int:
    depth = 0
    index = start_index
    length = len(text)

    while index < length:
        if text.startswith("//", index):
            newline_index = text.find("\n", index)
            if newline_index == -1:
                return -1
            index = newline_index + 1
            continue
        if text.startswith("/*", index):
            comment_end = text.find("*/", index + 2)
            if comment_end == -1:
                return -1
            index = comment_end + 2
            continue
        if text[index] in {'"', "'"}:
            quote = text[index]
            index += 1
            while index < length:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == quote:
                    index += 1
                    break
                index += 1
            continue
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1

    return -1


def find_function_start(text: str, match_start: int) -> int:
    boundary_index = -1
    for token in [";", "}"]:
        token_index = text.rfind(token, 0, match_start)
        if token_index > boundary_index:
            boundary_index = token_index

    start_index = 0 if boundary_index == -1 else boundary_index + 1
    while start_index < len(text) and text[start_index] in "\r\n\t ":
        start_index += 1
    return start_index


def extract_c_function_text(source_text: str, function_name: str) -> str:
    pattern = re.compile(r"\b" + re.escape(function_name) + r"\s*\(")
    matches = list(pattern.finditer(source_text))
    if not matches:
        raise ValueError(f"Function '{function_name}' was not found in the source file.")

    for match in matches:
        params_open = source_text.find("(", match.start())
        params_close = find_matching_delimiter(source_text, params_open, "(", ")")
        if params_open == -1 or params_close == -1:
            continue

        body_start = skip_c_trivia(source_text, params_close + 1)
        if body_start >= len(source_text) or source_text[body_start] != "{":
            continue

        body_end = find_matching_delimiter(source_text, body_start, "{", "}")
        if body_end == -1:
            continue

        function_start = find_function_start(source_text, match.start())
        return source_text[function_start:body_end + 1].strip() + "\n"

    raise ValueError(f"Function '{function_name}' was found, but no function definition body could be extracted.")


def materialize_function_review_input(source_path: Path, function_name: str, source_text: str):
    extracted_text = extract_c_function_text(source_text, function_name)
    temp_dir = Path(tempfile.gettempdir()) / "kimi-review-scope"
    ensure_dir(temp_dir)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", function_name)
    ext = source_path.suffix.lower()
    scope_ext = ext if ext in (".c", ".h", ".cpp", ".cxx", ".cc", ".c++", ".hpp", ".hxx", ".h++") else ".c"
    temp_path = temp_dir / f"{source_path.stem}.{safe_name}.scope{scope_ext}"
    atomic_write(temp_path, extracted_text)
    return temp_path, extracted_text


def detect_review_language(source_path: str) -> str:
    ext = Path(source_path).suffix.lower()
    if ext in (".c", ".h"):
        return "c"
    if ext in (".cpp", ".cxx", ".cc", ".c++", ".hpp", ".hxx", ".h++"):
        return "cpp"
    return "generic"


def build_scope_label(scope_kind: str, scope_name: str, source_path: Path) -> str:
    if scope_kind == "function" and scope_name:
        return f"Function `{scope_name}`"
    if scope_kind == "selection" and scope_name:
        return f"Selection `{scope_name}`"
    if scope_kind == "selection":
        return "Selected code"
    return source_path.name


def sanitize_report_name_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "")
    cleaned = cleaned.strip("._-")
    return cleaned or "unnamed"


def derive_scope_subject(scope_kind: str = "file", scope_name: str = "", source_path=None, scope_label: str = "") -> str:
    if scope_kind == "function" and scope_name:
        return scope_name.strip()
    if scope_kind == "selection" and scope_name:
        return scope_name.strip()

    cleaned_label = strip_wrapping_backticks((scope_label or "").strip())
    if cleaned_label.startswith("Function "):
        return strip_wrapping_backticks(cleaned_label[len("Function "):].strip())
    if cleaned_label.startswith("Selection "):
        return strip_wrapping_backticks(cleaned_label[len("Selection "):].strip())
    if cleaned_label and cleaned_label != "Selected code":
        return cleaned_label

    if source_path:
        return Path(source_path).name

    if scope_name:
        return scope_name.strip()

    return ""


def derive_report_file_subject(scope_kind: str = "file", scope_name: str = "", source_path=None) -> str:
    subject = derive_scope_subject(scope_kind=scope_kind, scope_name=scope_name, source_path=source_path)
    if not subject and scope_kind == "selection":
        subject = "selected-code"
    return sanitize_report_name_component(subject)


def derive_default_report_base_prefix(config) -> str:
    return config.get("defaultReportBaseName", DEFAULT_REPORT_BASE_NAME)


def format_report_filename_timestamp(value: str) -> str:
    return parse_utc_iso(value).strftime("%Y%m%d-%H%M%S")


def derive_default_report_base_name(config, generated_at: str, source_path=None, scope_kind: str = "file", scope_name: str = "") -> str:
    prefix = derive_default_report_base_prefix(config)
    subject = derive_report_file_subject(scope_kind=scope_kind, scope_name=scope_name, source_path=source_path)
    timestamp = format_report_filename_timestamp(generated_at)
    return f"{prefix}.{subject}.{timestamp}"


def report_base_name_matches(base_name: str, prefix: str, subject_key: str = "") -> bool:
    if subject_key:
        return bool(re.fullmatch(r"^" + re.escape(prefix) + r"\." + re.escape(subject_key) + r"\.\d{8}-\d{6}$", base_name))

    return bool(
        base_name == prefix
        or re.fullmatch(r"^" + re.escape(prefix) + r"\.\d{8}-\d{6}$", base_name)
        or re.fullmatch(r"^" + re.escape(prefix) + r"\..+\.\d{8}-\d{6}$", base_name)
    )


def find_matching_report_bases(report_dir: Path, prefix: str, require_complete: bool = True, subject_key: str = ""):
    matches = []

    for html_path in report_dir.glob("*.html"):
        if html_path.name.endswith(".zh-CN.html"):
            continue

        base_name = html_path.stem
        if not report_base_name_matches(base_name, prefix, subject_key):
            continue

        report_base = report_dir / base_name
        report_paths = existing_report_set_paths(report_base)
        if require_complete and len(report_paths) < len(HTML_REPORT_VARIANTS):
            continue
        if not report_paths:
            continue

        timestamps = [path.stat().st_mtime for path in report_paths]
        matches.append((max(timestamps), report_base))

    matches.sort(key=lambda item: item[0], reverse=True)
    return [report_base for _, report_base in matches]


def find_all_report_bases(report_dir: Path):
    matches = []
    seen = set()

    candidate_paths = list(report_dir.glob("*.html")) + list(report_dir.glob("*.md"))

    for candidate_path in candidate_paths:
        if candidate_path.name.endswith(".zh-CN.html"):
            continue

        report_base = report_dir / candidate_path.stem
        normalized = str(report_base.resolve())
        if normalized in seen:
            continue

        report_paths = existing_report_set_paths(report_base)
        if not report_paths:
            continue

        seen.add(normalized)
        timestamps = [path.stat().st_mtime for path in report_paths]
        matches.append((max(timestamps), report_base))

    matches.sort(key=lambda item: item[0], reverse=True)
    return [report_base for _, report_base in matches]


def resolve_report_base_name(requested_report_base: str, config, source_path=None, scope_kind: str = "file", scope_name: str = "", report_dir: Path = None, generated_at: str = "", prefer_latest: bool = False) -> str:
    default_report_base = config.get("defaultReportBaseName", DEFAULT_REPORT_BASE_NAME)
    effective_report_base = requested_report_base or default_report_base

    if effective_report_base != default_report_base:
        return effective_report_base

    prefix = derive_default_report_base_prefix(config)
    subject_key = derive_report_file_subject(scope_kind=scope_kind, scope_name=scope_name, source_path=source_path)

    if prefer_latest and report_dir:
        matches = find_matching_report_bases(report_dir, prefix, require_complete=False, subject_key=subject_key)
        if not matches:
            matches = find_matching_report_bases(report_dir, prefix, require_complete=False)
        if matches:
            return matches[0].name

    if generated_at:
        return derive_default_report_base_name(
            config,
            generated_at,
            source_path=source_path,
            scope_kind=scope_kind,
            scope_name=scope_name,
        )

    return prefix


def resolve_review_scope(args):
    source_path = Path(args.source).resolve()
    scope_kind = getattr(args, "scope_kind", "file")
    scope_name = (getattr(args, "scope_name", "") or "").strip()
    source_text = read_text(source_path)

    if scope_kind == "function" and not scope_name:
        raise ValueError("--scope-name is required when --scope-kind=function.")

    if getattr(args, "review_input", None):
        review_input_path = Path(args.review_input).resolve()
        review_text = read_text(review_input_path)
    elif scope_kind == "function":
        review_input_path, review_text = materialize_function_review_input(source_path, scope_name, source_text)
    else:
        review_input_path = source_path
        review_text = source_text

    return {
        "sourcePath": source_path,
        "reviewInputPath": review_input_path,
        "reviewText": review_text,
        "scopeKind": scope_kind,
        "scopeName": scope_name,
        "scopeLabel": build_scope_label(scope_kind, scope_name, source_path),
    }


def build_scope_prompt_lines(review_scope) -> str:
    lines = [
        f"- Source file: {review_scope['sourcePath']}",
        f"- Review scope kind: {review_scope['scopeKind']}",
        f"- Review scope label: {review_scope['scopeLabel']}",
    ]
    if review_scope["scopeName"]:
        lines.append(f"- Review scope name: {review_scope['scopeName']}")
    if review_scope["reviewInputPath"] != review_scope["sourcePath"]:
        lines.append(f"- Review input path: {review_scope['reviewInputPath']}")
    return "\n".join(lines)


def build_scope_review_instructions(review_scope) -> str:
    if review_scope["scopeKind"] == "function":
        return (
            f"Review only the function `{review_scope['scopeName']}` from the provided review input. "
            "Ignore every other function even if the source file contains additional code. "
            "If the named function is not present in the review input, return no findings instead of widening scope."
        )
    if review_scope["scopeKind"] == "selection":
        return (
            "Review only the selected code block from the provided review input. "
            "Do not widen scope to surrounding functions or the rest of the file."
        )
    return "Review the provided source file as a file-level review."


def file_modified_iso(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def compact_rules_text(config) -> str:
    lines = []
    for rule in config.get("compactRuleReferences", []):
        lines.append(f"- {rule['id']}: {rule['title']} -- {rule['guidance']}")
    return "\n".join(lines)


def resolve_rule_version(config) -> str:
    return config.get("ruleVersion") or config.get("promptVersion", "unknown")


def resolve_ai_model(config) -> str:
    model_id = (
        os.environ.get("KIMI_MODEL")
        or os.environ.get("MOONSHOT_MODEL")
        or config.get("api", {}).get("model")
        or "unknown"
    )
    display_name = config.get("aiModelDisplayName")
    if display_name:
        return display_name
    return model_id


def default_report_title(config, language: str) -> str:
    report_titles = config.get("reportTitles", {})
    report_title = report_titles.get(language)
    if report_title:
        return report_title
    if language == "en":
        return config.get("reportTitle", HTML_REPORT_VARIANTS[language]["defaultTitle"])
    return HTML_REPORT_VARIANTS[language]["defaultTitle"]


def derive_scope_label(source_arg: str, markdown: str, fallback: str) -> str:
    patterns = [
        r"^-\s+Scope:\s*(.+)$",
        r"^File:\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, markdown, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()

    if source_arg:
        return Path(source_arg).name

    return fallback


def resolve_effective_scope_label(preferred_scope_label: str, source_arg: str, markdown: str, fallback: str) -> str:
    if preferred_scope_label:
        return preferred_scope_label
    return derive_scope_label(source_arg, markdown, fallback)


def localize_scope_label(scope_label: str, language: str) -> str:
    if language != "zh-CN":
        return scope_label

    function_match = re.fullmatch(r"Function\s+(`.+?`)", scope_label)
    if function_match:
        return f"函数 {function_match.group(1)}"

    selection_match = re.fullmatch(r"Selection\s+(`.+?`)", scope_label)
    if selection_match:
        return f"选区 {selection_match.group(1)}"

    if scope_label == "Selected code":
        return "选中代码"

    return scope_label


def derive_report_subject(source_arg: str = "", fallback_label: str = "") -> str:
    fallback = derive_scope_subject(scope_label=fallback_label)
    if fallback:
        return fallback

    if source_arg:
        return Path(source_arg).name

    return ""


def build_report_title(config, language: str, source_arg: str = "", scope_label: str = "") -> str:
    report_subject = derive_report_subject(source_arg, scope_label)
    if not report_subject:
        return default_report_title(config, language)
    return f"{default_report_title(config, language)} - {report_subject}"


def build_markdown_report_title(config, source_arg: str = "", scope_label: str = "") -> str:
    return build_report_title(config, "en", source_arg, scope_label)


def html_report_paths(report_base: Path):
    return {
        language: artifact_path(report_base, variant["suffix"])
        for language, variant in HTML_REPORT_VARIANTS.items()
    }


def set_html_title(html: str, title: str) -> str:
    title_tag = f"<title>{escape(title)}</title>"
    if re.search(r"<title>.*?</title>", html, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(r"<title>.*?</title>", title_tag, html, count=1, flags=re.IGNORECASE | re.DOTALL)
    if re.search(r"</head>", html, flags=re.IGNORECASE):
        return re.sub(r"</head>", f"  {title_tag}\n</head>", html, count=1, flags=re.IGNORECASE)
    return title_tag + "\n" + html


def set_first_h1(html: str, title: str) -> str:
    heading = f"<h1>{escape(title)}</h1>"
    if re.search(r"<h1\b[^>]*>.*?</h1>", html, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(r"<h1\b[^>]*>.*?</h1>", heading, html, count=1, flags=re.IGNORECASE | re.DOTALL)
    return html


def inject_html_metadata(html: str, config, language: str, generated_at: str) -> str:
    labels = HTML_REPORT_VARIANTS[language]["metadataLabels"]
    date_value = escape(format_report_timestamp(generated_at))
    rule_version = escape(resolve_rule_version(config))
    ai_model = escape(resolve_ai_model(config))
    metadata_markup = (
        f"<span><strong>{labels['date']}:</strong> {date_value}</span>"
        f"<span><strong>{labels['ruleVersion']}:</strong> {rule_version}</span>"
        f"<span><strong>{labels['aiModel']}:</strong> {ai_model}</span>"
    )

    html = re.sub(
        r"<span><strong>(Date|日期):</strong>.*?</span>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"<span><strong>(Rule Version|规则版本):</strong>.*?</span>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"<span><strong>(AI Model|AI 模型):</strong>.*?</span>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if re.search(r"<div\b[^>]*class=\"[^\"]*meta[^\"]*\"[^>]*>", html, flags=re.IGNORECASE):
        return re.sub(
            r"(<div\b[^>]*class=\"[^\"]*meta[^\"]*\"[^>]*>)(.*?)(</div>)",
            lambda match: f"{match.group(1)}{match.group(2)}{metadata_markup}{match.group(3)}",
            html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

    if re.search(r"</h1>", html, flags=re.IGNORECASE):
        meta_block = f"\n      <div class=\"meta\">{metadata_markup}</div>"
        return re.sub(r"</h1>", f"</h1>{meta_block}", html, count=1, flags=re.IGNORECASE)

    return html


def ensure_html_metadata_styles(html: str) -> str:
    style_block = """
  <style>
    .meta {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 14px;
      opacity: 1;
    }
    .meta span {
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: #eef4fb;
      color: #173a5e;
      border: 1px solid #c8d8ea;
    }
    .meta strong {
      color: #173a5e;
    }
        .meta code {
            background: #dbe7f3;
            color: #173a5e;
            border: 1px solid #bfd0e3;
        }
    .header .meta span {
            background: rgba(15, 23, 42, 0.42);
            color: #f8fbff;
            border: 1px solid rgba(255, 255, 255, 0.18);
    }
    .header .meta strong {
      color: #ffffff;
    }
        .header .meta code {
            background: rgba(15, 23, 42, 0.72);
            color: #ffffff;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }
  </style>
"""

    if ".header .meta span" in html or ".meta span" in html:
        return html

    if re.search(r"</head>", html, flags=re.IGNORECASE):
        return re.sub(r"</head>", style_block + "</head>", html, count=1, flags=re.IGNORECASE)

    return style_block + html


def normalize_markdown_report(markdown: str, config, generated_at: str, source_arg: str = "") -> str:
    report_subject = derive_report_subject(source_arg)
    markdown_title = build_markdown_report_title(config, source_arg)
    file_line = f"File: {report_subject}" if report_subject else ""
    date_line = f"Date: {format_report_timestamp(generated_at)}"
    rule_version_line = f"Rule Version: {resolve_rule_version(config)}"
    ai_model_line = f"AI Model: {resolve_ai_model(config)}"

    metadata_lines = [line for line in [file_line, date_line, rule_version_line, ai_model_line] if line]
    normalized = re.sub(
        r"^(File|Scope|Date|Rule Version|AI Model):\s*.+$\n?",
        "",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    normalized = re.sub(
        r"^#\s+.+$",
        f"# {markdown_title}",
        normalized,
        count=1,
        flags=re.MULTILINE,
    )

    normalized = apply_display_severity_filter_to_markdown(normalized, config)

    if not metadata_lines:
        return normalized

    return re.sub(
        r"^(#\s+.+)$",
        lambda match: f"{match.group(1)}\n\n" + "\n".join(metadata_lines),
        normalized,
        count=1,
        flags=re.MULTILINE,
    )


def get_markdown_section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        r"^##\s+" + re.escape(heading) + r"\s*$\n?(.*?)(?=^##\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    if not match:
        raise ValueError(f"Markdown report is missing section body for heading: {heading}")
    return match.group(1).strip()


def markdown_inline_to_html(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    rendered = []
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            rendered.append(f"<code>{escape(part[1:-1])}</code>")
        else:
            rendered.append(escape(part))
    return "".join(rendered)


def normalize_field_key(label: str) -> str:
    normalized = re.sub(r"\s+", " ", label.strip().lower())
    return normalized


def strip_wrapping_backticks(text: str) -> str:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped.startswith("`") and stripped.endswith("`"):
        return stripped[1:-1].strip()
    return stripped


def markdown_field_pattern() -> str:
    return r"^-\s+\*\*(.+?)(?::)?\*\*:?\s*(.*)$"


def extract_field_value_lines(lines, start_index: int):
    match = re.match(markdown_field_pattern(), lines[start_index])
    field_name = normalize_field_key(match.group(1))
    initial_value = match.group(2).strip()
    values = []
    if initial_value:
        values.append(initial_value)

    index = start_index + 1
    while index < len(lines):
        line = lines[index]
        if re.match(markdown_field_pattern(), line):
            break
        if line.strip():
            values.append(line.rstrip())
        index += 1

    return field_name, values, index


def clean_field_lines(values):
    cleaned = []
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            cleaned.append(stripped[2:].strip())
        else:
            cleaned.append(stripped)
    return cleaned


def parse_markdown_finding_block(block: str, severity: str, title: str):
    lines = [line.rstrip() for line in block.strip().splitlines() if line.strip()]
    fields = {}
    index = 0
    while index < len(lines):
        if not re.match(markdown_field_pattern(), lines[index]):
            index += 1
            continue
        field_name, values, next_index = extract_field_value_lines(lines, index)
        fields[field_name] = clean_field_lines(values)
        index = next_index

    required_field_map = {
        "function": "Function",
        "location": "Location",
        "evidence": "Evidence",
        "functional impact": "Functional Impact",
        "reasoning": "Reasoning",
        "suggested action": "Suggested Action",
    }
    for field_key, field_label in required_field_map.items():
        if field_key not in fields:
            raise ValueError(f"Markdown confirmed finding is missing required field content: {field_label}")

    return {
        "severity": severity.lower(),
        "title": title.strip(),
        "function": strip_wrapping_backticks(fields["function"][0]),
        "location": " ".join(fields["location"]),
        "evidence": fields["evidence"],
        "functionalImpact": " ".join(fields["functional impact"]),
        "reasoning": " ".join(fields["reasoning"]),
        "suggestedAction": fields["suggested action"],
    }


def parse_markdown_confirmed_findings(markdown: str):
    section = get_markdown_section(markdown, "Confirmed Findings")
    if re.fullmatch(r"None\.?", section, flags=re.IGNORECASE):
        return []

    pattern = re.compile(
        r"^###\s+(critical|major|minor|info)\s+-\s+(.+?)\s*$\n?(.*?)(?=^###\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    findings = []
    for match in pattern.finditer(section):
        findings.append(parse_markdown_finding_block(match.group(3), match.group(1), match.group(2)))
    return findings


def severity_rank(severity: str) -> int:
    order = {
        "info": 0,
        "minor": 1,
        "major": 2,
        "critical": 3,
    }
    return order.get((severity or "").lower(), -1)


def minimum_displayed_severity(config) -> str:
    return str(config.get("defaultMinimumDisplayedSeverity", "major")).lower()


def filter_findings_by_threshold(findings, config):
    threshold = minimum_displayed_severity(config)
    threshold_rank = severity_rank(threshold)
    if threshold_rank < 0:
        threshold_rank = severity_rank("major")
    return [finding for finding in findings if severity_rank(finding.get("severity", "")) >= threshold_rank]


def summarize_findings(findings):
    summary = {"total": 0, "critical": 0, "major": 0, "minor": 0, "info": 0}
    for finding in findings:
        severity = (finding.get("severity") or "").lower()
        if severity in summary:
            summary[severity] += 1
            summary["total"] += 1
    return summary


def format_markdown_finding(finding) -> str:
    evidence_lines = "\n".join(f"- {item}" for item in finding["evidence"])
    suggested_action_lines = "\n".join(f"- {item}" for item in finding["suggestedAction"])
    severity = finding["severity"].lower()
    return (
        f"### {severity} - {finding['title']}\n\n"
        f"- **Function**: {finding['function']}\n"
        f"- **Location**: {finding['location']}\n"
        f"- **Evidence**:\n{evidence_lines}\n"
        f"- **Functional Impact**: {finding['functionalImpact']}\n"
        f"- **Reasoning**: {finding['reasoning']}\n"
        f"- **Suggested Action**:\n{suggested_action_lines}"
    )


def replace_markdown_section(markdown: str, heading: str, new_body: str) -> str:
    pattern = re.compile(
        r"(^##\s+" + re.escape(heading) + r"\s*$\n?)(.*?)(?=^##\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    replacement = lambda match: match.group(1) + new_body.strip() + "\n\n"
    updated, count = pattern.subn(replacement, markdown, count=1)
    if count == 0:
        raise ValueError(f"Markdown report is missing section body for heading: {heading}")
    return updated


def apply_display_severity_filter_to_markdown(markdown: str, config) -> str:
    findings = parse_markdown_confirmed_findings(markdown)
    filtered_findings = filter_findings_by_threshold(findings, config)
    filtered_summary = summarize_findings(filtered_findings)

    summary_body = "\n".join([
        f"- Scope: {derive_report_subject('') or ''}",
        f"- Total findings: {filtered_summary['total']}",
        f"- Critical: {filtered_summary['critical']}",
        f"- Major: {filtered_summary['major']}",
        f"- Minor: {filtered_summary['minor']}",
        f"- Info: {filtered_summary['info']}",
    ])

    scope_match = re.search(r"^-\s+Scope:\s+(.+)$", get_markdown_section(markdown, "Summary"), re.IGNORECASE | re.MULTILINE)
    if scope_match:
        summary_body = "\n".join([
            f"- Scope: {scope_match.group(1).strip()}",
            f"- Total findings: {filtered_summary['total']}",
            f"- Critical: {filtered_summary['critical']}",
            f"- Major: {filtered_summary['major']}",
            f"- Minor: {filtered_summary['minor']}",
            f"- Info: {filtered_summary['info']}",
        ])

    findings_body = "\n\n".join(format_markdown_finding(finding) for finding in filtered_findings) if filtered_findings else "None."
    markdown = replace_markdown_section(markdown, "Summary", summary_body)
    markdown = replace_markdown_section(markdown, "Confirmed Findings", findings_body)
    return markdown


def parse_markdown_simple_list(section_text: str):
    stripped = section_text.strip()
    if not stripped:
        return []
    if re.fullmatch(r"None\.?", stripped, flags=re.IGNORECASE):
        return []

    items = []
    for line in stripped.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        bullet_match = re.match(r"^[-*]\s+(.+)$", cleaned)
        numbered_match = re.match(r"^\d+\.\s+(.+)$", cleaned)
        if bullet_match:
            items.append(bullet_match.group(1).strip())
        elif numbered_match:
            items.append(numbered_match.group(1).strip())
        else:
            items.append(cleaned)
    return items


def parse_markdown_paragraphs(section_text: str):
    stripped = section_text.strip()
    if not stripped:
        return []
    if re.fullmatch(r"None\.?", stripped, flags=re.IGNORECASE):
        return []
    return [paragraph.strip().replace("\n", " ") for paragraph in re.split(r"\n\s*\n", stripped) if paragraph.strip()]


def html_to_text_lines(html: str):
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<(br|p|/p|div|/div|section|/section|article|/article|header|/header|footer|/footer|li|/li|ul|/ul|ol|/ol|h1|/h1|h2|/h2|h3|/h3|h4|/h4|h5|/h5|h6|/h6)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li\b[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)
    text = unescape(text)
    lines = []
    for raw_line in text.splitlines():
        normalized = re.sub(r"\s+", " ", raw_line).strip()
        if normalized:
            lines.append(normalized)
    return lines


def extract_section_lines_from_html(html: str, current_title: str, all_titles):
    lines = html_to_text_lines(html)
    start_index = None
    for index, line in enumerate(lines):
        if line == current_title:
            start_index = index + 1
            break
    if start_index is None:
        return []

    section_lines = []
    other_titles = {title for title in all_titles if title != current_title}
    for line in lines[start_index:]:
        if line in other_titles:
            break
        section_lines.append(line)
    return section_lines


def parse_labeled_section_lines(lines, field_map):
    parsed = {target_key: [] for target_key in field_map.values()}
    current_key = None

    for line in lines:
        matched_key = None
        matched_value = ""
        for label, target_key in field_map.items():
            match = re.match(r"^" + re.escape(label) + r"\s*[:：]\s*(.*)$", line)
            if match:
                matched_key = target_key
                matched_value = match.group(1).strip()
                break

        if matched_key:
            current_key = matched_key
            if matched_value:
                parsed[current_key].append(matched_value)
            continue

        if current_key:
            parsed[current_key].append(line)

    return parsed


def normalize_text_list(lines):
    items = []
    for line in lines:
        cleaned = re.sub(r"^[-*•]\s*", "", line).strip()
        cleaned = re.sub(r"^\d+[\.)]\s*", "", cleaned).strip()
        if cleaned:
            items.append(cleaned)
    if len(items) == 1 and re.fullmatch(r"None\.?|无。?", items[0], flags=re.IGNORECASE):
        return []
    return items


def parse_localized_finding_section(lines, language: str):
    if not lines:
        return []

    if language == "zh-CN":
        severity_map = {"严重": "critical", "重要": "major", "次要": "minor", "提示": "info"}
        field_map = {
            "函数": "function",
            "位置": "location",
            "证据": "evidence",
            "功能影响": "functionalImpact",
            "定级理由": "reasoning",
            "建议操作": "suggestedAction",
        }
    else:
        severity_map = {"CRITICAL": "critical", "MAJOR": "major", "MINOR": "minor", "INFO": "info"}
        field_map = {
            "Function": "function",
            "Location": "location",
            "Evidence": "evidence",
            "Functional Impact": "functionalImpact",
            "Reasoning": "reasoning",
            "Suggested Action": "suggestedAction",
        }

    severity = "major"
    title = ""
    content_start = 0
    severity_labels = "|".join(re.escape(key) for key in severity_map)

    for index, line in enumerate(lines):
        if line in severity_map:
            severity = severity_map[line]
            continue
        split_match = re.match(r"^(" + severity_labels + r")\s*[-:：]\s*(.+)$", line)
        if split_match:
            severity = severity_map[split_match.group(1)]
            title = split_match.group(2).strip()
            content_start = index + 1
            break
        if line and not any(re.match(r"^" + re.escape(label) + r"\s*[:：]", line) for label in field_map):
            title = line
            content_start = index + 1
            break

    content_lines = lines[content_start:]
    parsed_fields = parse_labeled_section_lines(content_lines, field_map)
    if not title:
        title = lines[0]

    return [{
        "severity": severity,
        "title": title,
        "function": strip_wrapping_backticks(" ".join(parsed_fields.get("function", [])) or ""),
        "location": " ".join(parsed_fields.get("location", [])),
        "evidence": normalize_text_list(parsed_fields.get("evidence", [])),
        "functionalImpact": " ".join(parsed_fields.get("functionalImpact", [])),
        "reasoning": " ".join(parsed_fields.get("reasoning", [])),
        "suggestedAction": normalize_text_list(parsed_fields.get("suggestedAction", [])),
    }]


def build_localized_render_model_from_html(html: str, language: str):
    language_pack = house_report_language_pack(language)
    section_titles = list(language_pack["sections"].values())

    return {
        "findings": parse_localized_finding_section(
            extract_section_lines_from_html(html, language_pack["sections"]["findings"], section_titles),
            language,
        ),
        "openQuestions": normalize_text_list(
            extract_section_lines_from_html(html, language_pack["sections"]["openQuestions"], section_titles)
        ),
        "suspectedIssues": normalize_text_list(
            extract_section_lines_from_html(html, language_pack["sections"]["suspectedIssues"], section_titles)
        ),
        "riskSummary": normalize_text_list(
            extract_section_lines_from_html(html, language_pack["sections"]["riskSummary"], section_titles)
        ),
        "nextActions": normalize_text_list(
            extract_section_lines_from_html(html, language_pack["sections"]["nextActions"], section_titles)
        ),
    }


def merge_render_models(base_model, localized_model):
    if not localized_model:
        return base_model

    merged = dict(base_model)
    if localized_model.get("findings"):
        merged_findings = []
        for index, base_finding in enumerate(base_model["findings"]):
            localized_finding = localized_model["findings"][index] if index < len(localized_model["findings"]) else {}
            merged_findings.append({
                "severity": localized_finding.get("severity") or base_finding["severity"],
                "title": localized_finding.get("title") or base_finding["title"],
                "function": localized_finding.get("function") or base_finding["function"],
                "location": localized_finding.get("location") or base_finding["location"],
                "evidence": localized_finding.get("evidence") or base_finding["evidence"],
                "functionalImpact": localized_finding.get("functionalImpact") or base_finding["functionalImpact"],
                "reasoning": localized_finding.get("reasoning") or base_finding["reasoning"],
                "suggestedAction": localized_finding.get("suggestedAction") or base_finding["suggestedAction"],
            })
        merged["findings"] = merged_findings

    for key in ["openQuestions", "suspectedIssues", "riskSummary", "nextActions"]:
        if localized_model.get(key):
            merged[key] = localized_model[key]

    return merged


def build_report_render_model(markdown: str, scope_label: str):
    summary = parse_summary_counts(markdown)
    return {
        "scopeLabel": scope_label,
        "summary": summary,
        "findings": parse_markdown_confirmed_findings(markdown),
        "openQuestions": parse_markdown_simple_list(get_markdown_section(markdown, "Open Questions")),
        "suspectedIssues": parse_markdown_simple_list(get_markdown_section(markdown, "Suspected But Unconfirmed Issues")),
        "riskSummary": parse_markdown_paragraphs(get_markdown_section(markdown, "Risk Summary")),
        "nextActions": parse_markdown_simple_list(get_markdown_section(markdown, "Suggested Next Actions")),
    }


def render_text_items(items, ordered: bool = False, empty_text: str = "None.") -> str:
    if not items:
        return f"<p>{escape(empty_text)}</p>"
    tag = "ol" if ordered else "ul"
    rendered_items = "".join(f"<li>{markdown_inline_to_html(item)}</li>" for item in items)
    return f"<{tag}>{rendered_items}</{tag}>"


def render_paragraphs(paragraphs, empty_text: str = "None.") -> str:
    if not paragraphs:
        return f"<p>{escape(empty_text)}</p>"
    return "".join(f"<p>{markdown_inline_to_html(paragraph)}</p>" for paragraph in paragraphs)


def render_suggested_action(values):
    if not values:
        return "<p>None.</p>"
    if len(values) == 1:
        return f"<p><strong>Suggested Action:</strong> {markdown_inline_to_html(values[0])}</p>"
    rendered_items = "".join(f"<li>{markdown_inline_to_html(value)}</li>" for value in values)
    return f"<p><strong>Suggested Action:</strong></p><ul>{rendered_items}</ul>"


def house_report_language_pack(language: str):
    if language == "zh-CN":
        return {
            "lang": "zh-CN",
            "bodyFont": '"Microsoft YaHei", "PingFang SC", Segoe UI, Tahoma, sans-serif',
            "titleFont": '"Microsoft YaHei UI", "PingFang SC", "Source Han Sans SC", sans-serif',
            "bodyLetterSpacing": "0.005em",
            "pageWidth": "1120px",
            "titleSize": "31px",
            "sectionSize": "21px",
            "bodyLineHeight": "1.72",
            "summaryLabels": {
                "total": "总问题数",
                "critical": "严重",
                "major": "重要",
                "minor": "次要",
                "info": "提示",
            },
            "sections": {
                "findings": "已确认问题",
                "openQuestions": "待确认问题",
                "suspectedIssues": "疑似但未确认的问题",
                "riskSummary": "风险总结",
                "nextActions": "建议的后续操作",
            },
            "fields": {
                "scope": "范围",
                "date": "日期",
                "ruleVersion": "规则版本",
                "aiModel": "AI 模型",
                "function": "函数",
                "location": "位置",
                "evidence": "证据",
                "functionalImpact": "功能影响",
                "reasoning": "定级理由",
                "suggestedAction": "建议操作",
            },
            "severityBadges": {
                "critical": "严重",
                "major": "重要",
                "minor": "次要",
                "info": "提示",
            },
            "empty": "无。",
        }

    return {
        "lang": "en",
        "bodyFont": '"Aptos", "Segoe UI Variable Text", "Segoe UI", "Trebuchet MS", sans-serif',
        "titleFont": '"Bahnschrift SemiBold", "Aptos Display", "Segoe UI Variable Display", sans-serif',
        "bodyLetterSpacing": "0.012em",
        "pageWidth": "1140px",
        "titleSize": "33px",
        "sectionSize": "20px",
        "bodyLineHeight": "1.68",
        "summaryLabels": {
            "total": "Total Findings",
            "critical": "Critical",
            "major": "Major",
            "minor": "Minor",
            "info": "Info",
        },
        "sections": {
            "findings": "Confirmed Findings",
            "openQuestions": "Open Questions",
            "suspectedIssues": "Suspected But Unconfirmed Issues",
            "riskSummary": "Risk Summary",
            "nextActions": "Suggested Next Actions",
        },
        "fields": {
            "scope": "Scope",
            "date": "Date",
            "ruleVersion": "Rule Version",
            "aiModel": "AI Model",
            "function": "Function",
            "location": "Location",
            "evidence": "Evidence",
            "functionalImpact": "Functional Impact",
            "reasoning": "Reasoning",
            "suggestedAction": "Suggested Action",
        },
        "severityBadges": {
            "critical": "CRITICAL",
            "major": "MAJOR",
            "minor": "MINOR",
            "info": "INFO",
        },
        "empty": "None.",
    }


def render_findings_html(findings, language_pack) -> str:
    if not findings:
        return f"<section class=\"card neutral-card\"><h2 class=\"section-title\">{escape(language_pack['sections']['findings'])}</h2><p>{escape(language_pack['empty'])}</p></section>"

    rendered_findings = []
    for finding in findings:
        severity = finding["severity"]
        evidence_items = "".join(f"<li>{markdown_inline_to_html(item)}</li>" for item in finding["evidence"])
        suggested_action_html = render_text_items(finding["suggestedAction"], empty_text=language_pack["empty"])
        rendered_findings.append(
            f"""
    <section class=\"card {severity}-card\">
      <h2 class=\"section-title\">{escape(language_pack['sections']['findings'])}</h2>
      <div>
        <span class=\"badge {severity}\">{escape(language_pack['severityBadges'][severity])}</span>
        <div class=\"finding-title\">{markdown_inline_to_html(finding['title'])}</div>
        <p><strong>{escape(language_pack['fields']['function'])}:</strong> <code>{escape(finding['function'])}</code></p>
        <p><strong>{escape(language_pack['fields']['location'])}:</strong> {markdown_inline_to_html(finding['location'])}</p>
        <p><strong>{escape(language_pack['fields']['evidence'])}:</strong></p>
        <ul>{evidence_items}</ul>
        <p><strong>{escape(language_pack['fields']['functionalImpact'])}:</strong> {markdown_inline_to_html(finding['functionalImpact'])}</p>
        <p><strong>{escape(language_pack['fields']['reasoning'])}:</strong> {markdown_inline_to_html(finding['reasoning'])}</p>
        <p><strong>{escape(language_pack['fields']['suggestedAction'])}:</strong></p>
        {suggested_action_html}
      </div>
    </section>""".strip()
        )
    return "\n".join(rendered_findings)


def normalize_html_report(markdown: str, source_html: str, config, language: str, source_arg: str, scope_label: str, generated_at: str) -> str:
    report_subject = derive_report_subject(source_arg, scope_label)
    render_model = build_report_render_model(markdown, report_subject or scope_label)
    if source_html:
        render_model = merge_render_models(render_model, build_localized_render_model_from_html(source_html, language))
    render_model["findings"] = filter_findings_by_threshold(render_model.get("findings", []), config)
    render_model["summary"] = summarize_findings(render_model["findings"])
    return render_html_report(render_model, config, language, source_arg, scope_label, generated_at)


def render_html_report(render_model, config, language: str, source_arg: str, scope_label: str, generated_at: str) -> str:
    language_pack = house_report_language_pack(language)
    title = build_report_title(config, language, source_arg, scope_label)
    summary = render_model["summary"]
    fields = language_pack["fields"]
    sections = language_pack["sections"]
    summary_labels = language_pack["summaryLabels"]

    return f"""<!DOCTYPE html>
<html lang=\"{language_pack['lang']}\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: {language_pack['bodyFont']}; background: #f5f7fb; color: #1f2937; margin: 0; padding: 24px; letter-spacing: {language_pack.get('bodyLetterSpacing', 'normal')}; line-height: {language_pack.get('bodyLineHeight', '1.6')}; text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased; }}
    .page {{ max-width: {language_pack.get('pageWidth', '1100px')}; margin: 0 auto; }}
    .header {{ background: linear-gradient(135deg, #0f172a, #1d4ed8); color: #ffffff; padding: 28px 30px 26px; border-radius: 18px; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.18); }}
    .header h1 {{ margin: 0 0 10px; font-size: {language_pack.get('titleSize', '28px')}; font-family: {language_pack.get('titleFont', language_pack['bodyFont'])}; letter-spacing: -0.02em; line-height: 1.12; }}
    .meta {{ display: flex; gap: 12px; flex-wrap: wrap; font-size: 14px; opacity: 1; }}
    .meta span {{ display: inline-block; padding: 7px 11px; border-radius: 999px; background: rgba(15, 23, 42, 0.42); color: #f8fbff; border: 1px solid rgba(255, 255, 255, 0.18); backdrop-filter: blur(6px); }}
    .meta strong {{ color: #ffffff; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 22px 0; }}
    .summary-card {{ border-radius: 14px; padding: 15px 17px; box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08); }}
    .summary-card strong {{ display: block; font-size: 23px; margin-bottom: 5px; font-family: {language_pack.get('titleFont', language_pack['bodyFont'])}; letter-spacing: -0.02em; }}
    .summary-total {{ background: #e2e8f0; color: #0f172a; }}
    .summary-critical {{ background: #c2410c; color: #ffffff; }}
    .summary-major {{ background: #facc15; color: #422006; }}
    .summary-minor {{ background: #bef264; color: #365314; }}
    .summary-info {{ background: #bae6fd; color: #0c4a6e; }}
    .card {{ border-radius: 14px; padding: 18px 20px; margin-bottom: 15px; box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08); border-left: 6px solid #94a3b8; }}
    .critical-card {{ background: #fff1f2; border-left-color: #dc2626; }}
    .major-card {{ background: #fff7ed; border-left-color: #d97706; }}
    .minor-card {{ background: #f7fee7; border-left-color: #65a30d; }}
    .info-card {{ background: #eff6ff; border-left-color: #0284c7; }}
    .neutral-card {{ background: #ffffff; border-left-color: #94a3b8; }}
    .section-title {{ margin: 0 0 12px; font-size: {language_pack.get('sectionSize', '22px')}; font-family: {language_pack.get('titleFont', language_pack['bodyFont'])}; letter-spacing: -0.015em; line-height: 1.18; }}
    .finding-title {{ font-size: 19px; font-weight: 700; margin: 12px 0 10px; font-family: {language_pack.get('titleFont', language_pack['bodyFont'])}; letter-spacing: -0.01em; line-height: 1.24; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 700; letter-spacing: 0.03em; }}
    .critical {{ background: #c2410c; color: #ffffff; }}
    .major {{ background: #facc15; color: #422006; }}
    .minor {{ background: #bef264; color: #365314; }}
    .info {{ background: #bae6fd; color: #0c4a6e; }}
        code {{ display: inline-block; background: #e7eef7; color: #17324d; padding: 2px 7px; border-radius: 7px; border: 1px solid #c7d6e7; font-family: "Cascadia Code", Consolas, monospace; font-size: 0.94em; line-height: 1.5; vertical-align: baseline; word-break: break-word; }}
        ul, ol {{ margin: 10px 0 0 20px; padding-left: 2px; }}
        li {{ margin: 4px 0; }}
        p {{ margin: 8px 0; line-height: {language_pack.get('bodyLineHeight', '1.6')}; }}
        p strong, li strong {{ color: #0f172a; }}
  </style>
</head>
<body>
  <div class=\"page\">
    <header class=\"header\">
      <h1>{escape(title)}</h1>
      <div class=\"meta\">
        <span><strong>{escape(fields['scope'])}:</strong> {markdown_inline_to_html(localize_scope_label(scope_label, language))}</span>
        <span><strong>{escape(fields['date'])}:</strong> {escape(format_report_timestamp(generated_at))}</span>
        <span><strong>{escape(fields['ruleVersion'])}:</strong> {escape(resolve_rule_version(config))}</span>
        <span><strong>{escape(fields['aiModel'])}:</strong> {escape(resolve_ai_model(config))}</span>
      </div>
    </header>

    <section class=\"summary\">
      <div class=\"summary-card summary-total\"><strong>{summary['total']}</strong>{escape(summary_labels['total'])}</div>
      <div class=\"summary-card summary-critical\"><strong>{summary['critical']}</strong>{escape(summary_labels['critical'])}</div>
      <div class=\"summary-card summary-major\"><strong>{summary['major']}</strong>{escape(summary_labels['major'])}</div>
      <div class=\"summary-card summary-minor\"><strong>{summary['minor']}</strong>{escape(summary_labels['minor'])}</div>
      <div class=\"summary-card summary-info\"><strong>{summary['info']}</strong>{escape(summary_labels['info'])}</div>
    </section>

    {render_findings_html(render_model['findings'], language_pack)}

    <section class=\"card neutral-card\">
      <h2 class=\"section-title\">{escape(sections['openQuestions'])}</h2>
      {render_text_items(render_model['openQuestions'], empty_text=language_pack['empty'])}
    </section>

    <section class=\"card neutral-card\">
      <h2 class=\"section-title\">{escape(sections['suspectedIssues'])}</h2>
      {render_text_items(render_model['suspectedIssues'], empty_text=language_pack['empty'])}
    </section>

    <section class=\"card neutral-card\">
      <h2 class=\"section-title\">{escape(sections['riskSummary'])}</h2>
      {render_paragraphs(render_model['riskSummary'], empty_text=language_pack['empty'])}
    </section>

    <section class=\"card neutral-card\">
      <h2 class=\"section-title\">{escape(sections['nextActions'])}</h2>
      {render_text_items(render_model['nextActions'], ordered=True, empty_text=language_pack['empty'])}
    </section>
  </div>
</body>
</html>
"""


def strip_skill_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            return parts[1].strip()
    return text.strip()


def load_skill_context(config, config_path: Path):
    skill_config = config.get("skill", {})
    base_dir = config_path.resolve().parent.parent
    skill_file = base_dir / skill_config.get("skillFile", "skills/static-code-review-workflow/SKILL.md")
    skill_text = strip_skill_frontmatter(read_text(skill_file))

    guideline_texts = []
    for relative_path in skill_config.get("guidelineFiles", []):
        guideline_path = base_dir / relative_path
        guideline_texts.append(f"## {guideline_path.name}\n\n{read_text(guideline_path).strip()}")

    return {
        "skillFile": str(skill_file.resolve()),
        "skillText": skill_text,
        "guidelineFiles": [str((base_dir / item).resolve()) for item in skill_config.get("guidelineFiles", [])],
        "guidelineText": "\n\n".join(guideline_texts).strip(),
    }


def build_skill_system_prompt(config, config_path: Path) -> str:
    skill_context = load_skill_context(config, config_path)
    compact_rules = compact_rules_text(config)
    return f"""# Project Skill Context

The following repository skill and guideline excerpts are the authoritative review method for this request.

## Skill File

Path: {skill_context['skillFile']}

{skill_context['skillText']}

## Selected Guideline Files

{skill_context['guidelineText']}

## Additional Tightening Rules

{compact_rules}

## Required Behavior

1. Apply the project skill as if it were preloaded project knowledge.
2. Review only the code in the user message.
3. Prefer one strong code-proven finding over multiple speculative findings.
4. Do not produce contract-dependent, null-pointer, portability, wraparound, or caller-behavior findings unless the visible code proves the failure.
5. Keep the output short and structured.
6. Return the final answer using the exact output contract requested by the user message.
"""


def build_skill_user_prompt(review_scope, config) -> str:
    title = build_markdown_report_title(config, str(review_scope["sourcePath"]), review_scope["scopeLabel"])
    max_findings = config.get("defaultMaxConfirmedFindings", 2)
    min_severity = minimum_displayed_severity(config)
    language = detect_review_language(str(review_scope['sourcePath']))
    return f"""Review the following source file using the preloaded project skill context and generate a review result plus aligned Markdown and HTML reports.

## Scope

- Source: {review_scope['sourcePath']}
- Language: {language}
- Scope kind: {review_scope['scopeKind']}
- Scope label: {review_scope['scopeLabel']}
- Confirmed findings cap: {max_findings}
- Minimum displayed severity: {min_severity}

## Review Scope Instruction

{build_scope_review_instructions(review_scope)}

## Output Contract

Return exactly these sections in this order:

1. Review Result
2. Short review conclusion text
3. Markdown Report
4. A single ```md fenced block
5. English HTML Report
6. A single ```html fenced block
7. Chinese HTML Report
8. A single ```html fenced block

Markdown must contain these exact headings:

1. # {title}
2. ## Summary
3. ## Confirmed Findings
4. ## Open Questions
5. ## Suspected But Unconfirmed Issues
6. ## Risk Summary
7. ## Suggested Next Actions

If Open Questions or Suspected But Unconfirmed Issues are empty, output None.

Only keep findings with severity {min_severity} or higher in the final Review Result, Markdown Report, English HTML Report, and Chinese HTML Report. Suppress minor and info findings from final output. Summary counts must reflect only the displayed findings.

Each confirmed finding in Markdown must use this exact field order:

1. **Function**
2. **Location**
3. **Evidence**
4. **Functional Impact**
5. **Reasoning**
6. **Suggested Action**

English HTML must be a complete HTML document and include these section titles:

1. Confirmed Findings
2. Open Questions
3. Suspected But Unconfirmed Issues
4. Risk Summary
5. Suggested Next Actions

Chinese HTML must be a complete HTML document and include these section titles:

1. 已确认问题
2. 待确认问题
3. 疑似但未确认的问题
4. 风险总结
5. 建议的后续操作

Both HTML reports must put the source file or reviewed function name into the report title and display Rule Version plus AI Model in the report metadata area.
Both HTML reports must follow the fixed review card layout from report-templates.md. Each confirmed finding card must include, in order, a severity badge, finding title, Function/函数, Location/位置, Evidence/证据, Functional Impact/功能影响, Reasoning/定级理由, and Suggested Action/建议操作.

## Review Input

```{language}
{review_scope['reviewText'].rstrip()}
```
"""


def build_skill_pack(config, config_path: Path) -> str:
    skill_context = load_skill_context(config, config_path)
    compact_rules = compact_rules_text(config)
    min_severity = minimum_displayed_severity(config)
    return f"""# Kimi Project Skill Pack

This file is project knowledge for Kimi. It is not review input.

## How To Use

1. Treat this file as the review policy and output contract.
2. Review only the separately uploaded source file.
3. Do not generate findings against this skill pack itself.
4. Keep confirmed findings selective and code-proven.
5. In final formal output, only display findings with severity `{min_severity}` or higher.

## Project Skill

Source: {skill_context['skillFile']}

{skill_context['skillText']}

## Selected Guideline Files

{skill_context['guidelineText']}

## Additional Tightening Rules

{compact_rules}

## Required Output Contract

Return exactly these sections in this order:

1. Review Result
2. Short review conclusion text
3. Markdown Report
4. A single ```md fenced block
5. English HTML Report
6. A single ```html fenced block
7. Chinese HTML Report
8. A single ```html fenced block

Markdown must contain these exact headings:

1. # Static Code Review Report - <source-file-name>
2. ## Summary
3. ## Confirmed Findings
4. ## Open Questions
5. ## Suspected But Unconfirmed Issues
6. ## Risk Summary
7. ## Suggested Next Actions

If Open Questions or Suspected But Unconfirmed Issues are empty, output None.

Only keep findings with severity {min_severity} or higher in the final Review Result, Markdown Report, English HTML Report, and Chinese HTML Report. Suppress minor and info findings from final output. Summary counts must reflect only the displayed findings.

Each confirmed finding in Markdown must use this exact field order:

1. **Function**
2. **Location**
3. **Evidence**
4. **Functional Impact**
5. **Reasoning**
6. **Suggested Action**

English HTML must be a complete HTML document and include these section titles:

1. Confirmed Findings
2. Open Questions
3. Suspected But Unconfirmed Issues
4. Risk Summary
5. Suggested Next Actions

Chinese HTML must be a complete HTML document and include these section titles:

1. 已确认问题
2. 待确认问题
3. 疑似但未确认的问题
4. 风险总结
5. 建议的后续操作

Both HTML reports must put the source file or reviewed function name into the report title and display Rule Version plus AI Model in the report metadata area.
Both HTML reports must follow the fixed review card layout from report-templates.md. Each confirmed finding card must include, in order, a severity badge, finding title, Function/函数, Location/位置, Evidence/证据, Functional Impact/功能影响, Reasoning/定级理由, and Suggested Action/建议操作.
"""


def build_bundle(review_scope, config) -> str:
    generated_at = utc_now_iso()
    rules = compact_rules_text(config)
    max_findings = config.get("defaultMaxConfirmedFindings", 2)
    min_severity = minimum_displayed_severity(config)
    title = build_markdown_report_title(config, str(review_scope["sourcePath"]), review_scope["scopeLabel"])
    source_hash = sha256_text(review_scope["reviewText"])
    language = detect_review_language(str(review_scope['sourcePath']))
    return f"""# Kimi Review To Report Bundle

- Mode: review-to-report
- Language: {language}
- Review scope: {review_scope['scopeKind']}
- Source: {review_scope['sourcePath']}
- Scope label: {review_scope['scopeLabel']}
- Review input: {review_scope['reviewInputPath']}
- Prompt version: {config.get('promptVersion', 'unknown')}
- Review input sha256: {source_hash}
- Generated at: {generated_at}

## Base Prompt

# Kimi Review And Report Prompt

请只评审本文最后 `## Review Input` 下面的代码，并在一次输出中同时给出评审结论、Markdown 报告、英文 HTML 报告和中文 HTML 报告。

## 严格边界

1. 你真正要评审的对象只有 `## Review Input` 下面的代码。
2. 不要把本文中的 workflow、policy、规则说明、输出约束当作待评审对象。
3. 只有代码本身直接证明失败路径时，才能保留 confirmed finding。
4. 不要把空指针、调用契约、调用方保证、wraparound、portability、defensive programming 之类的推测问题放进 confirmed finding，除非代码直接证明失败路径。
5. 如果某个弱证据问题对 reviewer 没有明显帮助，也不要放进 Open Questions。
6. Confirmed Findings 最多保留 {max_findings} 条，并优先保留 1 条最核心、最能解释行为风险的 finding。
7. 如果多个问题本质上属于同一个整数转换、比较、边界判断或同一根因的不同表现，只保留 1 条。
8. 不要因为命中很多 guideline 就扩写很多 finding。规则只能作为已确认问题的依据。
9. 如果 `Open Questions` 或 `Suspected But Unconfirmed Issues` 为空，输出 `None.`。
10. 报告语言保持简洁，不要复述大段规则原文。
11. 严格遵守 `Review Scope`。如果 scope 是 function，只评审该函数；如果 scope 是 selection，只评审给定选区；不要扩展到其他函数。
12. 最终正式输出默认只显示 `{min_severity}` 及以上级别的 finding；`minor` 和 `info` 不要写入最终报告。

## 严重级别口径

1. `critical` 仅用于代码直接证明的高风险问题，例如越界、未初始化读、明确的安全暴露或高风险并发破坏。
2. `major` 用于代码直接证明的行为错误，例如语言特性误用、错误处理缺失、数值转换或求值顺序导致结果错误。
3. `minor` 和 `info` 用于非功能性问题。

## 紧凑规则参考

{rules}

## Review Scope

{build_scope_prompt_lines(review_scope)}

{build_scope_review_instructions(review_scope)}

## 输出要求

你最终只允许输出以下内容，顺序不能变：

1. `Review Result`
2. 评审结论正文
3. `Markdown Report`
4. 一个 ```md 代码块
5. `English HTML Report`
6. 一个 ```html 代码块
7. `Chinese HTML Report`
8. 一个 ```html 代码块

不要输出额外解释，不要输出多余前言。

## Markdown 报告格式

Markdown 报告必须包含以下 section，标题保持一致：

1. `# {title}`
2. `## Summary`
3. `## Confirmed Findings`
4. `## Open Questions`
5. `## Suspected But Unconfirmed Issues`
6. `## Risk Summary`
7. `## Suggested Next Actions`

`Summary` 中必须包含：

- Scope
- Total findings
- Critical
- Major
- Minor
- Info

`Summary` 中的计数必须只统计最终实际显示出来的 finding。

每条 confirmed finding 必须包含：

- **Function:**
- **Location:**
- **Evidence:**
- **Functional Impact:**
- **Reasoning:**
- **Suggested Action:**

## HTML 报告格式

1. 输出两份完整 HTML 文档，一份英文，一份中文。
2. 两份 HTML 报告语义必须与 Markdown 报告一致。
3. 英文 HTML 中必须出现这些 section 标题：`Confirmed Findings`、`Open Questions`、`Suspected But Unconfirmed Issues`、`Risk Summary`、`Suggested Next Actions`。
4. 中文 HTML 中必须出现这些 section 标题：`已确认问题`、`待确认问题`、`疑似但未确认的问题`、`风险总结`、`建议的后续操作`。
5. 两份 HTML 报告标题都要包含源码文件名或被审函数名。
6. 两份 HTML 报告都要展示 `Rule Version` / `规则版本` 和 `AI Model` / `AI 模型`。
7. 每条已确认问题都必须使用固定卡片格式，且字段顺序固定为：严重级别徽标、问题标题、`函数`、`位置`、`证据`、`功能影响`、`定级理由`、`建议操作`。
8. `证据` 优先使用项目符号列表，不要只写一句笼统概述。
9. 不要输出空文件或占位 HTML。

## Review Input

下面这段代码是唯一需要评审的输入对象。

```{language}
{review_scope['reviewText'].rstrip()}
```
"""


def artifact_path(report_base: Path, suffix: str) -> Path:
    return report_base.parent / f"{report_base.name}{suffix}"


def find_code_block(text: str, label: str, fence_langs):
    langs = "|".join(re.escape(item) for item in fence_langs)
    pattern = re.compile(r"(?:" + label + r")\s*```(?:" + langs + r")\s*(.*?)```", re.IGNORECASE | re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None


def extract_report_parts(response_text: str):
    markdown = find_code_block(response_text, r"Markdown Report", ["md", "markdown"])
    english_html = find_code_block(response_text, r"English HTML Report|HTML Report\s*\(English\)", ["html"])
    if not english_html:
        english_html = find_code_block(response_text, r"HTML Report", ["html"])
    chinese_html = find_code_block(response_text, r"Chinese HTML Report|HTML Report\s*\(Chinese\)|中文 HTML Report", ["html"])
    if not markdown:
        raise ValueError("Missing Markdown Report fenced code block.")
    if not english_html:
        raise ValueError("Missing English HTML Report fenced code block.")
    return markdown, {"en": english_html, "zh-CN": chinese_html or ""}


def count_markdown_findings(markdown: str):
    counts = {"critical": 0, "major": 0, "minor": 0, "info": 0}
    for severity in counts:
        pattern = re.compile(r"^###\s+" + severity + r"\s+-", re.IGNORECASE | re.MULTILINE)
        counts[severity] = len(pattern.findall(markdown))
    return counts


def parse_summary_counts(markdown: str):
    patterns = {
        "total": r"-\s+Total findings:\s+(\d+)",
        "critical": r"-\s+Critical:\s+(\d+)",
        "major": r"-\s+Major:\s+(\d+)",
        "minor": r"-\s+Minor:\s+(\d+)",
        "info": r"-\s+Info:\s+(\d+)",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, markdown, re.IGNORECASE)
        if not match:
            raise ValueError(f"Missing summary count: {key}")
        result[key] = int(match.group(1))
    return result


def validate_markdown(markdown: str, expected_title: str = ""):
    if expected_title:
        first_heading_match = re.search(r"^#\s+(.+)$", markdown, flags=re.MULTILINE)
        if not first_heading_match:
            raise ValueError("Markdown report is missing the top-level report title.")
        if first_heading_match.group(1).strip() != expected_title:
            raise ValueError(
                f"Markdown report title does not match the expected normalized title: {expected_title}."
            )

    for heading in REQUIRED_MD_HEADINGS:
        if heading not in markdown:
            raise ValueError(f"Markdown report is missing required heading: {heading}")

    summary = parse_summary_counts(markdown)
    finding_counts = count_markdown_findings(markdown)
    calculated_total = sum(finding_counts.values())

    if summary["total"] != calculated_total:
        raise ValueError(
            f"Summary total {summary['total']} does not match counted findings {calculated_total}."
        )

    for severity in ["critical", "major", "minor", "info"]:
        if summary[severity] != finding_counts[severity]:
            raise ValueError(
                f"Summary {severity} count {summary[severity]} does not match counted findings {finding_counts[severity]}."
            )

    required_finding_fields = {
        "Function": re.compile(r"^-\s+\*\*Function(?::)?\*\*:?\s*", re.IGNORECASE | re.MULTILINE),
        "Location": re.compile(r"^-\s+\*\*Location(?::)?\*\*:?\s*", re.IGNORECASE | re.MULTILINE),
        "Evidence": re.compile(r"^-\s+\*\*Evidence(?::)?\*\*:?\s*", re.IGNORECASE | re.MULTILINE),
        "Functional Impact": re.compile(r"^-\s+\*\*Functional Impact(?::)?\*\*:?\s*", re.IGNORECASE | re.MULTILINE),
        "Reasoning": re.compile(r"^-\s+\*\*Reasoning(?::)?\*\*:?\s*", re.IGNORECASE | re.MULTILINE),
        "Suggested Action": re.compile(r"^-\s+\*\*Suggested Action(?::)?\*\*:?\s*", re.IGNORECASE | re.MULTILINE),
    }
    finding_blocks = re.split(r"^###\s+", markdown, flags=re.MULTILINE)[1:]

    for finding_block in finding_blocks:
        for required_field, required_pattern in required_finding_fields.items():
            if not required_pattern.search(finding_block):
                raise ValueError(f"Markdown confirmed finding is missing required field: {required_field}")

    return {
        "summary": summary,
        "findingCounts": finding_counts,
    }


def parse_summary_counts_from_html(html: str):
    summary_classes = {
        "total": "summary-total",
        "critical": "summary-critical",
        "major": "summary-major",
        "minor": "summary-minor",
        "info": "summary-info",
    }
    result = {}

    for key, css_class in summary_classes.items():
        pattern = re.compile(
            r'<div class="summary-card\s+' + re.escape(css_class) + r'">\s*<strong>(\d+)</strong>',
            re.IGNORECASE,
        )
        match = pattern.search(html)
        if not match:
            raise ValueError(f"HTML report is missing summary card: {key}")
        result[key] = int(match.group(1))

    return result


def validate_html(html: str, language: str, expected_title: str):
    if f"<title>{escape(expected_title)}</title>" not in html:
        raise ValueError(
            f"{language} HTML report title does not match the expected normalized title: {expected_title}. "
            "The report files may be mixed from different review scopes or different review runs."
        )

    for snippet in HTML_REPORT_VARIANTS[language]["requiredSnippets"]:
        if snippet not in html:
            raise ValueError(f"{language} HTML report is missing required snippet: {snippet}")


def backfill_missing_html_variants(report_base: Path, config, source_arg: str = "", preferred_scope_label: str = ""):
    html_paths = html_report_paths(report_base)
    english_path = html_paths["en"]
    chinese_path = html_paths["zh-CN"]

    if not english_path.exists() or chinese_path.exists():
        return

    english_html = english_path.read_text(encoding="utf-8")
    render_model = build_localized_render_model_from_html(english_html, "en")
    render_model["summary"] = parse_summary_counts_from_html(english_html)
    scope_label = preferred_scope_label or report_base.name
    generated_at = file_modified_iso(english_path)
    chinese_html = render_html_report(render_model, config, "zh-CN", source_arg, scope_label, generated_at)
    validate_html(chinese_html, "zh-CN", build_report_title(config, "zh-CN", source_arg, scope_label))
    atomic_write(chinese_path, chinese_html.strip() + "\n")


def resolve_api_key():
    return os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")


def invoke_kimi_api(messages, config):
    api_key = resolve_api_key()
    if not api_key:
        raise ValueError("Missing Kimi API key. Set KIMI_API_KEY or MOONSHOT_API_KEY.")

    api_config = config.get("api", {})
    base_url = (os.environ.get("KIMI_BASE_URL") or os.environ.get("MOONSHOT_BASE_URL") or api_config.get("baseUrl") or "https://api.moonshot.cn/v1").rstrip("/")
    model = os.environ.get("KIMI_MODEL") or os.environ.get("MOONSHOT_MODEL") or api_config.get("model") or "moonshot-v1-8k"
    timeout_seconds = int(api_config.get("timeoutSeconds", 120))
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }
    request = urllib.request.Request(
        url=f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Kimi API request failed: HTTP {exc.code}. {error_body}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Kimi API request failed: {exc.reason}") from exc

    parsed = json.loads(body)
    try:
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Kimi API response is missing choices[0].message.content.") from exc


def copy_text_to_clipboard(text: str):
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value @'\n" + text + "\n'@"], check=True)


def read_text_from_clipboard() -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def enrich_with_source_freshness(result, source_arg: str):
    if not source_arg:
        return result

    source_info = source_metadata(Path(source_arg))
    report_time = parse_utc_iso(result["generatedAt"])
    source_time = parse_utc_iso(source_info["sourceModifiedAt"])

    if source_time > report_time:
        raise ValueError(
            f"Source file is newer than the report: {source_info['sourceModifiedAt']} > {result['generatedAt']}."
        )

    result.update(source_info)
    return result


def validate_report_base(report_base: Path, config, preferred_scope_label="", source_arg=""):
    backfill_missing_html_variants(report_base, config, source_arg=source_arg, preferred_scope_label=preferred_scope_label)
    html_paths = html_report_paths(report_base)
    timestamps = [file_modified_iso(path) for path in html_paths.values()]
    report_generated_at = max(timestamps)
    result = {
        "status": "validated",
        "htmlPath": str(html_paths["en"]),
        "htmlPaths": {language: str(path) for language, path in html_paths.items()},
        "generatedAt": report_generated_at,
    }

    html_contents = {language: path.read_text(encoding="utf-8") for language, path in html_paths.items()}
    for language, html in html_contents.items():
        if not html.strip():
            raise ValueError(f"{language} HTML report is empty.")

    scope_label = preferred_scope_label or report_base.name
    for language, html in html_contents.items():
        validate_html(html, language, build_report_title(config, language, source_arg, scope_label))

    result["summary"] = parse_summary_counts_from_html(html_contents["en"])
    return result


def command_prepare(args):
    config = load_json(Path(args.config))
    review_scope = resolve_review_scope(args)
    source_path = review_scope["sourcePath"]
    bundle = build_bundle(review_scope, config)
    bundle_path = (
        Path(args.output).resolve()
        if args.output
        else source_path.with_name(source_path.stem + ".file-review-to-report.kimi-input.latest.md")
    )
    atomic_write(bundle_path, bundle)
    payload = {
        "status": "bundle_ready",
        "bundlePath": str(bundle_path),
        "sourcePath": str(source_path),
        "sourceSha256": sha256_text(read_text(source_path)),
        "reviewScopeKind": review_scope["scopeKind"],
        "reviewScopeName": review_scope["scopeName"],
        "reviewScopeLabel": review_scope["scopeLabel"],
        "promptVersion": config.get("promptVersion", "unknown"),
        "generatedAt": utc_now_iso(),
    }
    payload.update(review_input_metadata(review_scope["reviewInputPath"], review_scope["reviewText"]))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_prepare_clipboard(args):
    config = load_json(Path(args.config))
    review_scope = resolve_review_scope(args)
    source_path = review_scope["sourcePath"]
    bundle = build_bundle(review_scope, config)
    bundle_path = (
        Path(args.output).resolve()
        if args.output
        else source_path.with_name(source_path.stem + ".file-review-to-report.kimi-input.latest.md")
    )
    atomic_write(bundle_path, bundle)
    copy_text_to_clipboard(bundle)
    payload = {
        "status": "bundle_copied",
        "bundlePath": str(bundle_path),
        "sourcePath": str(source_path),
        "sourceSha256": sha256_text(read_text(source_path)),
        "reviewScopeKind": review_scope["scopeKind"],
        "reviewScopeName": review_scope["scopeName"],
        "reviewScopeLabel": review_scope["scopeLabel"],
        "generatedAt": utc_now_iso(),
    }
    payload.update(review_input_metadata(review_scope["reviewInputPath"], review_scope["reviewText"]))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def import_response_text(config, response_text: str, report_dir: Path, report_base_name: str, source_path=None, response_path=None, preferred_scope_label="", scope_kind="file", scope_name=""):
    ensure_dir(report_dir)
    report_generated_at = utc_now_iso()
    resolved_report_base_name = resolve_report_base_name(
        report_base_name,
        config,
        source_path,
        scope_kind,
        scope_name,
        report_dir=report_dir,
        generated_at=report_generated_at,
    )
    report_base = report_dir / resolved_report_base_name

    try:
        markdown, html_reports = extract_report_parts(response_text)
        scope_label = resolve_effective_scope_label(preferred_scope_label, source_path, markdown, report_base.name)
        normalized_markdown = normalize_markdown_report(markdown, config, report_generated_at, source_path or "")
        normalized_html_reports = {
            language: normalize_html_report(normalized_markdown, html_reports.get(language, ""), config, language, source_path or "", scope_label, report_generated_at)
            for language in html_reports
        }
        md_validation = validate_markdown(
            normalized_markdown,
            build_markdown_report_title(config, source_path or "", scope_label),
        )
        for language, html in normalized_html_reports.items():
            validate_html(html, language, build_report_title(config, language, source_path or "", scope_label))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    html_paths = html_report_paths(report_base)
    meta = {
        "status": "success",
        "promptVersion": config.get("promptVersion", "unknown"),
        "ruleVersion": resolve_rule_version(config),
        "aiModel": resolve_ai_model(config),
        "htmlPath": str(html_paths["en"]),
        "htmlPaths": {language: str(path) for language, path in html_paths.items()},
        "summary": md_validation["summary"],
        "responseSha256": sha256_text(response_text),
        "generatedAt": report_generated_at,
    }
    if response_path:
        meta["responsePath"] = str(response_path)
    if source_path:
        meta.update(source_metadata(Path(source_path)))

    report_bases_to_archive = find_all_report_bases(report_dir)
    report_bases_to_archive.append(report_base)

    archived_report = archive_existing_report_sets(report_bases_to_archive)
    if archived_report:
        meta["archivedPreviousReport"] = archived_report

    for language, path in html_paths.items():
        atomic_write(path, normalized_html_reports[language].strip() + "\n")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


def command_import(args):
    config = load_json(Path(args.config))
    response_path = Path(args.response).resolve()
    response_text = response_path.read_text(encoding="utf-8")
    preferred_scope_label = ""
    if args.source:
        preferred_scope_label = build_scope_label(args.scope_kind, args.scope_name or "", Path(args.source).resolve())
    return import_response_text(
        config,
        response_text,
        Path(args.report_dir).resolve(),
        args.report_base,
        source_path=args.source,
        response_path=response_path,
        preferred_scope_label=preferred_scope_label,
        scope_kind=args.scope_kind,
        scope_name=args.scope_name or "",
    )


def command_import_clipboard(args):
    clipboard_text = read_text_from_clipboard()
    if not clipboard_text.strip():
        print(json.dumps({
            "status": "import_failed",
            "error": "Clipboard is empty.",
            "generatedAt": utc_now_iso(),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    config = load_json(Path(args.config))
    response_path = Path(args.response).resolve() if args.response else None
    if response_path:
        atomic_write(response_path, clipboard_text)

    preferred_scope_label = ""
    if args.source:
        preferred_scope_label = build_scope_label(args.scope_kind, args.scope_name or "", Path(args.source).resolve())

    return import_response_text(
        config,
        clipboard_text,
        Path(args.report_dir).resolve(),
        args.report_base,
        source_path=args.source,
        response_path=response_path,
        preferred_scope_label=preferred_scope_label,
        scope_kind=args.scope_kind,
        scope_name=args.scope_name or "",
    )


def command_run(args):
    config_path = Path(args.config)
    config = load_json(config_path)
    if not resolve_api_key() and config.get("webAutomation", {}).get("enabled", False):
        return command_run_web(args)

    review_scope = resolve_review_scope(args)
    source_path = review_scope["sourcePath"]
    report_dir = Path(args.report_dir).resolve()
    ensure_dir(report_dir)
    report_base = resolve_report_base_name(
        args.report_base,
        config,
        source_path,
        review_scope["scopeKind"],
        review_scope["scopeName"],
        report_dir=report_dir,
        generated_at=utc_now_iso(),
    )

    bundle_text = build_bundle(review_scope, config)
    bundle_path = source_path.with_name(source_path.stem + ".file-review-to-report.kimi-input.latest.md")
    atomic_write(bundle_path, bundle_text)

    messages = [
        {"role": "system", "content": build_skill_system_prompt(config, config_path)},
        {"role": "user", "content": build_skill_user_prompt(review_scope, config)},
    ]

    response_text = invoke_kimi_api(messages, config)
    response_path = Path(args.response_output).resolve() if args.response_output else None
    if response_path:
        atomic_write(response_path, response_text)

    import_code = import_response_text(
        config,
        response_text,
        report_dir,
        report_base,
        source_path=str(source_path),
        response_path=response_path,
        preferred_scope_label=review_scope["scopeLabel"],
        scope_kind=review_scope["scopeKind"],
        scope_name=review_scope["scopeName"],
    )
    if import_code != 0:
        return import_code

    gate_args = argparse.Namespace(
        config=args.config,
        report_dir=str(report_dir),
        report_base=report_base,
        source=str(source_path),
    )
    return command_gate(gate_args)


def command_run_web(args):
    config_path = Path(args.config)
    config = load_json(config_path)
    review_scope = resolve_review_scope(args)
    source_path = review_scope["sourcePath"]
    report_dir = Path(args.report_dir).resolve()
    ensure_dir(report_dir)
    report_base = resolve_report_base_name(
        args.report_base,
        config,
        source_path,
        review_scope["scopeKind"],
        review_scope["scopeName"],
        report_dir=report_dir,
        generated_at=utc_now_iso(),
    )

    bundle_text = build_bundle(review_scope, config)
    bundle_path = source_path.with_name(source_path.stem + ".file-review-to-report.kimi-input.latest.md")
    atomic_write(bundle_path, bundle_text)

    automation_script = config_path.resolve().parent.parent / "automation" / "kimi_web_automation.mjs"

    with tempfile.TemporaryDirectory(prefix="kimi-review-runtime-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        skill_pack_path = Path(args.skill_pack_output).resolve() if args.skill_pack_output else temp_dir / "kimi-project-skill-pack.current.md"
        response_path = Path(args.response_output).resolve() if args.response_output else temp_dir / "kimi-response.current-file.md"
        atomic_write(skill_pack_path, build_skill_pack(config, config_path))

        completed = subprocess.run(
            [
                "node",
                str(automation_script),
                "--config",
                str(config_path.resolve()),
                "--source",
                str(review_scope["reviewInputPath"]),
                "--skill-pack",
                str(skill_pack_path),
                "--response-output",
                str(response_path),
            ],
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Kimi web automation failed.")

        response_text = read_text(response_path)
        persisted_response_path = Path(args.response_output).resolve() if args.response_output else None

    import_code = import_response_text(
        config,
        response_text,
        report_dir,
        report_base,
        source_path=str(source_path),
        response_path=persisted_response_path,
        preferred_scope_label=review_scope["scopeLabel"],
        scope_kind=review_scope["scopeKind"],
        scope_name=review_scope["scopeName"],
    )
    if import_code != 0:
        return import_code

    gate_args = argparse.Namespace(
        config=args.config,
        report_dir=str(report_dir),
        report_base=report_base,
        source=str(source_path),
    )
    return command_gate(gate_args)


def command_validate(args):
    config = load_json(Path(args.config))
    report_dir = Path(args.report_dir).resolve()
    resolved_report_base = resolve_report_base_name(
        args.report_base,
        config,
        args.source,
        args.scope_kind,
        args.scope_name or "",
        report_dir=report_dir,
        prefer_latest=True,
    )
    report_base = report_dir / resolved_report_base
    preferred_scope_label = ""
    if args.source:
        preferred_scope_label = build_scope_label(args.scope_kind, args.scope_name or "", Path(args.source).resolve())

    try:
        result = validate_report_base(report_base, config, preferred_scope_label=preferred_scope_label, source_arg=args.source or "")
        result = enrich_with_source_freshness(result, args.source)
    except Exception as exc:
        result = {
            "status": "validation_failed",
            "reportBase": str(report_base),
            "error": str(exc),
            "generatedAt": utc_now_iso(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_gate(args):
    config = load_json(Path(args.config))
    report_dir = Path(args.report_dir).resolve()
    resolved_report_base = resolve_report_base_name(
        args.report_base,
        config,
        args.source,
        args.scope_kind,
        args.scope_name or "",
        report_dir=report_dir,
        prefer_latest=True,
    )
    report_base = report_dir / resolved_report_base
    preferred_scope_label = ""
    if args.source:
        preferred_scope_label = build_scope_label(args.scope_kind, args.scope_name or "", Path(args.source).resolve())

    try:
        validation_result = validate_report_base(report_base, config, preferred_scope_label=preferred_scope_label, source_arg=args.source or "")
        validation_result = enrich_with_source_freshness(validation_result, args.source)
    except Exception as exc:
        failed = {
            "status": "gate_failed",
            "reportBase": str(report_base),
            "error": str(exc),
            "generatedAt": utc_now_iso(),
        }
        print(json.dumps(failed, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    gate_result = {
        "status": "gate_passed",
        "reportBase": str(report_base),
        "htmlPath": validation_result["htmlPath"],
        "htmlPaths": validation_result["htmlPaths"],
        "summary": validation_result["summary"],
        "generatedAt": validation_result["generatedAt"],
        "policy": "report-success-and-format-only",
    }
    if "sourcePath" in validation_result:
        gate_result.update(
            {
                "sourcePath": validation_result["sourcePath"],
                "sourceSha256": validation_result["sourceSha256"],
                "sourceModifiedAt": validation_result["sourceModifiedAt"],
            }
        )
    print(json.dumps(gate_result, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Engineering workflow for Kimi-based static code review.")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("kimi-review.config.json")),
        help="Path to the workflow config JSON.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_scope_arguments(command_parser):
        command_parser.add_argument(
            "--scope-kind",
            choices=["file", "function", "selection"],
            default="file",
            help="Review scope type. Use function or selection to constrain review scope.",
        )
        command_parser.add_argument("--scope-name", help="Function name or selection label for constrained review scope.")
        command_parser.add_argument(
            "--review-input",
            help="Optional path to the exact code text to review. Defaults to --source for file-level review.",
        )

    prepare = subparsers.add_parser("prepare", help="Generate a compact Kimi review bundle for a source file.")
    prepare.add_argument("--source", required=True, help="Source file to review.")
    prepare.add_argument("--output", help="Optional explicit bundle output path.")
    add_scope_arguments(prepare)
    prepare.set_defaults(func=command_prepare)

    prepare_clipboard = subparsers.add_parser("prepare-clipboard", help="Generate a compact Kimi review bundle and copy it to the clipboard.")
    prepare_clipboard.add_argument("--source", required=True, help="Source file to review.")
    prepare_clipboard.add_argument("--output", help="Optional explicit bundle output path.")
    add_scope_arguments(prepare_clipboard)
    prepare_clipboard.set_defaults(func=command_prepare_clipboard)

    import_cmd = subparsers.add_parser("import", help="Import a Kimi response, validate it, and write reports atomically.")
    import_cmd.add_argument("--response", required=True, help="Markdown file containing the pasted Kimi response.")
    import_cmd.add_argument("--source", help="Optional reviewed source file for traceability and freshness checks.")
    import_cmd.add_argument("--report-dir", default="review-reports", help="Directory to write reports into.")
    import_cmd.add_argument(
        "--report-base",
        default=DEFAULT_REPORT_BASE_NAME,
        help="Base name of the generated report without extension.",
    )
    import_cmd.add_argument(
        "--scope-kind",
        choices=["file", "function", "selection"],
        default="file",
        help="Optional scope type used to normalize the report title.",
    )
    import_cmd.add_argument("--scope-name", help="Optional function name or selection label used to normalize the report title.")
    import_cmd.set_defaults(func=command_import)

    import_clipboard = subparsers.add_parser("import-clipboard", help="Import a Kimi response from the clipboard and write reports atomically.")
    import_clipboard.add_argument("--response", help="Optional path to persist the clipboard response before import.")
    import_clipboard.add_argument("--source", help="Optional reviewed source file for traceability and freshness checks.")
    import_clipboard.add_argument("--report-dir", default="review-reports", help="Directory to write reports into.")
    import_clipboard.add_argument(
        "--report-base",
        default=DEFAULT_REPORT_BASE_NAME,
        help="Base name of the generated report without extension.",
    )
    import_clipboard.add_argument(
        "--scope-kind",
        choices=["file", "function", "selection"],
        default="file",
        help="Optional scope type used to normalize the report title.",
    )
    import_clipboard.add_argument("--scope-name", help="Optional function name or selection label used to normalize the report title.")
    import_clipboard.set_defaults(func=command_import_clipboard)

    run_cmd = subparsers.add_parser("run", help="End-to-end automated path: prepare bundle, call Kimi API, import, and gate.")
    run_cmd.add_argument("--source", required=True, help="Source file to review.")
    run_cmd.add_argument("--report-dir", default="review-reports", help="Directory to write reports into.")
    run_cmd.add_argument(
        "--report-base",
        default=DEFAULT_REPORT_BASE_NAME,
        help="Base name of the generated report without extension.",
    )
    run_cmd.add_argument("--response-output", help="Optional path to persist the raw Kimi response.")
    add_scope_arguments(run_cmd)
    run_cmd.set_defaults(func=command_run)

    run_web_cmd = subparsers.add_parser("run-web", help="End-to-end no-key path: auto-load project skill, drive Kimi web, import, and gate.")
    run_web_cmd.add_argument("--source", required=True, help="Source file to review.")
    run_web_cmd.add_argument("--report-dir", default="review-reports", help="Directory to write reports into.")
    run_web_cmd.add_argument(
        "--report-base",
        default=DEFAULT_REPORT_BASE_NAME,
        help="Base name of the generated report without extension.",
    )
    run_web_cmd.add_argument("--response-output", help="Optional path to persist the raw Kimi web response.")
    run_web_cmd.add_argument("--skill-pack-output", help="Optional path to persist the generated skill pack for Kimi web upload.")
    add_scope_arguments(run_web_cmd)
    run_web_cmd.set_defaults(func=command_run_web)

    validate = subparsers.add_parser("validate", help="Validate generated formal HTML reports.")
    validate.add_argument("--report-dir", default="review-reports", help="Directory containing reports.")
    validate.add_argument("--source", help="Optional reviewed source file. If provided, fail when the source is newer than the report.")
    validate.add_argument(
        "--report-base",
        default=DEFAULT_REPORT_BASE_NAME,
        help="Base name of the generated report without extension.",
    )
    validate.add_argument(
        "--scope-kind",
        choices=["file", "function", "selection"],
        default="file",
        help="Optional scope type used to resolve the default report file name.",
    )
    validate.add_argument("--scope-name", help="Optional function name or selection label used to resolve the default report file name.")
    validate.set_defaults(func=command_validate)

    gate = subparsers.add_parser("gate", help="CI-friendly soft gate: require non-empty, structurally valid reports only.")
    gate.add_argument("--report-dir", default="review-reports", help="Directory containing reports.")
    gate.add_argument("--source", help="Optional reviewed source file. If provided, fail when the source is newer than the report.")
    gate.add_argument(
        "--report-base",
        default=DEFAULT_REPORT_BASE_NAME,
        help="Base name of the generated report without extension.",
    )
    gate.add_argument(
        "--scope-kind",
        choices=["file", "function", "selection"],
        default="file",
        help="Optional scope type used to resolve the default report file name.",
    )
    gate.add_argument("--scope-name", help="Optional function name or selection label used to resolve the default report file name.")
    gate.set_defaults(func=command_gate)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())