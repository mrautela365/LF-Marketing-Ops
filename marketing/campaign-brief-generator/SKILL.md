---
name: campaign-brief-generator
description: >
  Generates a complete multi-platform paid media campaign brief as a formatted Excel
  workbook (.xlsx) for any LF event. Covers Google Search (RSA + keywords), Google
  Display, Meta (FB/IG), LinkedIn Sponsored Content, and X/Twitter. Integrates with
  HubSpot for UTM campaign tokens and registers tracking URLs in the UTM Link Builder
  Google Sheet.

  Trigger when the user says: "generate a campaign brief", "build the brief for",
  "create a brief for [event]", or after running lf-event-scraper.

  Prerequisite: lf-event-scraper output (EventDetails JSON), or user provides event
  details manually.
---

# Campaign Brief Generator

Builds a 6-tab Excel campaign brief for any LF event, ready for marketer review
and approval before any ad spend begins.

## Prerequisites

| Requirement | Available? | Fallback if missing |
|-------------|-----------|---------------------|
| Event data | JSON from `lf-event-scraper` or state file | Ask user for fields manually |
| HubSpot MCP (`search_crm_objects`, `manage_crm_objects`) | Optional | Ask user for `hs_utm` token directly |
| Google Ads MCP (`build_utm_url`) | Optional | Use built-in Python UTM builder (see below) |
| Python + openpyxl | Required | Install: `pip install openpyxl` |

**This skill is designed to work with zero external MCP connections.** All MCP tools
are optional — see the fallback paths in each step.

## Configuration

| Setting | Value |
|---------|-------|
| UTM Link Builder Sheet ID | `1AVFVYTo92kncOdtwyblS_M96m_gq6k2dG1rpueEMy6Q` |
| Output file pattern | `{event_slug}-campaign-brief.xlsx` |
| State file pattern | `{event_slug}-campaign-state.json` |
| Output directory | Working directory (or `/Users/misharautela/`) |

## Fallback UTM Builder (no MCP needed)

If `build_utm_url` MCP tool is not connected, construct URLs with this Python snippet:

```python
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

def build_utm_url(base_url, utm_source, utm_medium, utm_campaign,
                  utm_term="", utm_content=""):
    params = {
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
    }
    if utm_term:   params["utm_term"]    = utm_term
    if utm_content: params["utm_content"] = utm_content
    sep = "&" if "?" in base_url else "?"
    return base_url.rstrip("/") + "/" + sep + urlencode(params)
```

Use this function wherever `build_utm_url` MCP calls appear in the steps below.

## Output

A `.xlsx` workbook with 6 tabs:

| Tab | Contents |
|-----|----------|
| `Overview` | Event details, UTM master table, Stakeholder Inputs block |
| `Google Search` | RSA headlines + char counts, descriptions, sitelinks, keyword list |
| `Google Display` | Display copy fields + char counts, image crop spec table |
| `Meta` | Primary text, headlines, CTA, audience strategy note |
| `LinkedIn` | Intro text, headlines, CTA, targeting criteria table |
| `X Twitter` | Tweet variants with char counts, targeting spec |

---

## Step-by-Step Workflow

### Step 0: Load state file (token saver)

Check for `{event_slug}-campaign-state.json` in the working directory.

**If the file exists**, load it and skip any steps whose outputs are already populated:

| State field populated | Skip |
|-----------------------|------|
| `event_name`, `dates`, `registration_url` | Step 1 validation (data already confirmed) |
| `hs_utm` | Steps 2a–2d (HubSpot already resolved) |
| `utm_sheet_rows` | Steps 3–4 (UTMs already built and registered) |
| `brief_file` (and file exists on disk) | Steps 5–8 (brief already generated) |

Tell the user what was loaded vs what will be regenerated. This saves re-running
HubSpot API calls and UTM construction on subsequent sessions.

### Step 1: Validate event data

Confirm the following fields are present. If any are missing, ask the user:

- `event_name`, `event_slug`, `dates`, `year`, `city`, `country`, `region_code`
- `audience_description`, `themes`
- `registration_url` (required for ad final URLs)

### Step 2: HubSpot — look up or create the campaign object

HubSpot is the source of truth for campaign attribution. Every paid campaign must be
linked to a HubSpot campaign object so UTM-tagged visits can be attributed in HubSpot
reporting. The campaign's `hs_utm` token is what ties all platform UTMs together.

