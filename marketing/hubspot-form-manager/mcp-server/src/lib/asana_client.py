"""
Async Asana API client.
Handles auth and base URL for task reads and comment writes.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from .credentials import get_asana_pat

BASE_URL = "https://app.asana.com/api/1.0"


def _build_client() -> httpx.AsyncClient:
    pat = get_asana_pat()
    if not pat:
        raise RuntimeError(
            "ASANA_PAT is not configured. "
            "Open http://localhost:8000/setup to enter your credentials, "
            "or skip Asana pre-fill and fill the form manually."
        )
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
        },
        timeout=20.0,
    )


def extract_task_gid(url_or_gid: str) -> str:
    """
    Extract the numeric task GID from a full Asana URL or return it unchanged
    if it's already a bare GID.

    Asana URL patterns (task GID is always the LAST long numeric segment):
      https://app.asana.com/1/{workspace}/{project}/{task_gid}/f   ← new format
      https://app.asana.com/1/{workspace}/task/{task_gid}
      https://app.asana.com/0/{project}/{task_gid}
      https://app.asana.com/0/search/{task_gid}
    """
    url_or_gid = url_or_gid.strip()
    # Already a bare numeric GID
    if re.fullmatch(r"\d+", url_or_gid):
        return url_or_gid
    # Find ALL long numeric segments — task GID is always the last one
    matches = re.findall(r"/(\d{10,})(?=[/?#]|$)", url_or_gid)
    if matches:
        return matches[-1]
    raise ValueError(
        f"Cannot extract a task GID from: {url_or_gid!r}. "
        "Please provide either an Asana task URL or a bare numeric GID."
    )


async def asana_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    async with _build_client() as client:
        r = await client.get(path, params=params)
        r.raise_for_status()
        return r.json()


async def asana_post(path: str, json: dict[str, Any]) -> dict[str, Any]:
    async with _build_client() as client:
        r = await client.post(path, json=json)
        r.raise_for_status()
        return r.json()
