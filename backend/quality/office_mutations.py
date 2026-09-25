"""Narrow, reproducible non-text edits with an independently checked baseline."""
from __future__ import annotations

import io
import re
from zipfile import ZipFile
from lxml import etree

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'


def sheet_names(originals, translations):
    """Excel names must be nonempty, unique ignoring case, and <=31 characters."""
    result, used = {}, set()
    for original, translated in zip(originals, translations):
        base = re.sub(r'[\x00-\x1f\\/*?:\[\]]', ' ', translated).strip().strip("'").strip()[:31].rstrip("' ") or original
        if base.casefold() == 'history':
            base = base[:29] + '_1'
        candidate, index = base, 2
        while candidate.casefold() in used:
            suffix = f' ({index})'
            candidate = base[:31-len(suffix)] + suffix
            index += 1
        used.add(candidate.casefold())
        result[original] = candidate
    return result


def rewrite_reference(expression, names):
    """Rewrite sheet qualifiers outside string literals, including 3-D ranges.

    External workbook qualifiers are untouched. INDIRECT string literals are
    deliberately excluded: their meaning cannot be inferred statically.
    """
    lookup = {key.casefold(): value for key, value in names.items()}
    pattern = re.compile(r'''(?P<string>"(?:[^"]|"")*")|(?P<bracket>\[[^\]]*\])|(?<![\w.\]'])(?P<qualifier>'(?:[^']|'')*'|[\w.\u0080-\uffff]+(?::[\w.\u0080-\uffff]+)?)!''')
    def replace(match):
        # Lex strings, structured references and quoted sheet qualifiers in one
        # pass: a double quote inside a single-quoted sheet name is not a string.
        qualifier = match['qualifier']
        if qualifier is None:
            return match[0]
        decoded = qualifier[1:-1].replace("''", "'") if qualifier.startswith("'") else qualifier
        if '[' in decoded or ']' in decoded:
            return match[0]
        parts = decoded.split(':')
        changed = [lookup.get(part.casefold(), part) for part in parts]
        if parts == changed:
            return match[0]
        return "'" + ':'.join(changed).replace("'", "''") + "'!"
    return pattern.sub(replace, expression)


def transform_package(data: bytes, names=None, fit_paths=None) -> bytes:
    """Apply only validated sheet renames/reference updates and text autofit.

    fit_paths maps parts to bodyPr paths and explicit font scale percentages.
    Geometry, styles, object relationships and formula operators stay intact.
    """
    names, fit_paths = names or {}, fit_paths or {}
    output = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, 'w') as target:
        target.comment = source.comment
        for info in source.infolist():
            raw = source.read(info)
            if (names and info.filename.startswith('xl/') and info.filename.endswith('.xml')
                    and '/embeddings/' not in info.filename) or info.filename in fit_paths:
                root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
                unchanged = etree.tostring(root)
                for node in root.iter():
                    local = etree.QName(node).localname
                    if names and node.tag == f'{{{S}}}sheet' and node.get('name') in names:
                        node.set('name', names[node.get('name')])
                    if names and local in ('f', 'formula', 'formula1', 'formula2', 'definedName',
                                           'calculatedColumnFormula', 'totalsRowFormula') and node.text:
                        node.text = rewrite_reference(node.text, names)
                    if names and node.tag == f'{{{S}}}worksheetSource' and node.get('sheet') in names:
                        node.set('sheet', names[node.get('sheet')])
                    if names and node.tag == f'{{{S}}}hyperlink' and node.get('location'):
                        node.set('location', rewrite_reference(node.get('location'), names))
                for path, scale in fit_paths.get(info.filename, {}).items():
                    if not isinstance(scale, int) or not 55000 <= scale <= 100000:
                        raise ValueError('Unsafe text scale')
                    body = root.find(path)
                    if body is None or body.tag != f'{{{A}}}bodyPr':
                        raise ValueError('Missing text body for fit repair')
                    for child in list(body):
                        if child.tag in {f'{{{A}}}{tag}' for tag in ('noAutofit', 'normAutofit', 'spAutoFit')}:
                            body.remove(child)
                    auto = etree.Element(f'{{{A}}}normAutofit', fontScale=str(scale))
                    # Autofit precedes 3D and extension properties in CT_TextBodyProperties.
                    following = {f'{{{A}}}{tag}' for tag in ('scene3d', 'sp3d', 'flatTx', 'extLst')}
                    position = next((i for i, child in enumerate(body) if child.tag in following), len(body))
                    body.insert(position, auto)
                if etree.tostring(root) != unchanged:
                    raw = etree.tostring(root, encoding='UTF-8', xml_declaration=True)
            target.writestr(info, raw)
    return output.getvalue()
