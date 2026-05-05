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

| Requirement | Details |
|-------------|---------|
| Event data | JSON output from `lf-event-scraper`, or manually provided fields |
| HubSpot MCP | `search_crm_objects` + `manage_crm_objects` tools must be connected |
| Google Ads MCP | `build_utm_url` tool must be connected |
| Python + openpyxl | For assembling the Excel file |

## Configuration

| Setting | Value |
|---------|-------|
| UTM Link Builder Sheet ID | `1AVFVYTo92kncOdtwyblS_M96m_gq6k2dG1rpueEMy6Q` |
| Output file pattern | `{event_slug}-campaign-brief.xlsx` |
| Output directory | `/Users/misharautela/` (or current working directory) |

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

### Step 1: Validate event data

Confirm the following fields are present. If any are missing, ask the user:

- `event_name`, `event_slug`, `dates`, `year`, `city`, `country`, `region_code`
- `audience_description`, `themes`
- `registration_url` (required for ad final URLs)

### Step 2: HubSpot — look up or create campaign token

#### 2a. Search for existing campaign

Call `search_crm_objects`:
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
  "properties": ["hs_name", "hs_utm"]
}
```

#### 2b. Extract hs_utm token

If found: extract `hs_utm` from the result (format: `{numericId}-{URL-encoded-name}`,
e.g. `42462239-MCP%20Dev%20Summit%20Mumbai`).

If not found: call `manage_crm_objects` to create the campaign, then extract `hs_utm`
from the created object.

### Step 3: Build UTM URLs for all platforms

For each row below, call `build_utm_url` to construct and validate the final tracking URL.

Base registration URL: `{registration_url}`

| Platform | utm_source | utm_medium | utm_content |
|----------|-----------|------------|-------------|
| Google Search | `google` | `paid-search` | `events-{slug}-{region}-conv` |
| Google Display | `google` | `display` | `events-{slug}-{region}-conv` |
| Meta | `facebook` | `paid-social` | `events-{slug}-{region}-conv` |
| LinkedIn | `linkedin` | `paid-social` | `events-{slug}-{region}-conv` |
| X / Twitter | `twitter` | `paid-social` | `events-{slug}-{region}-conv` |

`utm_campaign` = `{hs_utm}` for all platforms.

> Note: LF event pages return 403 to bots — `url_resolves: false` is expected and
> acceptable. The URL structure is still valid.

### Step 4: Register UTM rows in Google Sheet

Write one row per platform into the UTM Link Builder Google Sheet
(ID: `1AVFVYTo92kncOdtwyblS_M96m_gq6k2dG1rpueEMy6Q`).

Columns A–G: Campaign Name, Source, Medium, Campaign (hs_utm), Term, Content, Landing Page.
Column H: formula (auto-calculates full URL).

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

### Step 9: Present summary and wait for approval

After saving the file, summarise in chat:

```
✅ Campaign brief saved: {event_slug}-campaign-brief.xlsx

Platforms covered: Google Search · Google Display · Meta · LinkedIn · X/Twitter
Keywords: {N} keywords across Exact/Phrase/BMM match types
UTM rows: registered in UTM Link Builder (rows {start}–{end})
HubSpot campaign token: {hs_utm}

⚠️ Stakeholder inputs needed before launch:
  - Budget (cannot proceed without this)
  - Square (1:1) image from Design team
  - Retargeting audiences (create now if using retargeting)

Ready to proceed to campaign-implementation? Reply "yes" to create platform drafts.
```

**Do not proceed to implementation without explicit user approval.**

---

## Meta Audience Strategy Reference

Include this note in the Meta tab:

| Mode | When to Use | Setup |
|------|-------------|-------|
| **Prospecting** (default) | New event, no existing audience | AI-inferred: interests (AI/ML, APIs, developer tools), behaviours (tech early adopters), location (India metros or event country). Ready immediately. |
| **Retargeting** | If audience list exists | Website visitors, past event purchasers, email upload. ⚠️ Create segments 2–3 days before campaign launch — audiences take time to populate. |
