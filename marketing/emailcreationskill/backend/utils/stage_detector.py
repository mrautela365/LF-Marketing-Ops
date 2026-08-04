"""
Campaign stage detection — maps event date to the 13-stage marketing journey.
"""
from datetime import datetime, date
import json
import re
from pathlib import Path

# Full marketing journey detail per stage — strategy, expected performance, content ideas,
# and researched industry-best-practice guidance (structure/CTA/urgency-FOMO/specificity).
# Keys match the STAGES name field. Source of truth: templates/marketing_journey_stages.json
_JOURNEY_JSON_PATH = Path(__file__).resolve().parent.parent / "templates" / "marketing_journey_stages.json"
with open(_JOURNEY_JSON_PATH, "r", encoding="utf-8") as _f:
    MARKETING_JOURNEY: dict[str, dict] = json.load(_f)

STAGES = [
    {"name": "Event Announcement",               "funnel": "TOFU",      "email_type": "Invite",      "min": 105,   "max": 9999},
    {"name": "CFP Launch",                        "funnel": "TOFU",      "email_type": "Invite",      "min": 98,    "max": 104},
    {"name": "Registration Launch",               "funnel": "TOFU",      "email_type": "Invite",      "min": 84,    "max": 97},
    {"name": "Co-Located Events + CFP Reminder",  "funnel": "MOFU",      "email_type": "Invite",      "min": 70,    "max": 83},
    {"name": "DEI & Travel Fund",                 "funnel": "MOFU",      "email_type": "Invite",      "min": 63,    "max": 69},
    {"name": "Schedule Announcement",             "funnel": "MOFU",      "email_type": "Invite",      "min": 49,    "max": 62},
    {"name": "Main Registration Push",            "funnel": "BOFU",      "email_type": "Invite",      "min": 35,    "max": 48},
    {"name": "Final Countdown",                   "funnel": "BOFU",      "email_type": "Invite",      "min": 14,    "max": 34},
    {"name": "Event Week",                        "funnel": "BOFU",      "email_type": "Invite",      "min": 0,     "max": 13},
    {"name": "Thank You + Survey",                "funnel": "FOLLOW-UP", "email_type": "Invite",      "min": -3,    "max": -1},
    {"name": "Content & Recordings Release",      "funnel": "FOLLOW-UP", "email_type": "Invite",      "min": -17,   "max": -4},
    {"name": "Next Event CFP Teaser",             "funnel": "FOLLOW-UP", "email_type": "Invite",      "min": -31,   "max": -18},
    {"name": "Community Nurture",                 "funnel": "FOLLOW-UP", "email_type": "Invite",      "min": -9999, "max": -32},
]

STAGE_GOALS = {
    "Event Announcement":               "Generate excitement, announce key details, drive awareness",
    "CFP Launch":                       "Invite speakers to submit proposals, emphasize visibility and impact",
    "Registration Launch":              "Drive early registrations, highlight early-bird pricing and value",
    "Co-Located Events + CFP Reminder": "Highlight co-located events, create urgency around CFP deadline",
    "DEI & Travel Fund":                "Promote DEI scholarships and travel funding opportunities",
    "Schedule Announcement":            "Highlight keynotes and sessions, build anticipation, drive ticket purchases",
    "Main Registration Push":           "Strong registration CTA with social proof, speaker highlights, urgency",
    "Final Countdown":                  "Urgency-driven messaging — registration closes very soon",
    "Event Week":                       "Logistics, venue details, what to expect, build on-site excitement",
    "Thank You + Survey":               "Thank attendees for joining, gather feedback via post-event survey",
    "Content & Recordings Release":     "Share session recordings, slides, and key community takeaways",
    "Next Event CFP Teaser":            "Tease upcoming event dates/location, invite early speaker interest",
    "Community Nurture":                "Stay connected, share community updates, preview upcoming events",
}

CTA_LABELS = {
    "Event Announcement":               "Learn More",
    "CFP Launch":                       "Submit Your Proposal",
    "Registration Launch":              "Register Now",
    "Co-Located Events + CFP Reminder": "Register & Submit CFP",
    "DEI & Travel Fund":                "Apply for Funding",
    "Schedule Announcement":            "View the Schedule",
    "Main Registration Push":           "Register Now",
    "Final Countdown":                  "Register Before It's Too Late",
    "Event Week":                       "View Event Details",
    "Thank You + Survey":               "Take the Survey",
    "Content & Recordings Release":     "Watch the Sessions",
    "Next Event CFP Teaser":            "Stay Informed",
    "Community Nurture":                "Stay Connected",
}

FUNNEL_COLORS = {
    "TOFU": "#16a34a",       # green
    "MOFU": "#d97706",       # amber
    "BOFU": "#dc2626",       # red
    "FOLLOW-UP": "#7c3aed",  # purple
}


_MONTH_RE = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
             r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")


