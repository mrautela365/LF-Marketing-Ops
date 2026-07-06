"""
Async HubSpot API client.
Handles auth, base URL, and retries on 429 rate-limit responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .credentials import get_hubspot_api_key

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hubapi.com"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # seconds


def _build_client() -> httpx.AsyncClient:
    api_key = get_hubspot_api_key()
    if not api_key:
        raise RuntimeError(
            "HUBSPOT_API_KEY is not configured. "
            "Open http://localhost:8000/setup to enter your credentials."
        )
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


async def hubspot_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    """
    Make an authenticated request to the HubSpot API.
    Retries up to MAX_RETRIES times on 429 responses with exponential backoff.
    Raises httpx.HTTPStatusError for non-2xx responses after retries.
    """
    for attempt in range(MAX_RETRIES + 1):
        async with _build_client() as client:
            response = await client.request(method, path, params=params, json=json)

        if response.status_code == 429 and attempt < MAX_RETRIES:
            retry_after = float(response.headers.get("Retry-After", RETRY_BACKOFF_BASE ** attempt))
            logger.warning("HubSpot rate limit hit. Retrying in %.1fs (attempt %d).", retry_after, attempt + 1)
            await asyncio.sleep(retry_after)
            continue

        if not response.is_success:
            # Include the response body in the error so callers can see HubSpot's reason
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise httpx.HTTPStatusError(
                f"Client error '{response.status_code} {response.reason_phrase}' "
                f"for url '{response.url}'\nHubSpot detail: {detail}",
                request=response.request,
                response=response,
            )
        if response.content:
            return response.json()
        return {}

    # re-raise after exhausting retries
    try:
        detail = response.json()
    except Exception:
        detail = response.text
    raise httpx.HTTPStatusError(
        f"Client error '{response.status_code} {response.reason_phrase}' "
        f"for url '{response.url}'\nHubSpot detail: {detail}",
        request=response.request,
        response=response,
    )


async def hs_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    return await hubspot_request("GET", path, params=params)


async def hs_post(path: str, json: dict[str, Any]) -> dict[str, Any] | list[Any]:
    return await hubspot_request("POST", path, json=json)


async def hs_patch(path: str, json: dict[str, Any]) -> dict[str, Any] | list[Any]:
    return await hubspot_request("PATCH", path, json=json)


async def hs_delete(path: str) -> dict[str, Any] | list[Any]:
    return await hubspot_request("DELETE", path)
