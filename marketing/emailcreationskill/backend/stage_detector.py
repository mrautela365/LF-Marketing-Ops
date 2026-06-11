"""
Campaign stage detection — maps event date to the 13-stage marketing journey.
"""
from datetime import datetime, date
import re

STAGES = [
    {"name": "Event Announcement",               "funnel": "TOFU",      "email_type": "Invite",      "min": 100,   "max": 9999},
    {"name": "CFP Launch",                        "funnel": "TOFU",      "email_type": "Invite",      "min": 85,    "max": 99},
    {"name": "Registration Launch",               "funnel": "TOFU",      "email_type": "Invite",      "min": 70,    "max": 84},
    {"name": "Co-Located Events + CFP Reminder",  "funnel": "MOFU",      "email_type": "Invite",      "min": 50,    "max": 69},
    {"name": "DEI & Travel Fund",                 "funnel": "MOFU",      "email_type": "Newsletter",  "min": 42,    "max": 49},
    {"name": "Schedule Announcement",             "funnel": "MOFU",      "email_type": "Newsletter",  "min": 28,    "max": 41},
    {"name": "Main Registration Push",            "funnel": "BOFU",      "email_type": "Reminder",    "min": 14,    "max": 27},
    {"name": "Final Countdown",                   "funnel": "BOFU",      "email_type": "Last Chance", "min": 3,     "max": 13},
    {"name": "Event Week",                        "funnel": "BOFU",      "email_type": "Reminder",    "min": -2,    "max": 2},
    {"name": "Thank You + Survey",                "funnel": "FOLLOW-UP", "email_type": "Newsletter",  "min": -3,    "max": -1},
    {"name": "Content & Recordings Release",      "funnel": "FOLLOW-UP", "email_type": "Newsletter",  "min": -14,   "max": -4},
    {"name": "Next Event CFP Teaser",             "funnel": "FOLLOW-UP", "email_type": "Newsletter",  "min": -28,   "max": -15},
    {"name": "Community Nurture",                 "funnel": "FOLLOW-UP", "email_type": "Newsletter",  "min": -9999, "max": -29},
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


def parse_event_date(date_strings: list) -> date | None:
    """Parse scraped date strings into a Python date object. Returns the earliest found."""
    if not date_strings:
        return None
    parsed = []
    for ds in date_strings:
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
    return min(parsed) if parsed else None


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

    today = date.today()
    days = (event_date - today).days

    for s in STAGES:
        if s["min"] <= days <= s["max"]:
            name = s["name"]
            return {
                "name": name,
                "funnel": s["funnel"],
                "email_type": s["email_type"],
                "days_to_event": days,
                "goal": STAGE_GOALS.get(name, ""),
                "cta_label": CTA_LABELS.get(name, "Learn More"),
                "event_date_str": event_date.strftime("%B %d, %Y"),
                "color": FUNNEL_COLORS.get(s["funnel"], "#6b7280"),
            }

    # Fallback for edge cases
    name = "Community Nurture" if days < 0 else "Event Announcement"
    funnel = "FOLLOW-UP" if days < 0 else "TOFU"
    return {
        "name": name,
        "funnel": funnel,
        "email_type": "Newsletter",
        "days_to_event": days,
        "goal": STAGE_GOALS.get(name, ""),
        "cta_label": CTA_LABELS.get(name, "Learn More"),
        "event_date_str": event_date.strftime("%B %d, %Y"),
        "color": FUNNEL_COLORS.get(funnel, "#6b7280"),
    }
