"""Shared failure memory: data-only observations activate bounded review rules.

No document text, model instructions, credentials, or generated code are stored.
Recent distinct-document observations use generation-checked GCS updates.
New repair behavior still requires a code change and regression validation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)
VERSION = 2
KINDS = frozenset(('pdf', 'docx', 'pptx', 'xlsx', 'txt', 'md', 'csv', 'json', 'html', 'htm', 'png', 'jpg', 'jpeg', 'webp'))
WINDOW_SECONDS = 30 * 86400
MAX_DOCUMENTS = 200
# Small deployments can learn from one batch, but never from one document alone.
MIN_DOCUMENTS = 3
MIN_FAILURES = 2
MIN_DAYS = 1
MIN_RATE = 0.20
CHECKS = {'numbers': 'protected_entities', 'coverage': 'coverage',
          'text_fit': 'native_text_rendering', 'overflow': 'visual',
          'visual': 'visual', 'immutable_structure': 'immutable_structure'}
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


def _read(bucket, kind):
    """Read a specific generation so concurrent workers cannot overwrite evidence."""
    from google.api_core.exceptions import NotFound
    blob = bucket.blob(f'translation-feedback/v{VERSION}/{kind}.json')
    try:
        blob.reload(timeout=5, retry=None)
    except NotFound:
        return blob, 0, {'version': VERSION, 'salt': secrets.token_hex(32), 'observations': []}
    generation = int(blob.generation)
    if blob.size and blob.size > 256_000:
        raise ValueError('Feedback state exceeds size limit')
    state = json.loads(blob.download_as_bytes(if_generation_match=generation, timeout=5, retry=None))
    if (state.get('version') != VERSION or not isinstance(state.get('salt'), str)
            or len(state['salt']) != 64 or not isinstance(state.get('observations'), list)
            or len(state['observations']) > MAX_DOCUMENTS):
        raise ValueError('Invalid feedback state')
    for row in state['observations']:
        if (set(row) != {'id', 'time', 'eligible', 'failures'}
                or not isinstance(row['id'], str) or len(row['id']) != 64
                or type(row['time']) not in (int, float)
                or not isinstance(row['eligible'], list) or not isinstance(row['failures'], list)
                or any(code not in RULES for code in row['eligible'] + row['failures'])
                or not set(row['failures']).issubset(row['eligible'])):
            raise ValueError('Invalid feedback observation')
    return blob, generation, state


def summarize(state, now=None) -> dict:
    """Count distinct documents, not pages, findings, or retry attempts."""
    now = time.time() if now is None else now
    rows = [row for row in state['observations'] if now - WINDOW_SECONDS <= row['time'] <= now]
    evidence = {}
    for code in RULES:
        eligible = [row for row in rows if code in row['eligible']]
        failures = [row for row in eligible if code in row['failures']]
        days = len({int(row['time'] // 86400) for row in failures})
        rate = len(failures) / len(eligible) if eligible else 0
        evidence[code] = {'documents': len(eligible), 'failures': len(failures),
                          'failure_days': days, 'rate': round(rate, 4),
                          'active': len(eligible) >= MIN_DOCUMENTS and len(failures) >= MIN_FAILURES
                          and days >= MIN_DAYS and rate >= MIN_RATE}
    return evidence


def load_insights(kind: str) -> dict:
    """Unavailable or invalid evidence never changes mandatory quality gates."""
    if kind not in KINDS:
        return {}
    try:
        bucket = _bucket()
        if bucket is None:
            return {}
        return summarize(_read(bucket, kind)[2])
    except Exception:
        logger.warning('Shared quality feedback unavailable; using built-in quality gates.')
        return {}


def load_rules(kind: str) -> list[str]:
    return sorted(code for code, evidence in load_insights(kind).items() if evidence['active'])


def record_report(report) -> None:
    if report is None or report.manifest is None or report.manifest.kind not in KINDS:
        return
    codes = {finding.code for finding in report.findings
             if finding.code in RULES and finding.severity in ('error', 'review')}
    codes.update(code for code in report.observed_failure_codes if code in RULES)
    eligible = {code for code, check in CHECKS.items()
                if report.checks.get(check) in ('passed', 'failed', 'needs_review')}
    if any('unavailable' in finding.code or finding.code == 'specialist_error' for finding in report.findings):
        eligible.clear()  # Partial inspections are not evidence of a clean document.
    eligible.update(codes)
    if not eligible:
        return
    try:
        bucket = _bucket()
        if bucket is None:
            return
        from google.api_core.exceptions import PreconditionFailed
        kind = report.manifest.kind
        for _ in range(3):
            try:
                blob, generation, state = _read(bucket, kind)
                now = time.time()
                rows = [row for row in state['observations'] if now - WINDOW_SECONDS <= row['time'] <= now]
                identifier = hashlib.sha256((state['salt'] + report.manifest.sha256).encode()).hexdigest()
                if any(row['id'] == identifier for row in rows):
                    return  # Re-uploading or resuming a document cannot amplify evidence.
                rows.append({'id': identifier, 'time': now, 'eligible': sorted(eligible), 'failures': sorted(codes)})
                state['observations'] = sorted(rows, key=lambda row: row['time'])[-MAX_DOCUMENTS:]
                blob.upload_from_string(json.dumps(state),
                                        content_type='application/json', if_generation_match=generation,
                                        timeout=5, retry=None)
                return
            except PreconditionFailed:
                continue
        logger.warning('Shared quality feedback update skipped after concurrent writes.')
    except Exception:
        logger.warning('Could not persist shared quality feedback; artifact result is unchanged.')
