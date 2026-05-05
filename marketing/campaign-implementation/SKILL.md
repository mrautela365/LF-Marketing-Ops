---
name: campaign-implementation
description: >
  Creates platform-ready campaign files (bulk upload CSVs/JSON) and/or live paused
  drafts for Google Ads (Search + Display), Meta Ads, and LinkedIn. Two modes:
  (1) Bulk Upload — generates import-ready files the marketer loads manually, no
  browser auth needed, 100% reliable; (2) Browser — creates live drafts via browser
  automation, faster but requires Chrome logged in to each platform.

  Trigger after the user approves the campaign brief and says: "implement the campaigns",
  "create the campaigns", "set up the ads", "generate the upload files", or
  "proceed to implementation".

  Prerequisites: approved campaign brief Excel file + campaign state file.
---

# Campaign Implementation

Two execution paths — choose based on what's available:

| Mode | When to use | Reliability |
|------|------------|-------------|
| **Bulk Upload** (default) | Always works; no browser auth needed | ✅ 100% — pure file generation |
| **Browser Automation** | Faster; creates live drafts directly | ⚠️ Requires Chrome logged in to each platform |

**Recommendation:** Use Bulk Upload for first-time setup or when browser auth is
uncertain. Use Browser Automation when all platforms are already logged in and
you want live drafts immediately.

## ⚠️ Safety Rules (both modes)

1. **Paused by default**: All campaigns created in paused/draft state. No spend.
2. **Budget placeholders**: Use `[TO BE FILLED]` in bulk files, `$1.00/day` in browser.
3. **Second approval gate**: Before any campaign goes live, stop and ask for explicit
   user confirmation. This skill only creates drafts.
4. **Never activate**: Do not publish or enable any campaign in this skill.

## Configuration

| Setting | Value |
|---------|-------|
| Google Ads account | LF Core |
| Campaign naming pattern | `Events \| {Event Name} {Year} \| {Region} \| Conversions \| Prospecting \| {Platform} \| {Brand} \| BoFU` |
| Default daily budget | `$1.00` (browser) / `[TO BE FILLED]` (bulk upload files) |
| Bid strategy | Maximize conversions (no CPA target for new events) |

---

## Step 0: Load state file

Read `{event_slug}-campaign-state.json`. Extract:
- `event_name`, `dates`, `year`, `city`, `region_code`
- `registration_url`, `hs_utm`
- `campaigns` — skip any platform whose status is already `paused` or `live`

If state file is missing, ask the user to run `lf-event-scraper` and
`campaign-brief-generator` first, or provide the brief file path manually.

Also read the campaign brief Excel to get copy (headlines, descriptions, sitelinks,
keywords) — use pandas: `pd.read_excel("{event_slug}-campaign-brief.xlsx", sheet_name=None)`.

---

## MODE A: Bulk Upload Files (default, no API required)

Generates one import-ready file per platform. The marketer imports these into each
ad platform's bulk upload interface — no browser automation, no auth issues.

### A1. Google Ads Search — Editor CSV

Generate `{event_slug}-google-search.csv` following Google Ads Editor bulk upload schema.

**Required columns and row types:**

```
Row Type    | Campaign          | Ad Group          | Keyword  | Headline 1..15 | Description 1..10 | ...
------------|-------------------|-------------------|----------|----------------|-------------------|----
Campaign    | Events | MCP...  |                   |          |                |                   |
Ad Group    | Events | MCP...  | MCP - High Intent |          |                |                   |
Keyword     | Events | MCP...  | MCP - High Intent | [kw text]|                |                   | Match Type
RSA         | Events | MCP...  | MCP - High Intent |          | [h1]..[h15]    | [d1]..[d10]       |
Sitelink    | Events | MCP...  |                   |          |                |                   | Headline, Desc1, Desc2, URL
```

**Header row (exact column names Google Ads Editor expects):**

`Row Type, Campaign, Ad Group, Keyword, Match Type, Final URL, Headline 1, Headline 2, ..., Headline 15, Description 1, ..., Description 10, Sitelink Text, Sitelink Description Line 1, Sitelink Description Line 2, Sitelink Final URL, Campaign Status, Ad Group Status, Campaign Daily Budget, Campaign Bid Strategy Type`

