#!/usr/bin/env python3
"""
===============================================================================
Portable Sample Review HTML Index Builder
===============================================================================

Purpose:
    Generates a standalone, browser-readable HTML dashboard (index.html)
    summarizing all generated Korean sample translations, source excerpts,
    quality reports, and review findings in output/sample-reviews/sample-review.

Usage:
    python tools/index_sample_review.py
===============================================================================
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

ROOT_CANDIDATES = [
    Path(__file__).resolve().parents[2] / 'output' / 'sample-reviews' / 'sample-review',
    Path(__file__).resolve().parents[2] / 'output' / 'sample-review',
]
root = next((p for p in ROOT_CANDIDATES if p.exists()), ROOT_CANDIDATES[0])

if not (root / 'selection.json').exists():
    print(f"Notice: selection.json not found in {root}; skipping index generation.")
    sys.exit(0)

rows = json.loads((root / 'selection.json').read_text(encoding='utf-8'))
cards = []
for row in rows:
    sample = row['sample']
    output = sample.replace('.source-sample.', '.ko.')
    report = root / (output + '.quality.json')
    quality = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    scope = ', '.join(f'{key}: {row[key]}' for key in ('pages', 'slides', 'sheet_positions', 'body_blocks') if key in row)
    links = [('Source excerpt', sample)]
    if (root / output).exists():
        links.append(('Korean output', output))
    if report.exists():
        links.append(('Quality report', report.name))
    findings = quality.get('findings', [])
    messages = list(dict.fromkeys(f['code'] + ': ' + f['message'] for f in findings))
    cards.append('<article><h2>' + html.escape(row['source']) + '</h2><p>' + html.escape(scope) + '</p>'
                 + '<p>Status: <strong>' + html.escape(quality.get('status', 'pending')) + '</strong></p>'
                 + '<p>' + ' · '.join('<a href="' + quote(name) + '">' + label + '</a>' for label, name in links) + '</p>'
                 + '<p>' + html.escape(row.get('note', '')) + '</p>'
                 + '<details><summary>Review findings (' + str(len(findings)) + ')</summary><ul>'
                 + ''.join('<li>' + html.escape(message) + '</li>' for message in messages) + '</ul></details></article>')
page = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Korean sample review</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#172b40;background:#f6f8fa}article{background:white;border:1px solid #d8e0e8;border-radius:12px;padding:24px;margin:20px 0}h2{font-size:20px;overflow-wrap:anywhere}a{color:#0758a6}li{margin:12px 0}summary{cursor:pointer}</style>
<h1>Korean sample outputs / 한국어 샘플 검토</h1>
<p>Compare each source excerpt with its Korean output. These are live system outputs, not manually corrected reference translations. Existing Korean may remain unchanged.</p>
<p><strong>Restricted completion:</strong> The company presentation, pricing workbook and contract now translate only allowlisted generic headings and labels. Only a fixed dictionary-label list was sent remotely for these three samples. Other content remains unchanged locally. These files are NOT redacted and may still contain sensitive source content. The other four outputs were generated in the earlier run.</p>
<p>Check terminology, completeness, diagrams, hyperlinks, tables, numbers and clipping. “Needs review” means unresolved findings or unavailable checks. Office rendering was unavailable on this machine; native Office layout needs manual review. The APF PDF loses its original diagram and logos.</p>
<p>Workbook copies retain hidden sheets and dependencies to preserve formulas and objects. Translation is limited to the selected visible sheets and their drawing parts; hidden sheets remain in the source language. Presentation translation is limited to the selected slides, retaining master/layout text unchanged. PDF excerpts use original page positions; the employment-rules excerpt covers contents pages.</p>
'''
(root / 'index.html').write_text(page + ''.join(cards) + '</html>', encoding='utf-8')
print('Review index written.')
