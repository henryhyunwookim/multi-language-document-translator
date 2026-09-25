"""Shared failure memory: data-only observations activate bounded review rules.

No document text, model instructions, credentials, or generated code are stored.
Each failure code has its own immutable GCS object, avoiding lost-update races.
New repair behavior still requires a code change and regression validation.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)
VERSION = 1
RULES = {
    'numbers': ('source_review', 'Check numeric equivalence and identifiers before accepting each translation.'),
    'coverage': ('source_review', 'Check every source component for omissions and duplicate translations.'),
    'text_fit': ('visual_review', 'Check text against its container bounds and report clipping without omitting content.'),
    'overflow': ('visual_review', 'Check translated glyph bounds, table cells and shape text for overflow.'),
    'visual': ('table_review', 'Check table cell associations and merged headers; preserve empty cells and artwork.'),
    'immutable_structure': ('source_review', 'Preserve native object structure and all protected references.'),
}


def _bucket():
    name = os.getenv('TRANSLATION_FEEDBACK_BUCKET', '').strip()
    if not name:
        return None
    from google.cloud import storage
    return storage.Client().bucket(name)


def load_rules(kind: str) -> list[str]:
    """An absent/offline store never changes the mandatory quality gates."""
    try:
        bucket = _bucket()
        if bucket is None:
            return []
        prefix = f'translation-feedback/v{VERSION}/{kind}/'
        result = []
        for blob in bucket.list_blobs(prefix=prefix, max_results=32, timeout=5, retry=None):
            code = blob.name.removeprefix(prefix).removesuffix('.json')
            if code in RULES:
                import json
                value = json.loads(blob.download_as_bytes(timeout=5, retry=None))
                if value == {'version': VERSION, 'kind': kind, 'code': code}:
                    result.append(code)
        return sorted(set(result))
    except Exception:
        logger.warning('Shared quality feedback unavailable; using built-in quality gates.')
        return []


def record_report(report) -> None:
    if report is None or report.manifest is None:
        return
    codes = {finding.code for finding in report.findings
             if finding.code in RULES and finding.severity in ('error', 'review')}
    codes.update(code for code in report.observed_failure_codes if code in RULES)
    if not codes:
        return
    try:
        bucket = _bucket()
        if bucket is None:
            return
        import json
        from google.api_core.exceptions import PreconditionFailed
        kind = report.manifest.kind
        for code in sorted(codes):
            blob = bucket.blob(f'translation-feedback/v{VERSION}/{kind}/{code}.json')
            try:
                blob.upload_from_string(json.dumps({'version': VERSION, 'kind': kind, 'code': code}),
                                        content_type='application/json', if_generation_match=0,
                                        timeout=5, retry=None)
            except PreconditionFailed:
                pass  # Another worker has already recorded exactly this failure class.
    except Exception:
        logger.warning('Could not persist shared quality feedback; artifact result is unchanged.')
