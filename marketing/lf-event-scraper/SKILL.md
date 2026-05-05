---
name: lf-event-scraper
description: >
  Scrapes a Linux Foundation event page and returns structured event data: exact dates,
  location, audience, themes, pricing tiers, and all relevant URLs. Use this as Step 1
  whenever starting any LF paid media campaign. Output feeds directly into the
  campaign-brief-generator skill.

  Trigger when the user says: "scrape this event", "get event details from", "start a
  campaign for [URL]", or provides any events.linuxfoundation.org URL.
---

# LF Event Scraper

Fetches a live LF event page and extracts all structured data needed to build a
campaign brief. Always scrapes live — never use LLM training-data memory for dates.

## ⚠️ Critical Rule: Dates Must Come from the Live Page

Prior-year dates are a known LLM failure mode. If the event ran in 2024, the model
may confidently output 2024 dates for a 2025/2026 edition. This skill must always
fetch the live page and extract dates from the HTML — never infer them.

## Input

| Field | Description |
|-------|-------------|
| `event_url` | Full URL of the LF event, e.g. `https://events.linuxfoundation.org/mcp-dev-summit-mumbai/` |

## Output Schema

Produce a fenced JSON block with this exact schema. This is consumed directly by
`campaign-brief-generator`:

```json
{
  "event_name": "MCP Dev Summit Mumbai",
  "event_slug": "mcp-dev-summit-mumbai",
  "dates": "Jun 14–15, 2026",
  "start_date": "2026-06-14",
  "end_date": "2026-06-15",
  "year": "2026",
  "city": "Mumbai",
  "country": "India",
  "region_code": "IN",
  "venue": "Venue name if available",
  "audience_description": "MCP maintainers, AI/ML engineers, fintech and enterprise devs",
  "themes": ["MCP protocol", "production AI agents", "security", "enterprise integration"],
  "format": "2-day; keynotes, breakouts, solutions showcase, Day-1 reception",
  "pricing": [
    { "tier": "General", "price": "$X", "deadline": "YYYY-MM-DD" }
  ],
  "registration_url": "https://events.linuxfoundation.org/.../register/",
  "agenda_url": "https://events.linuxfoundation.org/.../schedule/",
  "cfp_url": "https://events.linuxfoundation.org/.../cfp/",
  "speakers_url": "https://events.linuxfoundation.org/.../speakers/",
  "presented_by": "Agentic AI Foundation",
  "cfp_open": true,
  "sponsors": ["Sponsor A", "Sponsor B"]
}
```

## Steps

### Step 1: Fetch the event home page

Call `WebFetch` with the `event_url`. Use this prompt:

> "Extract: event name, exact dates (day month year — all three required), city, country,
> venue name, audience description, tracks/themes, pricing tiers with deadlines, registration
> URL, agenda/schedule URL, CFP URL, speakers URL, and the organizing or presenting foundation.
> List sponsors if visible. Return raw extracted text."

### Step 2: Validate dates — fail loudly if missing

Check that extracted dates contain:
- Day (e.g. 14), month name or number (e.g. Jun), and 4-digit year (e.g. 2026)

If any component is missing:
1. Try fetching the `/register/` or `/schedule/` sub-page for dates
2. If still not found, **stop and ask the user**: "Could not extract event dates from the
   page. Please provide the dates manually (e.g. 'Jun 14–15, 2026')."

Never proceed with incomplete or assumed dates.

### Step 3: Derive computed fields

| Field | Derivation |
|-------|------------|
| `event_slug` | Lowercase event name, spaces and special chars → hyphens. Strip leading/trailing hyphens. |
| `region_code` | ISO 3166-1 alpha-2 code for the event country (e.g. India → `IN`, USA → `US`) |
| `start_date` / `end_date` | ISO 8601 format `YYYY-MM-DD` derived from extracted dates |
| `year` | 4-digit year extracted from dates |
| `registration_url` | If not found on page, construct as `{event_url}register/` |
| `agenda_url` | If not found, construct as `{event_url}schedule/` |
| `cfp_url` | If not found on page, set to `null` |

### Step 4: Output

Return the completed JSON block. Summarise in one sentence what was found and flag
any fields that defaulted to null or constructed values so the user can verify.

**Example summary:**
> "Scraped MCP Dev Summit Mumbai. Dates: Jun 14–15, 2026. CFP URL not found on page —
> set to null. Registration URL constructed (not explicitly linked on home page)."