def _parse_all_dates(date_strings: list) -> list:
    """Parse scraped date strings into Python date objects, including BOTH ends of any
    range found in a single string (e.g. "June 15-16, 2026" → [June 15, June 16]), so
    callers can derive the full event date range, not just the earliest day."""
    if not date_strings:
        return []
    parsed = []
    for ds in date_strings:
        ds = (ds or "").strip()
        # ISO / slash formats first (e.g. schema.org startDate "2026-09-07",
        # "2026/09/07"). Take the leading date token if a time/offset follows.
        iso_m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", ds)
        if iso_m:
            try:
                y, mo, d = (int(g) for g in iso_m.groups())
                parsed.append(date(y, mo, d))
                continue
            except ValueError:
                pass
        # Capture the end day of an inline range ("June 15-16, 2026") before it gets
        # stripped below, so the range's last day isn't lost.
        range_m = re.match(
            r"(" + _MONTH_RE + r")[\s,]+\d{1,2}(?:st|nd|rd|th)?[\s,–\-]+"
            r"(\d{1,2})(?:st|nd|rd|th)?[\s,]+(20\d{2})",
            ds, re.I,
        )
        # Normalize ranges like "June 15-16, 2026" → "June 15, 2026"
        ds_clean = re.sub(r"(\b\w+ \d+)[-–]\d+", r"\1", ds).strip()
        # Remove ordinal suffixes: 1st, 2nd, 3rd, 15th → 1, 2, 3, 15
        ds_clean = re.sub(r"(\d+)(?:st|nd|rd|th)", r"\1", ds_clean)
        for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
            try:
                parsed.append(datetime.strptime(ds_clean, fmt).date())
                break
            except ValueError:
                continue
        if range_m:
            month, end_day, year = range_m.group(1), range_m.group(2), range_m.group(3)
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed.append(datetime.strptime(f"{month} {end_day}, {year}", fmt).date())
                    break
                except ValueError:
                    continue
    return parsed


def parse_event_date(date_strings: list) -> date | None:
    """Parse scraped date strings into a Python date object. Returns the earliest found."""
    parsed = _parse_all_dates(date_strings)
    return min(parsed) if parsed else None


def parse_event_end_date(date_strings: list) -> date | None:
    """Parse scraped date strings into a Python date object. Returns the latest found
    (the last day of the event, when the source gives a multi-day range)."""
    parsed = _parse_all_dates(date_strings)
    return max(parsed) if parsed else None


def format_event_date_range(start: date, end: date | None) -> str:
    """Format a start/end date pair as a human-readable range, e.g. "September 7–9, 2026"
    or "August 30 – September 1, 2026". Falls back to a single date when there is no
    distinct end date."""
    if not end or end <= start:
        return f"{start.strftime('%B')} {start.day}, {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%B')} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return f"{start.strftime('%B')} {start.day} – {end.strftime('%B')} {end.day}, {start.year}"
    return f"{start.strftime('%B')} {start.day}, {start.year} – {end.strftime('%B')} {end.day}, {end.year}"


def detect_stage(event_dates: list) -> dict:
    """
    Given a list of scraped event date strings, return the campaign stage dict.
    Returns: name, funnel, email_type, days_to_event, goal, cta_label, event_date_str, color
    """
    event_date = parse_event_date(event_dates)

    if not event_date:
        return {
            "name": "Unknown",
            "funnel": "TOFU",
            "email_type": "Invite",
            "days_to_event": None,
            "goal": "Promote the event and drive registrations",
            "cta_label": "Register Now",
            "event_date_str": "",
            "color": "#6b7280",
        }

    event_end_date = parse_event_end_date(event_dates)
    event_date_str = format_event_date_range(event_date, event_end_date)

    today = date.today()
    days = (event_date - today).days

    for s in STAGES:
        if s["min"] <= days <= s["max"]:
            name = s["name"]
            mj = MARKETING_JOURNEY.get(name, {})
            return {
                "name": name,
                "funnel": s["funnel"],
                "email_type": s["email_type"],
                "days_to_event": days,
                "goal": STAGE_GOALS.get(name, ""),
                "cta_label": CTA_LABELS.get(name, "Learn More"),
                "event_date_str": event_date_str,
                "color": FUNNEL_COLORS.get(s["funnel"], "#6b7280"),
                "stage_number": mj.get("stage_number"),
                "timeline": mj.get("timeline", ""),
                "marketing_strategy": mj.get("marketing_strategy", ""),
                "content_ideas": mj.get("content_ideas", []),
                "industry_best_practices": mj.get("industry_best_practices", {}),
            }

    # Fallback for edge cases
    name = "Community Nurture" if days < 0 else "Event Announcement"
    funnel = "FOLLOW-UP" if days < 0 else "TOFU"
    mj = MARKETING_JOURNEY.get(name, {})
    return {
        "name": name,
        "funnel": funnel,
        "email_type": "Invite",
        "days_to_event": days,
        "goal": STAGE_GOALS.get(name, ""),
        "cta_label": CTA_LABELS.get(name, "Learn More"),
        "event_date_str": event_date_str,
        "color": FUNNEL_COLORS.get(funnel, "#6b7280"),
        "stage_number": mj.get("stage_number"),
        "timeline": mj.get("timeline", ""),
        "marketing_strategy": mj.get("marketing_strategy", ""),
        "content_ideas": mj.get("content_ideas", []),
        "industry_best_practices": mj.get("industry_best_practices", {}),
    }
