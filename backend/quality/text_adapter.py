"""Stable text addresses and deterministic reconstruction for structured text."""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from backend.quality.inspection import inspect_document
from backend.quality.models import Segment, QualityFailure, Finding, stable_id
from backend.quality.supervisor import Supervisor


def translate_structured(translator, data: bytes, kind: str) -> io.BytesIO:
    manifest = inspect_document(data, kind)
    source = data.decode("utf-8-sig")
    bindings = {}

    def add(text: str, location: str, setter, context=""):
        if not text.strip() or not any(character.isalpha() for character in text):
            return
        identifier = stable_id(kind, location)
        category = 'table_cell' if kind == 'csv' else 'structured_value' if kind == 'json' else 'text'
        manifest.segments.append(Segment(identifier, text.strip(), kind, location, context or text, category=category))
        manifest.components.append({'id': identifier, 'category': category, 'part': kind, 'location': location})
        bindings[identifier] = (setter, text)

    if kind == "json":
        document = json.loads(source)
        root_box = [document]

        def walk(value: Any, path: str, setter):
            if isinstance(value, str):
                add(value, path, setter, path + ": " + value)
            elif isinstance(value, dict):
                for key, child in value.items():
                    walk(child, path + "/" + key.replace("~", "~0").replace("/", "~1"), lambda text, obj=value, key=key: obj.__setitem__(key, text))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}/{index}", lambda text, obj=value, index=index: obj.__setitem__(index, text))
        walk(document, "", lambda text: root_box.__setitem__(0, text))
        render = lambda: json.dumps(root_box[0], ensure_ascii=False, indent=2)
    elif kind == "csv":
        try:
            dialect = csv.Sniffer().sniff(source[:8192])
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(source, newline=""), dialect))
        for row_index, row in enumerate(rows):
            context = json.dumps(row, ensure_ascii=False)
            for column, text in enumerate(row):
                if text.startswith('='):
                    continue  # CSV spreadsheet expressions are immutable data.
                add(text, f"row:{row_index + 1}/column:{column + 1}", lambda text, row=row, column=column: row.__setitem__(column, text), context)
        def render():
            result = io.StringIO(newline="")
            csv.writer(result, dialect).writerows(rows)
            return result.getvalue()
    elif kind in ("html", "htm"):
        from bs4 import BeautifulSoup, Comment
        document = BeautifulSoup(source, "html.parser")
        for index, node in enumerate(document.find_all(['table', 'img', 'svg'])):
            manifest.components.append({'id': f'object:{index}', 'part': kind,
                'category': {'table': 'table', 'img': 'image_unknown', 'svg': 'diagram'}[node.name]})
        for index, node in enumerate(list(document.find_all(string=True))):
            if isinstance(node, Comment) or any(parent.name in ("script", "style", "code", "pre") for parent in node.parents):
                continue
            add(str(node), f"text:{index}", lambda text, node=node: node.replace_with(text), node.parent.get_text()[:3000])
        for index, node in enumerate(document.find_all(True)):
            for attribute in ("alt", "title", "aria-label"):
                if attribute in node.attrs:
                    add(str(node[attribute]), f"element:{index}/@{attribute}", lambda text, node=node, attribute=attribute: node.__setitem__(attribute, text))
        render = lambda: str(document)
    else:
        # Retain all original syntax as fixed slices. Markdown code and link
        # destinations are protected; only prose spans become editable segments.
        protected = []
        if kind == "md":
            pattern = r"(?ms)^```.*?^```[^\n]*|^~~~.*?^~~~[^\n]*|`[^`\n]*`|\]\([^\n)]*\)|https?://[^\s]+|^\s*\[[^\]]+\]:[^\n]*$|<[^>]*>"
            protected = [(m.start(), m.end()) for m in re.finditer(pattern, source)]
            protected.extend((m.start(), m.end()) for m in re.finditer(r"(?m)^[ \t]*(?:#{1,6}[ \t]+|[-+*][ \t]+|\d+[.)][ \t]+|>[ \t]*)", source))
        replacements = {}
        pattern = r"[^\n\r#*_|\[\]<>`~()]+" if kind == "md" else r"[^\r\n]+"
        for index, match in enumerate(re.finditer(pattern, source)):
            start, end = match.span()
            # Split prose around protected intervals rather than discarding a
            # whole line containing a link or code fragment.
            cuts = [(start, end)]
            for left, right in protected:
                cuts = [(a, b) for x, y in cuts for a, b in ((x, min(y, left)), (max(x, right), y)) if a < b] if any(left < y and right > x for x, y in cuts) else cuts
            for left, right in cuts:
                text = source[left:right]
                add(text, f"offset:{left}:{right}", lambda text, left=left, right=right: replacements.__setitem__((left, right), text), source[max(0, left - 150):right + 150])
        def render():
            result = source
            for (start, end), text in sorted(replacements.items(), reverse=True):
                result = result[:start] + text + result[end:]
            return result
    supervisor = Supervisor(translator, manifest)
    values = supervisor.run()
    translator.quality_report = supervisor.report
    if supervisor.report.finish().status == "failed":
        raise QualityFailure(supervisor.report)
    for identifier, value in values.items():
        setter, text = bindings[identifier]
        if kind == "csv" and value.lstrip().startswith(('=', '+', '-', '@')) and not text.lstrip().startswith(('=', '+', '-', '@')):
            supervisor.report.findings.append(Finding("csv_expression", "Translation introduced a spreadsheet expression into a text cell.", "error", identifier))
            raise QualityFailure(supervisor.report)
        if kind == "md":
            value = re.sub(r"\s*\r?\n\s*", " ", value)
            value = re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", value)
        setter(text[:len(text) - len(text.lstrip())] + value.strip() + text[len(text.rstrip()):])
    result = render()
    # The native constructors retain keys, cells, attributes and syntax. Parsing
    # output again rejects serialization defects before releasing an artifact.
    inspect_document(result.encode("utf-8"), kind)
    supervisor.report.checks["native_syntax"] = "passed"
    supervisor.report.finish()
    return io.BytesIO(result.encode("utf-8"))
