"""
Form naming convention helpers.

LF Events pattern: [YYQ#] - [Team] - [Event Name] [Year]
Example: "26Q2 - LF Events - CloudNativeCon Europe 2026"
"""

from __future__ import annotations

import re


def parse_name_parts(form_name: str) -> dict[str, str]:
    """
    Parse an existing LF-style form name into its components.

    Returns a dict with keys: quarter, team, event, year
    Returns empty values for any part that doesn't match.

    >>> parse_name_parts("26Q1 - LF Events - MCP NA 2026")
    {'quarter': '26Q1', 'team': 'LF Events', 'event': 'MCP NA', 'year': '2026'}
    """
    pattern = r"^(\d{2}Q\d)\s*-\s*(.+?)\s*-\s*(.+?)\s+(\d{4})\s*$"
    m = re.match(pattern, form_name.strip())
    if not m:
        return {"quarter": "", "team": "", "event": form_name.strip(), "year": ""}
    return {
        "quarter": m.group(1),
        "team": m.group(2).strip(),
        "event": m.group(3).strip(),
        "year": m.group(4),
    }


def derive_form_name(
    reference_form_name: str,
    new_event_name: str,
    new_quarter: str,
    new_year: str | None = None,
) -> str:
    """
    Derive a new form name from a reference form name and new event details.

    Preserves the team segment from the reference form.
    Uses new_year if provided; otherwise extracts year from reference or infers from quarter.

    >>> derive_form_name("26Q1 - LF Events - MCP NA 2026", "CloudNativeCon Europe", "26Q2")
    '26Q2 - LF Events - CloudNativeCon Europe 2026'

    >>> derive_form_name("26Q1 - LF Events - MCP NA 2026", "OpenSSF Day", "26Q3", "2026")
    '26Q3 - LF Events - OpenSSF Day 2026'
    """
    parts = parse_name_parts(reference_form_name)
    team = parts.get("team") or "LF Events"

    # Resolve year: explicit > from reference > infer from quarter prefix
    if new_year:
        year = new_year
    elif parts.get("year"):
        year = parts["year"]
    else:
        # Infer from quarter prefix: "26Q2" → "2026"
        century_prefix = new_quarter[:2] if len(new_quarter) >= 2 else "26"
        year = f"20{century_prefix}"

    # Validate quarter format
    new_quarter = new_quarter.strip().upper()
    if not re.match(r"^\d{2}Q\d$", new_quarter):
        raise ValueError(
            f"Invalid quarter format: {new_quarter!r}. Expected format: YYQ# (e.g. '26Q2')."
        )

    return f"{new_quarter} - {team} - {new_event_name.strip()} {year}"


def suggest_form_name(event_name: str, team: str, quarter: str, year: str) -> str:
    """
    Build a form name from scratch when no reference form is available.

    >>> suggest_form_name("DockerCon 2026", "LF Events", "26Q2", "2026")
    '26Q2 - LF Events - DockerCon 2026 2026'
    """
    quarter = quarter.strip().upper()
    if not re.match(r"^\d{2}Q\d$", quarter):
        raise ValueError(f"Invalid quarter format: {quarter!r}. Expected: YYQ# (e.g. '26Q2').")
    return f"{quarter} - {team.strip()} - {event_name.strip()} {year.strip()}"