#### 2a. Check state file first

If `hs_utm` is already set in the state file, skip the HubSpot API calls entirely
and proceed directly to Step 3. The token is already resolved.

#### 2b. Search for an existing HubSpot campaign (if hs_utm missing)

**If HubSpot MCP is not connected:** ask the user:
> "HubSpot MCP is not available. Please provide the hs_utm token for this campaign
> (format: `{numericId}-{URL-encoded-name}`, e.g. `42462239-MCP%20Dev%20Summit%20Mumbai`).
> You can find it in HubSpot → Marketing → Campaigns → [campaign] → UTM parameters."

If the user provides it, save to state file and skip to Step 3.

**If HubSpot MCP is connected:** call `search_crm_objects`:
```json
{
  "objectType": "campaigns",
  "filterGroups": [{
    "filters": [{
      "propertyName": "hs_name",
      "operator": "CONTAINS_TOKEN",
      "value": "{event_name}"
    }]
  }],
  "properties": ["hs_name", "hs_utm", "hs_goal", "hs_start_date", "hs_end_date"]
}
```

If multiple results return, pick the one whose `hs_name` most closely matches the
full event name (including year if present).

#### 2c. Extract the hs_utm token

The `hs_utm` property has the format:

```
{numericCampaignId}-{URL-encoded campaign name}
```

Example: `42462239-MCP%20Dev%20Summit%20Mumbai`

This token becomes the `utm_campaign` value in **all** tracking URLs across every
platform. It is how HubSpot links a website visit back to this specific campaign.

**Save this token** — it is used in every UTM URL in Steps 3 and 4.

#### 2d. Create campaign if not found

If no matching campaign exists, call `manage_crm_objects` to create one:

```json
{
  "objectType": "campaigns",
  "operation": "create",
  "properties": {
    "hs_name": "{event_name}",
    "hs_goal": "AWARENESS",
    "hs_notes": "Paid media campaign for {event_name} — {dates}, {city}. Auto-created by campaign brief generator."
  }
}
```

After creation, call `search_crm_objects` again to retrieve the `hs_utm` token
(it is generated server-side and not returned directly from the create call).

#### 2e. Verify campaign properties

Confirm or update these HubSpot campaign properties (call `manage_crm_objects`
with operation `update` if any are missing):

| Property | Expected value |
|----------|---------------|
| `hs_name` | Full event name (e.g. `MCP Dev Summit Mumbai`) |
| `hs_goal` | `AWARENESS` or `LEAD_GENERATION` |
| `hs_start_date` | Campaign start date (Unix ms) — leave blank if stakeholder hasn't confirmed |
| `hs_end_date` | Campaign end date (Unix ms) — leave blank if unknown |

### Step 3: Build UTM-tagged URLs for all platforms

Use the `build_utm_url` MCP tool to construct and validate each tracking URL.
Call it once per platform row below.

