"""Tiny async HTTP wrapper used by every outbound integration.

Standardises:
* request construction (bearer auth, JSON body),
* timeout defaults,
* error handling (turns httpx exceptions into ``(False, body)`` so callers
  never raise mid-pipeline),
* structured logging (logs the URL, status code, and a snippet of the
  upstream error body — never the request payload, which may contain PII).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
DEFAULT_DOWNLOAD_TIMEOUT = 30


def _build_headers(
    *, auth_token: str | None, content_type: str | None = "application/json"
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _format_error(exc: httpx.HTTPError) -> str | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        return response.text
    except Exception:
        return None


async def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    auth_token: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    log_label: str = "http",
) -> tuple[bool, str | None]:
    """POST ``payload`` as JSON. Returns ``(ok, error_body)``.

    ``error_body`` is the upstream response text when available so callers
    can surface it in their own error messages (handy for Graph/Telegram).
    """
    headers = _build_headers(auth_token=auth_token)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        body = _format_error(exc)
        logger.error("%s POST %s failed: %s — body: %s", log_label, url, exc, body)
        return False, body
    return True, None


async def get_json(
    url: str,
    *,
    auth_token: str | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    log_label: str = "http",
) -> tuple[bool, dict[str, Any] | None]:
    """GET a JSON response. Returns ``(ok, body_dict_or_None)``."""
    headers = _build_headers(auth_token=auth_token, content_type=None)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return True, resp.json()
    except httpx.HTTPError as exc:
        logger.error("%s GET %s failed: %s", log_label, url, exc)
        return False, None


async def get_bytes(
    url: str,
    *,
    auth_token: str | None = None,
    timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
    log_label: str = "http",
) -> bytes | None:
    """GET raw bytes (e.g. media download). Returns ``None`` on failure."""
    headers = _build_headers(auth_token=auth_token, content_type=None)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as exc:
        logger.error("%s GET %s (bytes) failed: %s", log_label, url, exc)
        return None
