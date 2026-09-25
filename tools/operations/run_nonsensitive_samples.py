#!/usr/bin/env python3
"""
===============================================================================
Non-Sensitive Allowlist Translation & Local Document Patcher
===============================================================================

Purpose:
    Translates an explicit generic-label allowlist and patches private
    documents locally. No source file, filename, context, image, metadata or
    source-derived prompt is passed to the model.

Usage:
    python tools/operations/run_nonsensitive_samples.py
===============================================================================
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
import io
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'

ROOT_CANDIDATES = [
    Path(__file__).resolve().parents[2] / 'output' / 'sample-reviews' / 'sample-review',
    Path(__file__).resolve().parents[2] / 'output' / 'sample-review',
]
ROOT = next((p for p in ROOT_CANDIDATES if p.exists()), ROOT_CANDIDATES[0])
LABELS = [
    'Contract', 'Re-Seller', 'Price', 'Preis', 'Notes:', 'Bemerkung:',
    'Grundsätzliches:', 'Basic:', 'Test Server:', 'Special case', 'Sonderfall:',
    'Maintenance fee:', 'Wartungsgebühr:', 'Process Framework',
    '基本情報', '会社名', 'Company Name', '設立', 'Date of Establishment',
    'Capital', '本社所在地', 'Head Office', 'President', '資本金',
    '従業員数', 'Total Employees', '代表取締役', 'カリキュラム',
    '情報セキュリティ', 'コンプライアンス', '文書作成',
    'プレゼンテーション', '日本語', 'プログラミング', 'ガイダンス',
    '技術課題', 'マイルストーン', '中間評価', '改善プラン',
    '初期評価', 'テスト', '最終評価', 'E-Learning',
]
PROMPT = ('Translate these generic dictionary labels into Korean. Return ONLY a JSON array '
          'of translated strings in the same order, one nonempty string per label. '
          'Do not add explanations. Labels:\n' + json.dumps(LABELS, ensure_ascii=False))


def main():
    # Persist the exact application payload for local inspection before networking.
    (ROOT / 'nonsensitive-request.json').write_text(json.dumps({'prompt': PROMPT}, ensure_ascii=False, indent=2), encoding='utf-8')
    mapping_path = ROOT / 'generic-label-translations.json'
    if not mapping_path.exists():
        from backend.core.cloud_secrets import get_gemini_api_key
        from backend.core.model_client import create_model
        model = create_model('gemini-2.5-flash', get_gemini_api_key())
        response = model.generate_content(PROMPT, generation_config={'response_mime_type': 'application/json'}, request_options={'timeout': 90})
        values = json.loads(response.text)
        if not isinstance(values, list) or len(values) != len(LABELS) or not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError('Incomplete generic vocabulary translation.')
        mapping_path.write_text(json.dumps(dict(zip(LABELS, values)), ensure_ascii=False, indent=2), encoding='utf-8')
    translations = json.loads(mapping_path.read_text(encoding='utf-8'))

    # Everything below is offline, including reading the source samples.
    from lxml import etree
    from backend.handlers.ooxml_text import _groups, SPACE
    from backend.quality.office_structure import expand_shared_cells
    from backend.quality.validation import validate_package
    rows = json.loads((ROOT / 'results.json').read_text(encoding='utf-8'))
    for row in rows:
        if row['status'] != 'failed':
            continue
        source = ROOT / row['sample']
        output = ROOT / row['output']
        report_path = ROOT / (row['output'] + '.quality.json')
        old = json.loads(report_path.read_text(encoding='utf-8'))
        selected = [s for s in old['manifest']['segments'] if s['source'] in translations]
        if not selected:
            raise ValueError('No allowlisted labels in sample.')
        original = source.read_bytes()
        editable, roots = {}, {}
        count = 0
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        with ZipFile(io.BytesIO(original)) as package:
            shared = etree.fromstring(package.read('xl/sharedStrings.xml'), parser) if 'xl/sharedStrings.xml' in package.namelist() else None
            for part in {s['part'] for s in selected}:
                root = etree.fromstring(package.read(part), parser)
                if part.startswith('xl/worksheets/'):
                    expand_shared_cells(root, shared)
                groups = {root.getroottree().getelementpath(nodes[0]): nodes for nodes in _groups(root, source.suffix[1:])}
                for segment in [s for s in selected if s['part'] == part]:
                    nodes = groups[segment['location']]
                    text = ''.join(n.text or '' for n in nodes)
                    if text.strip() != segment['source']:
                        raise ValueError('Source label identity mismatch.')
                    nodes[0].text = text[:len(text)-len(text.lstrip())] + translations[segment['source']] + text[len(text.rstrip()):]
                    nodes[0].set(SPACE, 'preserve')
                    for node in nodes[1:]:
                        node.text = ''
                    editable.setdefault(part, []).extend(root.getroottree().getelementpath(n) for n in nodes)
                    count += 1
                roots[part] = root
            buffer = io.BytesIO()
            with ZipFile(buffer, 'w') as target:
                target.comment = package.comment
                for info in package.infolist():
                    raw = etree.tostring(roots[info.filename], encoding='UTF-8', xml_declaration=True) if info.filename in roots else package.read(info)
                    target.writestr(info, raw)
        defects = validate_package(original, buffer.getvalue(), editable)
        if defects:
            raise ValueError('Local package preservation check failed.')
        output.write_bytes(buffer.getvalue())
        # Retain previous failure evidence without representing it as this result.
        archive = report_path.with_name(report_path.name + '.previous-failure.json')
        if not archive.exists():
            archive.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding='utf-8')
        report = {'status': 'needs_review', 'checks': {'immutable_structure': 'passed', 'full_translation': 'not_attempted', 'semantic': 'unavailable', 'visual': 'unavailable'},
                  'translated_label_occurrences': count, 'remote_payload': 'Fixed generic-label allowlist only; no documents, filenames, context, images or metadata.',
                  'findings': [{'code': 'restricted_partial_sample', 'severity': 'review', 'message': 'Only generic headings and labels were translated. All other content remains unchanged locally, including sensitive content. This file is NOT redacted and is NOT a full translation.'}]}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        row.update(status='needs_review', scope='Generic headings and labels only; sensitive content unchanged locally.', translated_label_occurrences=count)
        row.pop('error_type', None)
        (ROOT / (output.name + '.result.json')).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
        print('READY', output.name, count, 'generic label occurrences', flush=True)
    (ROOT / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
