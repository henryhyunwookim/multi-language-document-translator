"""Cancellable retries that resume the rejected request after provider cooldown."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import time
import socket

import httpx


def is_transient_provider_error(error) -> bool:
    """Retry transport outages and temporary HTTP failures, never bad requests."""
    if isinstance(error, InterruptedError):
        return False
    code = getattr(error, 'code', None)
    if callable(code):
        code = code()
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    return (code in (408, 500, 502, 503, 504) or status in (408, 500, 502, 503, 504)
            or isinstance(error, (httpx.TransportError, ConnectionError, TimeoutError, socket.gaierror)))


def retry_delay(error, attempt: int) -> float | None:
    code = getattr(error, 'code', None)
    if callable(code):
        code = code()
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    if code != 429 and status != 429 and not any(
            token in str(error).lower() for token in ('429', 'resource_exhausted', 'resourceexhausted', 'rate limit')):
        return None
    headers = getattr(response, 'headers', {}) or {}
    value = headers.get('Retry-After') or headers.get('retry-after')
    if value:
        try:
            return max(1, float(value))
        except (ValueError, TypeError):
            try:
                return max(1, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass
    details = getattr(error, 'details', None)
    if not isinstance(details, (list, tuple)) and response is not None:
        try:
            details = response.json().get('error', {}).get('details', [])
        except (ValueError, AttributeError, TypeError):
            details = []
    for detail in details if isinstance(details, (list, tuple)) else []:
        duration = getattr(detail, 'retry_delay', None)
        if duration is not None:
            return max(1, duration.seconds + duration.nanos / 1_000_000_000)
        if isinstance(detail, dict) and isinstance(detail.get('retryDelay'), str):
            match = re.fullmatch(r'(\d+(?:\.\d+)?)s', detail['retryDelay'])
            if match:
                return max(1, float(match[1]))
    match = re.search(r'(?:retry[ _-]?(?:after|delay)|retry in)\D{0,20}(\d+(?:\.\d+)?)\s*s', str(error), re.I)
    return max(1, float(match[1])) if match else min(300, 15 * 2 ** min(attempt, 5))


def retry_rate_limited(operation, check_cancelled, log, *, max_wait=None, max_transient_retries=3):
    """Keep resuming after cooldown until success or cancellation.

    Callers may supply a total wait bound. The default honors provider reset
    times even for long quota windows. Transport and temporary server failures
    get a separate bounded retry allowance; invalid requests fail immediately.
    """
    waited, attempt, transient_attempt = 0.0, 0, 0
    while True:
        check_cancelled()
        try:
            return operation()
        except Exception as error:
            delay = retry_delay(error, attempt)
            transient = delay is None and is_transient_provider_error(error)
            if transient:
                if transient_attempt >= max_transient_retries:
                    log('Temporary provider failure persisted after retries. Saved translations are retained; '
                        'check connectivity and choose Resume failed/cancelled files.', stage='WAIT')
                    raise
                delay = min(30, 2 ** (transient_attempt + 1))
                transient_attempt += 1
            if delay is None or (max_wait is not None and waited + delay > max_wait):
                raise
            reason = 'Temporary provider connection/server failure' if transient else 'Provider rate limit'
            log(f'{reason}: resuming this request in {delay:.0f} seconds.', stage='WAIT')
            remaining = delay
            while remaining > 0:
                check_cancelled()
                pause = min(1.0, remaining)
                time.sleep(pause)
                remaining -= pause
                if remaining > 0 and int(delay - remaining) % 60 == 0:
                    log(f'Waiting for provider rate-limit reset; retry in {remaining:.0f} seconds.', stage='WAIT')
            waited += delay
            attempt += 1
