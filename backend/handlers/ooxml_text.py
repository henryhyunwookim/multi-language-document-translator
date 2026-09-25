"""Translate text in an Office package without rebuilding its object model.

Only selected XML text nodes are changed. Drawings, relationships, embedded
objects, formulas, and unknown extension parts survive unchanged. Runs remain
separate where their formatting or hyperlink semantics differ.
"""
from __future__ import annotations

import io
import posixpath
import re
from urllib.parse import unquote
from zipfile import ZipFile

from lxml import etree

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"s": S, "a": A}
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _slide_parts(data: bytes) -> list[str]:
    """Resolve display order through presentation relationships, not filenames."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with ZipFile(io.BytesIO(data)) as source:
        root = etree.fromstring(source.read('ppt/presentation.xml'), parser)
        rels = etree.fromstring(source.read('ppt/_rels/presentation.xml.rels'), parser)
        targets = {r.get('Id'): posixpath.normpath(posixpath.join('ppt', unquote(r.get('Target', '')))).lstrip('/')
                   for r in rels if r.get('TargetMode') != 'External'}
        namespace = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        return [targets[node.get('{' + namespace + '}id')]
                for node in root.findall('{*}sldIdLst/{*}sldId')]


def clean_text(text: str) -> str:
    """Normalize Office soft-break escapes before translation and XML writing."""
    return re.sub(r"_x000[bB]_", " ", text).replace("\v", " ")


def _groups(root, kind: str):
    if kind == "docx":
        # Preserve links, drawings, fields, bookmarks and run styling. Text inside
        # field results is opaque because Word can regenerate it on open.
        in_field = 0
        for node in root.iter():
            if node.tag == f"{{{W}}}fldChar":
                action = node.get(f"{{{W}}}fldCharType")
                in_field += 1 if action == "begin" else -1 if action == "end" and in_field else 0
            elif node.tag == f"{{{W}}}t" and not in_field and not any(
                    parent.tag == f"{{{W}}}fldSimple" for parent in node.iterancestors()):
                yield [node]
    if kind == "xlsx":
        # Never translate formula expressions or cached formula string results.
        for node in root.xpath("//s:si/s:t | //s:si/s:r/s:t | "
                               "//s:c[not(s:f)]/s:is/s:t | //s:c[not(s:f)]/s:is/s:r/s:t | "
                               "//s:comment/s:text/s:t | //s:comment/s:text/s:r/s:t", namespaces=NS):
            yield [node]
    # DrawingML occurs in slides, tables, grouped shapes, notes, SmartArt and
    # worksheet drawings. Fields (slide numbers etc.) are deliberately excluded.
    for paragraph in root.iter(f"{{{A}}}p"):
        group = []
        signature = None
        for child in paragraph:
            if child.tag != f"{{{A}}}r":
                if group:
                    yield group
                    group = []
                signature = None
                continue
            node = child.find(f"{{{A}}}t")
            if node is None:
                continue
            props = child.find(f"{{{A}}}rPr")
            current = etree.tostring(props) if props is not None else b""
            if group and current != signature:
                yield group
                group = []
            group.append(node)
            signature = current
        if group:
            yield group


def _translation_units(root, kind: str):
    """Group complete prose across style changes, but never across links or fields."""
    if kind == "xlsx":
        for container in root.xpath('//s:si | //s:c[not(s:f)]/s:is | //s:comment/s:text', namespaces=NS):
            nodes = container.xpath('./s:t | ./s:r/s:t', namespaces=NS)
            if nodes:
                yield nodes
    if kind == "docx":
        allowed = {node for group in _groups(root, kind) for node in group if node.tag == f'{{{W}}}t'}
        def word_runs(container):
            group = []
            for child in container:
                if child.tag == f'{{{W}}}hyperlink':
                    if group:
                        yield group
                        group = []
                    yield from word_runs(child)
                elif child.tag == f'{{{W}}}r':
                    for content in child:
                        if content.tag == f'{{{W}}}rPr':
                            continue
                        if content in allowed:
                            group.append(content)
                        elif group:
                            yield group
                            group = []
                elif child.tag != f'{{{W}}}pPr' and group:
                    yield group
                    group = []
            if group:
                yield group
        for paragraph in root.iter(f'{{{W}}}p'):
            yield from word_runs(paragraph)
    for paragraph in root.iter(f'{{{A}}}p'):
        group, link = [], None
        for child in paragraph:
            node = child.find(f'{{{A}}}t') if child.tag == f'{{{A}}}r' else None
            if node is None:
                if group:
                    yield group
                group, link = [], None
                continue
            properties = child.find(f'{{{A}}}rPr')
            current = tuple(etree.tostring(item) for item in properties if etree.QName(item).localname.startswith('hlink')) if properties is not None else ()
            if group and current != link:
                yield group
                group = []
            group.append(node)
            link = current
        if group:
            yield group


def translate_package(translator, input_file, kind: str) -> io.BytesIO:
    """Patch supported text while copying every original package member."""
    translator.check_cancelled()
    if isinstance(input_file, bytes):
        input_file = io.BytesIO(input_file)
    # Production translators use the shared inspected, reviewed pipeline. The
    # lightweight adapter protocol remains useful to offline preservation tests.
    if getattr(translator, "quality_enabled", False):
        return _translate_with_quality(translator, input_file, kind)
    output = io.BytesIO()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with ZipFile(input_file) as source:
        parts = {}
        segments = []
        translator.sections = []
        for info in source.infolist():
            translator.check_cancelled()
            name = info.filename
            if not name.startswith({"xlsx": "xl/", "pptx": "ppt/", "docx": "word/"}[kind]) or not name.endswith(".xml"):
                continue
            # Embedded files are opaque assets, never translated as outer XML.
            if "/embeddings/" in name:
                continue
            root = etree.fromstring(source.read(info), parser)
            groups = list(_groups(root, kind))
            if not groups:
                continue
            parts[name] = root
            texts = []
            for nodes in groups:
                original = "".join(node.text or "" for node in nodes)
                normalized = clean_text(original)
                key = normalized.strip()
                if key:
                    texts.append(key)
                segments.append((name, nodes, original, normalized, key))
            translator.sections.append({"name": name, "texts": texts, "tone": "unknown"})
        texts = list(dict.fromkeys(segment[4] for segment in segments if segment[4]))
        translator.log(f"Extracted {len(texts)} text segments; preserving original Office objects.", stage="EXTRACT", progress=25)
        translator.check_cancelled()
        if texts:
            translator._analyze_tones()
            translator.log("Translating Office text...", stage="TRANSLATE", progress=40)
            translations = translator._translate_texts(texts)
        else:
            translations = {}
        missing = [text for text in texts if not isinstance(translations.get(text), str)
                   or not translations[text].strip()]
        if missing:
            raise ValueError(f"Translation returned {len(missing)} missing or empty Office text segments.")
        translator.translation_dict = translations
        changed = set()
        for name, nodes, original, normalized, key in segments:
            translator.check_cancelled()
            translated = translations.get(key)
            if not isinstance(translated, str) or not translated.strip():
                translated = key
            # Translation responses sometimes contain formatting hints. Original
            # run properties, including links, are authoritative for Office files.
            translated = re.sub(r"</?span\b[^>]*>", "", clean_text(translated)).strip()
            leading = normalized[:len(normalized) - len(normalized.lstrip())]
            trailing = normalized[len(normalized.rstrip()):]
            replacement = leading + translated + trailing if key else normalized
            if replacement == original:
                continue
            nodes[0].text = replacement
            nodes[0].set(SPACE, "preserve")
            for node in nodes[1:]:
                node.text = ""
            changed.add(name)
        translator.log("Writing preserved Office package...", stage="RENDER", progress=90)
        with ZipFile(output, "w") as target:
            target.comment = source.comment
            for info in source.infolist():
                data = (etree.tostring(parts[info.filename], xml_declaration=True, encoding="UTF-8")
                        if info.filename in changed else source.read(info))
                target.writestr(info, data)
    output.seek(0)
    translator.log("Processing finished.", stage="COMPLETE", progress=100)
    return output


def _translate_with_quality(translator, input_file, kind: str) -> io.BytesIO:
    from backend.quality.inspection import inspect_document
    from backend.quality.models import Segment, QualityFailure, Finding, stable_id
    from backend.quality.supervisor import Supervisor, segment_findings
    from backend.quality.validation import validate_package, review_rendered
    from backend.quality.office_structure import expand_shared_cells
    from backend.quality.components import office_category
    from backend.quality.office_mutations import sheet_names, transform_package

    if hasattr(input_file, "read"):
        original = input_file.read()
    else:
        with open(input_file, "rb") as stream:
            original = stream.read()
    manifest = inspect_document(original, kind)
    sample_parts = getattr(translator, "sample_parts", None)
    if sample_parts is not None:
        manifest.limitations.append("Partial review sample: only these package parts were selected for translation: " + ", ".join(sorted(sample_parts)))
    roots, editable, bindings = {}, {}, {}
    name_bindings, renames, fit_paths = {}, {}, {}
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    prefix = {"xlsx": "xl/", "pptx": "ppt/", "docx": "word/"}[kind]
    with ZipFile(io.BytesIO(original)) as source:
        shared = etree.fromstring(source.read("xl/sharedStrings.xml"), parser) if kind == "xlsx" and "xl/sharedStrings.xml" in source.namelist() else None
        for info in source.infolist():
            translator.check_cancelled()
            name = info.filename
            if sample_parts is not None and name not in sample_parts:
                continue
            if not name.startswith(prefix) or not name.endswith(".xml") or "/embeddings/" in name:
                continue
            if kind == "xlsx" and name == "xl/sharedStrings.xml":
                continue
            root = etree.fromstring(source.read(info), parser)
            if kind == 'xlsx' and name == 'xl/workbook.xml':
                for sheet in root.iter(f'{{{S}}}sheet'):
                    location = root.getroottree().getelementpath(sheet) + '/@name'
                    identifier = stable_id(name, location)
                    title = sheet.get('name')
                    name_bindings[identifier] = title
                    manifest.segments.append(Segment(identifier, title, name, location,
                        'Worksheet title. Translate as a concise Excel tab name (maximum 31 characters).',
                        category='sheet_name'))
            if kind == "xlsx" and name.startswith("xl/worksheets/"):
                expand_shared_cells(root, shared)
            groups = list(_translation_units(root, kind))
            if not groups:
                continue
            roots[name] = root
            editable[name] = [root.getroottree().getelementpath(node) for nodes in groups for node in nodes]
            for group_index, nodes in enumerate(groups):
                context = " ".join("".join(node.text or "" for node in neighbors)
                                   for neighbors in groups[max(0, group_index - 3):group_index + 4])
                text = clean_text("".join(node.text or "" for node in nodes))
                if not text.strip():
                    for node in nodes:
                        node.text = clean_text(node.text or "")
                    continue
                location = root.getroottree().getelementpath(nodes[0])
                identifier = stable_id(name, location)
                parent = nodes[0].getparent()
                protected = {"run_xml": etree.tostring(parent, encoding="unicode")[:2500],
                             "run_texts": [node.text or "" for node in nodes]}
                category = office_category(nodes[0], name)
                manifest.segments.append(Segment(identifier, text.strip(), name, location, context[:5000], protected, category))
                manifest.components.append({'id': identifier, 'part': name, 'location': location, 'category': category})
                bindings[identifier] = (nodes, text)
        translator.log(f"Inspected {len(manifest.segments)} addressable segments and {len(manifest.assets)} package parts.", stage="EXTRACT", progress=20)
        supervisor = Supervisor(translator, manifest)
        if supervisor.model:
            from backend.quality.components import classify_image
            for name in source.namelist():
                extension = name.rsplit('.', 1)[-1].lower()
                if '/media/' in name and extension in ('png', 'jpg', 'jpeg', 'webp'):
                    classify_image(supervisor, source.read(name), 'image/jpeg' if extension in ('jpg', 'jpeg') else 'image/' + extension, name)
        values = supervisor.run()
        report = supervisor.report
        translator.quality_report = report
        if report.finish().status == "failed":
            raise QualityFailure(report)
        from backend.quality.inline_styles import align_inline_styles
        renames = sheet_names(list(name_bindings.values()), [values[key] for key in name_bindings])
        if any(values[key] != renames[title] for key, title in name_bindings.items()):
            report.findings.append(Finding('sheet_name_normalized', 'Translated sheet names were adjusted for Excel length, character or uniqueness constraints.'))
        if renames and any('/connections' in name or '/externalLinks/' in name or
                           (name.startswith('xl/') and name.endswith('.xml') and b'INDIRECT(' in source.read(name).upper())
                           for name in source.namelist()):
            report.findings.append(Finding('dynamic_sheet_references', 'Sheet qualifiers in formulas, defined names, charts and internal hyperlinks are updated. String-built references (such as INDIRECT), external consumers and opaque connections require review.'))
        aligned = align_inline_styles(supervisor, bindings, {key: clean_text(value).strip() for key, value in values.items() if key in bindings})
        def apply_aligned(identifier, pieces):
            nodes, text = bindings[identifier]
            pieces = list(pieces)
            pieces[0] = text[:len(text) - len(text.lstrip())] + pieces[0]
            pieces[-1] += text[len(text.rstrip()):]
            for node, piece in zip(nodes, pieces):
                node.text = piece
                node.set(SPACE, "preserve")
        for identifier, pieces in aligned.items():
            apply_aligned(identifier, pieces)
        output = io.BytesIO()
        with ZipFile(output, "w") as target:
            target.comment = source.comment
            for info in source.infolist():
                raw = etree.tostring(roots[info.filename], encoding="UTF-8", xml_declaration=True) if info.filename in roots else source.read(info)
                target.writestr(info, raw)
    baseline = transform_package(original, renames)
    output = io.BytesIO(transform_package(output.getvalue(), renames))
    defects = validate_package(baseline, output.getvalue(), editable)
    report.findings.extend(defects)
    report.checks["immutable_structure"] = "failed" if defects else "passed"
    if report.finish().status == "failed":
        raise QualityFailure(report)
    visual_findings = review_rendered(supervisor, original, output.getvalue(), kind)
    report.observed_failure_codes = sorted(set(report.observed_failure_codes) | {f.code for f in visual_findings})
    if kind == 'pptx':
        # Prefer resizing text to changing wording. Only slides with observed
        # overflow are candidates; preserve shape extents and all run styles.
        ordered = _slide_parts(original)
        pages = {int(f.location.split(':')[1]) for f in visual_findings
                 if f.location and re.fullmatch(r'page:\d+', f.location)
                 and re.search(r'clip|overflow|overlap', f.message, re.I)}
        for page in pages:
            if not 1 <= page <= len(ordered):
                continue
            part = ordered[page - 1]
            root = roots.get(part)
            if root is None:
                continue
            for body in root.iter(f'{{{A}}}bodyPr'):
                if not any((node.text or '').strip() for node in body.getparent().iter(f'{{{A}}}t')):
                    continue
                auto = body.find(f'{{{A}}}normAutofit')
                value = auto.get('fontScale', '100000') if auto is not None else '100000'
                scale = int(float(value[:-1]) * 1000) if value.endswith('%') else int(value)
                if scale >= 65000:
                    fit_paths.setdefault(part, {})[root.getroottree().getelementpath(body)] = max(55000, int(scale * .85))
        if fit_paths:
            retained_checks = dict(report.checks)
            candidate = transform_package(output.getvalue(), fit_paths=fit_paths)
            candidate_baseline = transform_package(baseline, fit_paths=fit_paths)
            defects = validate_package(candidate_baseline, candidate, editable)
            candidate_findings = review_rendered(supervisor, original, candidate, kind) if not defects else defects
            report.repairs += 1
            # Never replace a reviewed output with an unreviewed or worse one.
            if not candidate_findings and report.checks.get('visual') == 'passed':
                output, baseline = io.BytesIO(candidate), candidate_baseline
                visual_findings = candidate_findings
                report.findings.append(Finding('text_resized', 'Reduced text scale on slides with observed overflow; source geometry and run styles were preserved and the rendered candidate passed review.', 'info'))
            else:
                fit_paths = {}
                report.checks = retained_checks
    # A PowerPoint slide has an unambiguous page-to-part mapping. Repair only
    # clipping/overlap on those slides, preserving geometry and protected runs.
    # Word/Excel pagination does not provide this mapping, so those findings
    # remain explicit review items rather than speculative document edits.
    if kind == "pptx" and supervisor.model:
        pages = {int(f.location.split(":")[1]) for f in visual_findings
                 if f.location and f.location.startswith("page:") and re.search(r"clip|overflow|overlap", f.message, re.I)}
        ordered_parts = _slide_parts(original)
        affected_parts = {ordered_parts[page - 1] for page in pages if 1 <= page <= len(ordered_parts)}
        repair_segments = [s for s in manifest.segments if s.part in affected_parts]
        if repair_segments:
            try:
                critique = [Finding("visual_fit", "Use a concise but complete translation to resolve reported clipping or overlap. Preserve all meaning and numbers.", segment_id=s.id, location=s.location) for s in repair_segments]
                repaired = supervisor.translate(repair_segments, critique)
                defects = [f for f in supervisor.check_entities(repair_segments, repaired) if f.severity != "info"]
                defects.extend(supervisor.review(repair_segments, repaired))
                report.repairs += 1
                if not defects:
                    repaired_alignment = align_inline_styles(supervisor, bindings, {key:clean_text(value).strip() for key,value in repaired.items()})
                    for identifier, pieces in repaired_alignment.items():
                        apply_aligned(identifier, pieces)
                    candidate = io.BytesIO()
                    with ZipFile(io.BytesIO(original)) as source, ZipFile(candidate, "w") as target:
                        target.comment = source.comment
                        for info in source.infolist():
                            raw = etree.tostring(roots[info.filename], encoding="UTF-8", xml_declaration=True) if info.filename in roots else source.read(info)
                            target.writestr(info, raw)
                    candidate = io.BytesIO(transform_package(candidate.getvalue(), renames, fit_paths))
                    structure_defects = validate_package(baseline, candidate.getvalue(), editable)
                    if not structure_defects:
                        retained_checks = dict(report.checks)
                        candidate_findings = review_rendered(supervisor, original, candidate.getvalue(), kind)
                        if not candidate_findings and report.checks.get('visual') == 'passed':
                            output = candidate
                            visual_findings = candidate_findings
                        else:
                            report.checks = retained_checks
                            visual_findings.append(Finding('visual_repair_rejected', 'The revised translation did not pass rendered review; retained the prior artifact.'))
                    else:
                        visual_findings.append(Finding('visual_repair_rejected', 'The candidate changed protected structure; retained the prior artifact.'))
                else:
                    visual_findings.append(Finding("visual_repair_rejected", "The concise revision failed source-grounded review; retained the prior translation."))
            except InterruptedError:
                raise
            except Exception as exc:
                visual_findings.append(Finding("visual_repair_unavailable", str(exc)))
    report.findings.extend(visual_findings)
    report.finish()
    if report.status == "failed":
        raise QualityFailure(report)
    translator.log(f"Quality result: {report.status}. Review report accompanies this artifact.", stage="REVIEW", progress=95)
    output.seek(0)
    return output