Fill from brief:
- Keywords: all rows from brief's `Google Search` tab where Intent ≠ 🟢 Low
- Headlines/descriptions: from RSA section of `Google Search` tab
- Final URL: `registration_url` + UTM params (utm_source=google, utm_medium=paid-search, utm_campaign={hs_utm})
- Campaign Status: `Paused`
- Campaign Daily Budget: `[TO BE FILLED]`
- Campaign Bid Strategy Type: `Maximize Conversions`

### A2. Google Ads Display — Editor CSV

Generate `{event_slug}-google-display.csv` with the Responsive Display Ad row:

`Row Type, Campaign, Ad Group, Short Headline, Long Headline, Description, Business Name, Final URL, Campaign Status, Campaign Daily Budget`

Fill from brief's `Google Display` tab. Campaign Status: `Paused`.

Add a comment row at the top:
```
# ⚠️ Images must be uploaded manually in Google Ads UI after import.
# Required: 1 landscape (1.91:1, min 1200×628) + 1 square (1:1, min 1200×1200).
# Design team to provide square image — auto-crop from event page often fails.
```

### A3. Meta Ads — Bulk Upload CSV

Generate `{event_slug}-meta-bulk.csv` following Meta Ads Manager bulk upload format:

`Campaign Name, Campaign Objective, Ad Set Name, Age Min, Age Max, Location, Interests, Budget, Ad Name, Primary Text, Headline, Description, CTA, Destination URL, Image Hash`

Fill from brief's `Meta` tab (Variant 1 as default). Leave `Image Hash` as `[UPLOAD IMAGE FIRST]`.

| Field | Value |
|-------|-------|
| Campaign Objective | `LEAD_GENERATION` |
| Age Min / Max | `25` / `55` |
| Location | Event country |
| Interests | `Artificial intelligence; Machine learning; Software development` |
| CTA | `SIGN_UP` |
| Budget | `[TO BE FILLED]` |

Add note row: `# Run Meta image upload first, then paste image hashes into this column.`

### A4. LinkedIn Campaigns — CSV

Generate `{event_slug}-linkedin-campaigns.csv`:

`Campaign Group, Campaign Name, Objective, Ad Format, Budget, Bid Type, Location, Job Titles, Industries, Ad Name, Intro Text, Headline, Destination URL, CTA, Status`

Fill from brief's `LinkedIn` tab. Status: `DRAFT`. Budget: `[TO BE FILLED]`.

### A5. Save files and update state

Write all files to working directory. Update `{event_slug}-campaign-state.json`:

```json
{
  "campaigns": {
    "google_search":  { "bulk_file": "{slug}-google-search.csv",  "status": "bulk_ready" },
    "google_display": { "bulk_file": "{slug}-google-display.csv", "status": "bulk_ready", "blocker": "needs square image" },
    "meta":           { "bulk_file": "{slug}-meta-bulk.csv",      "status": "bulk_ready" },
    "linkedin":       { "bulk_file": "{slug}-linkedin-campaigns.csv", "status": "bulk_ready" }
  },
  "last_updated": "YYYY-MM-DD"
}
```

### A6. Present import instructions

```
✅ Bulk upload files generated:

  {slug}-google-search.csv   → Google Ads Editor → File → Import CSV
  {slug}-google-display.csv  → Google Ads Editor → File → Import CSV
  {slug}-meta-bulk.csv       → Meta Ads Manager → ⬆ Import → Spreadsheet
  {slug}-linkedin-campaigns.csv → LinkedIn Campaign Manager → Bulk Operations → Upload

⚠️ Before importing:
  1. Fill [TO BE FILLED] budget fields in each file
  2. Upload square (1:1) image to Google Display campaign after import
  3. Upload ad images to Meta before importing (get image hashes first)

All campaigns import in Paused/Draft state — no spend until you activate.
State saved to: {event_slug}-campaign-state.json
```

---

## MODE B: Browser Automation (live drafts)

Use when Chrome is already logged into all ad platforms. Faster but fragile — if
any platform shows an auth prompt or unexpected UI change, fall back to Mode A.

### Prerequisites check

