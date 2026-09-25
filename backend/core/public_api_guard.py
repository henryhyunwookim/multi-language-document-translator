"""Small, process-local request guards for the public translation API.

These limits reduce accidental and opportunistic resource exhaustion. They are
not a replacement for a shared edge rate limiter such as Cloud Armor because
Cloud Run can serve requests from multiple instances.
"""
from __future__ import annotations

from collections import deque
import hashlib
import os
import threading
import time
from typing import Deque

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SlidingWindowRateLimiter:
    """Limit requests per identity while keeping only recent timestamps."""

    def __init__(self, *, limit: int = 30, window_seconds: int = 60) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("Rate limit and window must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, identity: str) -> int | None:
        """Return retry seconds when limited, otherwise record and allow."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events.setdefault(identity, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return max(1, int(events[0] + self.window_seconds - now + 0.999))
            events.append(now)

            # Bound memory if many one-off clients hit a long-lived instance.
            if len(self._events) > 10_000:
                self._events = {
                    key: values
                    for key, values in self._events.items()
                    if values and values[-1] > cutoff
                }
        return None


_PUBLIC_LIMITER = SlidingWindowRateLimiter()


def is_google_translate_provider(provider: str) -> bool:
    """Recognize only the supported free-provider identifiers."""
    return provider.strip().casefold() in {
        "google-translate",
        "google translate",
        "google translate (free)",
    }


def check_public_request_limit(request: Request, *, category: str = "translate") -> None:
    """Apply a per-client limit to public, resource-consuming API actions.

    Cloud Run places the original caller address first in X-Forwarded-For.
    Outside Cloud Run, use the direct ASGI peer address and ignore that header.
    The per-instance limit is defense in depth; production still needs a shared
    edge limit because a caller can be routed to another Cloud Run instance.
    """
    peer = request.client.host if request.client else "unknown"
    if os.environ.get("K_SERVICE"):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            peer = forwarded.split(",", 1)[0].strip() or peer

    digest = hashlib.sha256(f"{category}:{peer}".encode("utf-8")).hexdigest()
    retry_after = _PUBLIC_LIMITER.check(digest)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Request limit reached. Wait briefly and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def request_body_limit(path: str) -> int:
    """Choose conservative body limits while preserving documented batch caps."""
    if path == "/jobs/batches":
        return 260 * 1024 * 1024  # 256 MiB files plus multipart framing.
    if path in {"/translate/document", "/translate/document/stream"}:
        return 66 * 1024 * 1024  # 64 MiB file plus multipart framing.
    if path == "/translate/text":
        return 512 * 1024
    return 2 * 1024 * 1024


class RequestBodyLimitMiddleware:
    """Reject oversized requests before multipart parsing or file processing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        limit = request_body_limit(scope.get("path", ""))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    await self._too_large(send)
                    return
            except ValueError:
                await self._too_large(send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _RequestBodyTooLarge
            return message

        response_started = False

        async def track_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, track_send)
        except _RequestBodyTooLarge:
            if not response_started:
                await self._too_large(send)

    @staticmethod
    async def _too_large(send: Send) -> None:
        body = b'{"detail":"Request body exceeds the limit for this endpoint."}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


class _RequestBodyTooLarge(Exception):
    pass