**UTM field mapping (matches HubSpot's attribution model):**

| UTM Parameter | Maps to | Notes |
|---------------|---------|-------|
| `utm_campaign` | HubSpot `hs_utm` token | Same value for all platforms |
| `utm_source` | Traffic source | Platform-specific (see table) |
| `utm_medium` | Channel type | Platform-specific (see table) |
| `utm_term` | Ad group identifier | Campaign name + ad group slug |
| `utm_content` | Ad creative descriptor | Differentiates ads within an ad group |

**Per-platform UTM values:**

| Platform | utm_source | utm_medium | utm_term | utm_content |
|----------|-----------|------------|----------|-------------|
| Google Search | `google` | `paid-search` | `{slug}-search-high-intent` | `events-{slug}-{region}-conv` |
| Google Display | `google` | `display` | `{slug}-display-prospecting` | `events-{slug}-{region}-conv` |
| Meta | `facebook` | `paid-social` | `{slug}-meta-prospecting` | `events-{slug}-{region}-conv` |
| LinkedIn | `linkedin` | `paid-social` | `{slug}-linkedin-prospecting` | `events-{slug}-{region}-conv` |
| X / Twitter | `twitter` | `paid-social` | `{slug}-twitter-prospecting` | `events-{slug}-{region}-conv` |

`utm_campaign` = `{hs_utm}` for all platforms (the token from Step 2b).

**Example call to `build_utm_url`:**
```json
{
  "base_url": "https://events.linuxfoundation.org/mcp-dev-summit-mumbai/register/",
  "utm_source": "google",
  "utm_medium": "paid-search",
  "utm_campaign": "42462239-MCP%20Dev%20Summit%20Mumbai",
  "utm_term": "mcp-dev-summit-mumbai-search-high-intent",
  "utm_content": "events-mcp-dev-summit-mumbai-in-conv"
}
```

> Note: LF event pages return HTTP 403 to bots — `url_resolves: false` is expected
> and acceptable. The URL structure is still correct. Do not flag this as an error.

Collect all 5 built URLs into a table for the Overview tab and Step 4.

### Step 4: Register UTM rows in the UTM Link Builder Google Sheet

Write all platform rows into the UTM Link Builder Google Sheet so the full tracking
URLs are recorded and shareable with the broader marketing team.

**Sheet ID:** `1AVFVYTo92kncOdtwyblS_M96m_gq6k2dG1rpueEMy6Q`

Append one row per platform to the next available row. Column mapping:

| Column | Field | Example value |
|--------|-------|---------------|
| A | Campaign Name | `MCP Dev Summit Mumbai` |
| B | utm_source | `google` |
| C | utm_medium | `paid-search` |
| D | utm_campaign (hs_utm) | `42462239-MCP%20Dev%20Summit%20Mumbai` |
| E | utm_term | `mcp-dev-summit-mumbai-search-high-intent` |
| F | utm_content | `events-mcp-dev-summit-mumbai-in-conv` |
| G | Landing Page (base URL) | `https://events.linuxfoundation.org/.../register/` |
| H | *(formula — auto-calculates full URL from cols B–G)* | *(do not write)* |

After writing, confirm Column H is populated (it contains a formula that assembles
the full UTM URL). If H is blank, the sheet formula may need re-evaluation — notify
the user.

Record the row numbers written (e.g. rows 1040–1044) in the brief's Overview tab
so the team can find them.

### Step 5: Generate ad copy (in-context — no external API needed)

Generate all platform copy directly. Apply character limits strictly.

#### Google Ads Search — RSA
- **15 headlines** ≤ 30 chars each — vary themes: event name, protocol name, city, CTA
- **10 descriptions** ≤ 90 chars each — benefits, dates, audience, urgency
- **6 sitelinks**: headline ≤ 25 chars, two description lines ≤ 35 chars each
  - Suggested sitelinks: Register Now · View Agenda · Call for Proposals · Speakers ·
    Sponsorship · About the Event

**Google character limit reference:**

| Asset | Limit |
|-------|-------|
| RSA Headline | 30 chars |
| RSA Description | 90 chars |
| Sitelink Headline | 25 chars |
| Sitelink Description Line | 35 chars |

#### Google Display
- Short headline ≤ 30 chars
- Long headline ≤ 90 chars
- Description ≤ 90 chars
- Business name ≤ 25 chars (use: `Linux Foundation Events`)
- Image spec table: landscape 1.91:1 (1200×628), square 1:1 (1200×1200), portrait 4:5 (960×1200)

> ⚠️ Design team must provide both landscape AND square images. Auto-cropping from
> event page often fails for square format. Flag in the Stakeholder Inputs block.

#### Meta (Facebook / Instagram)
- 3 primary text variants ≤ 500 chars (preview truncates at ~125)
- 3 headline variants ≤ 40 chars
- CTA button: `Register Now`
- Audience strategy note (see Step 6)

#### LinkedIn Sponsored Content
- 3 intro text variants ≤ 150 chars
- 3 headline variants ≤ 70 chars
- CTA: `Register`
- Targeting: Job titles (Software Engineer, AI Engineer, ML Engineer, Solutions Architect,
  CTO, VP Engineering), Industries (IT, Financial Services, Computer Software),
  Company size (50–10,000+), Location: country from event data

#### X / Twitter Promoted Posts
- 3 tweet variants ≤ 280 chars
- Include hashtags: `#MCPDevSummit` (or event-appropriate), `#AIAgents`, `#OpenSource`
- Targeting: followers of @linuxfoundation, interest keywords matching event themes

### Step 6: Generate keyword list (Google Search tab)

Generate 25–40 high-intent keywords. Prioritise commercial intent over informational.

| Category | Match Type | Intent |
|----------|-----------|--------|
| Brand exact: `"{Event Name}"`, `"{Event Name} {City}"`, `"{Event Name} {Year}"` | Exact | 🔴 High |
| Protocol/topic phrase: `"model context protocol conference"` | Phrase | 🔴 High |
| Role-based: `"AI developer conference {country}"` | Phrase | 🟡 Med |
| Adjacent/competitor events | BMM | 🟡 Med |
| Informational (what is..., tutorial) | Phrase | 🟢 Low — flag with ⚠️ |

For each keyword, provide: Keyword · Match Type · Intent Level · Notes/Recommendation.

Flag informational-intent keywords for exclusion or bid modifier review.

Add a disclaimer note: new/emerging event brands may have near-zero search volume on
brand-exact terms initially — keep them for intent capture and monitor after 2 weeks.

### Step 7: Add Stakeholder Inputs block (Overview tab)

Required inputs that Claude cannot determine — must be collected before launch:

| Input Required | Who Provides | Notes |
|----------------|-------------|-------|
| Budget (total or per-platform) | Campaign stakeholder | ⚠️ REQUIRED before launch |
| Campaign start date | Stakeholder | Recommended: 4–6 weeks before event |
| Campaign end date | Stakeholder | Usually registration close date |
| Event logo / brand images | Design / event team | Needed for Display, Meta, LinkedIn |
| Event venue/speaker images | Design / event team | Google Display prefers multiple sizes |
| Square (1:1) image | Design / event team | ⚠️ Required for Display — auto-crop often fails |
| Retargeting audience lists | Ads manager | ⚠️ CREATE NOW — takes 2–3 days to populate |
| Google Ads customer ID | Ads manager | Needed for campaign creation |
| Meta Ad account ID | Ads manager | Needed for Meta campaign setup |
| LinkedIn Campaign Manager account | Ads manager | Needed for LinkedIn campaigns |

### Step 8: Assemble Excel workbook

Write a Python script using `openpyxl` to build the workbook. Key formatting rules:

- **Fonts**: Arial throughout; section headers bold white on navy (`1F3864`) or blue (`2F5496`)
- **Char count columns**: Use `=LEN(cell)` formula — never hardcode counts
- **Overflow highlighting**: Conditional formatting → red fill when char count > limit
- **Alternating row shading**: `EEF2FF` for even data rows
- **⚠️ Warning rows**: Amber text (`C55A11`), yellow background (`FFF2CC`)
- **Column widths**: Set explicitly — keyword notes column ≥ 55 chars wide
- **Merged cells**: Section headers span full table width

Save as `{event_slug}-campaign-brief.xlsx`.

Run `scripts/recalc.py` if available to force-evaluate LEN formulas.

### Step 9: Update state file and present summary

**Update `{event_slug}-campaign-state.json`** with all resolved values:

```json
{
  "event_slug": "...",
  "event_name": "...",
  "dates": "...",
  "registration_url": "...",
  "hs_campaign_id": "...",
  "hs_utm": "42462239-MCP%20Dev%20Summit%20Mumbai",
  "utm_sheet_rows": "1040-1047",
  "brief_file": "mcp-dev-summit-mumbai-campaign-brief.xlsx",
  "campaigns": {},
  "last_updated": "YYYY-MM-DD"
}
```

Then present the summary in chat:

```
✅ Campaign brief saved: {event_slug}-campaign-brief.xlsx
✅ State saved: {event_slug}-campaign-state.json

Platforms covered: Google Search · Google Display · Meta · LinkedIn · X/Twitter
Keywords: {N} keywords across Exact/Phrase/BMM match types
UTM rows: registered in UTM Link Builder (rows {start}–{end})
HubSpot campaign token: {hs_utm}

⚠️ Stakeholder inputs needed before launch:
  - Budget (cannot proceed without this)
  - Square (1:1) image from Design team
  - Retargeting audiences (create now if using retargeting)

Ready to proceed to campaign-implementation? Reply "yes" to create platform drafts.
(Next session: load state from {event_slug}-campaign-state.json to skip re-computation.)
```

**Do not proceed to implementation without explicit user approval.**

---

## Meta Audience Strategy Reference

Include this note in the Meta tab:

| Mode | When to Use | Setup |
|------|-------------|-------|
| **Prospecting** (default) | New event, no existing audience | AI-inferred: interests (AI/ML, APIs, developer tools), behaviours (tech early adopters), location (India metros or event country). Ready immediately. |
| **Retargeting** | If audience list exists | Website visitors, past event purchasers, email upload. ⚠️ Create segments 2–3 days before campaign launch — audiences take time to populate. |