Before starting, take a screenshot and confirm:
1. Chrome tab is open and logged into Google Ads (ads.google.com)
2. Correct account is active (LF Core)

If not logged in: switch to Mode A.

### B1. Google Ads Search Campaign

#### Navigate
Go to `https://ads.google.com/aw/campaigns` → **+** → **New campaign** →
**Website traffic** → **Search**

#### Campaign settings

| Field | Value |
|-------|-------|
| Campaign name | From naming pattern above |
| Networks | Google Search only (uncheck Display Network + Search Partners) |
| Locations | Event country (e.g. India) |
| Languages | English |
| Budget | `$1.00`/day (placeholder) |
| Bid strategy | Maximize clicks or Maximize conversions |

#### Ad group + keywords
Name: `{Event Name} - High Intent`. Add all 🔴 High intent keywords from brief.

#### RSA ad
Fill 15 headlines + 10 descriptions from brief. Final URL = registration URL + UTM.

#### Sitelinks
Add all 6 sitelinks from brief (headline + 2 description lines + URL each).

#### Publish then immediately pause
1. Click **Publish campaign**
2. Wait for confirmation screen
3. Go to Campaigns list → find by name → click Enabled dot → **Paused**
4. Confirm status is grey/paused

Record `campaignId` from URL. Update state file.

#### Known issues + fixes

| Issue | Fix |
|-------|-----|
| "Bidding: Enter an amount" on review | Uncheck "Set a target cost per action" |
| Image crop toast error on Display | Dismiss; save as draft; flag for Design team |
| Accidentally duplicated an ad | Click trash icon on duplicate → "Yes remove" |
| Search bar opens instead of URL bar | Press Escape; use navigate tool instead |

### B2. Google Ads Display Campaign

Follow same navigation pattern but select **Display** type.
- Bid strategy: Maximize conversions, **uncheck "Set a target CPA"**
- Add images from event URL (landscape usually works; square often fails — see Known Issues)
- If square image missing: save as draft, record campaignId + draftId

### B3. Meta Ads Manager

Go to `https://adsmanager.facebook.com/adsmanager/manage/campaigns`

1. **+Create** → Objective: **Leads** → name from pattern
2. Ad set: location = event country, age 25–55, interests (AI/ML, APIs, developer tools)
3. Ad: single image, primary text + headline Variant 1 from brief, CTA = **Register Now**
4. **Save as draft** — do not publish

### B4. LinkedIn Campaign Manager

Go to `https://www.linkedin.com/campaignmanager/`

1. Create campaign group: `Events | {Event Name} {Year}`
2. Inside group → create campaign → objective: **Website visits**
3. Targeting: job titles (Software/AI/ML Engineer, Solutions Architect, CTO, VP Engineering),
   industries (IT, Financial Services), company size 50–10,000+, location = event country
4. Ad: single image, intro text + headline Variant 1 from brief, CTA = **Register**
5. **Save as draft**

### B5. Update state file

```json
{
  "campaigns": {
    "google_search":  { "id": "XXXXXXXXXX", "status": "paused" },
    "google_display": { "id": "XXXXXXXXXX", "draft_id": "XXXXXXXXXX", "status": "draft", "blocker": "needs square image" },
    "meta":           { "status": "draft" },
    "linkedin":       { "status": "draft" }
  }
}
```

---

## Handoff Summary (both modes)

```
## Campaign Implementation Complete — {Event Name}

Mode used: [Bulk Upload / Browser Automation]

Platform         Status         Notes
Google Search    paused/ready   {campaign_id or bulk file}
Google Display   draft/ready    ⚠️ Needs square (1:1) image from Design team
Meta             draft/ready    ⚠️ Upload ad image before activating
LinkedIn         draft/ready

State file: {event_slug}-campaign-state.json

─── BEFORE GOING LIVE — stakeholder checklist ───────────────────────────
  □ Set real budget (replace placeholders)
  □ Set campaign start/end dates
  □ Upload square (1:1) image → Google Display
  □ Upload ad image → Meta
  □ Confirm conversion tracking is firing
  □ Review all copy for brand accuracy
  □ Say "activate campaigns" for final approval step
─────────────────────────────────────────────────────────────────────────
```
