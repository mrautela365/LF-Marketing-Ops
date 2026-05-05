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

**How entity type works — no "Row Type" column.**
Google Ads Editor infers the entity from which columns are populated in each row.
Leave all irrelevant columns blank for each row type.

| Entity | Columns that must be populated | Columns that must be blank |
|--------|-------------------------------|---------------------------|
| Campaign row | `Campaign`, `Campaign Type`, `Campaign Status`, `Campaign daily budget` | Ad group, Keyword, headlines |
| Ad Group row | `Campaign`, `Ad group`, `Max CPC` | Keyword, headlines |
| Keyword row | `Campaign`, `Ad group`, `Keyword`, `Criterion Type` | Headlines, descriptions |
| RSA Ad row | `Campaign`, `Ad group`, `Final URL`, `Headline 1`–`3` min, `Description 1`–`2` min | Keyword |
| Sitelink row | `Campaign`, `Sitelink text`, `Final URL` | Ad group, Keyword, headlines |

**Exact column headers (case-insensitive, spelling must be exact):**

```
Campaign, Campaign Type, Campaign Status, Campaign daily budget, Campaign Bid Strategy Type,
Ad group, Max CPC, Ad group status,
Keyword, Criterion Type,
Final URL, Path 1, Path 2,
Headline 1, Headline 2, Headline 3, Headline 4, Headline 5, Headline 6, Headline 7,
Headline 8, Headline 9, Headline 10, Headline 11, Headline 12, Headline 13, Headline 14, Headline 15,
Description 1, Description 2, Description 3, Description 4,
Sitelink text, Description line 1, Description line 2, Sitelink Final URL, Sitelink status
```

> Note: Descriptions only go to **4** (not 10) in Google Ads Editor. RSA requires minimum
> 3 headlines and 2 descriptions; Google optimises which to show.
> `Criterion Type` values: `Exact`, `Phrase`, `Broad` (not "Match Type").

**Row structure example:**

```csv
Campaign,Campaign Type,Campaign Status,Campaign daily budget,...
Events | MCP Dev Summit Mumbai 2026 | IN | Conversions | Prospecting | Search | AAIF | BoFU,Search,Paused,[TO BE FILLED],...
Events | MCP...,,,,,MCP - High Intent,1.00,,,,,,,,,,,,,,,,,,,,,,,,,,
Events | MCP...,,,,,MCP - High Intent,,,"MCP Dev Summit",Exact,,,,,,,,,,,,,,,
Events | MCP...,,,,,MCP - High Intent,,,,,https://events.../register/?utm_...,,register,now,Headline 1 text,...
Events | MCP...,,,,,,,,,,https://events.../register/?...,,,,,,,Register Now,Desc line 1,Desc line 2,,
```

Fill from brief:
- Keywords: all rows from `Google Search` tab where Intent ≠ 🟢 Low
- Headlines 1–15 + Descriptions 1–4: from RSA section of `Google Search` tab
- Final URL: `registration_url` + UTM (utm_source=google, utm_medium=paid-search, utm_campaign={hs_utm})
- `Criterion Type`: map from brief's Match Type column (Exact → `Exact`, Phrase → `Phrase`, BMM → `Broad`)
- Campaign Status: `Paused`
- Campaign daily budget: `[TO BE FILLED]`
- Campaign Bid Strategy Type: `Maximize Conversions`

### A2. Google Ads Display — Editor CSV

Generate `{event_slug}-google-display.csv`. Same column inference logic as Search —
no Row Type column; entity type inferred from populated columns.

**Display-specific columns needed:**

```
Campaign, Campaign Type, Campaign Status, Campaign daily budget, Campaign Bid Strategy Type,
Ad group, Max CPC,
Short headline, Long headline 1, Description 1, Business name, Final URL, Ad status
```

Fill from brief's `Google Display` tab. `Campaign Type`: `Display`. `Campaign Status`: `Paused`.

> ⚠️ **Images cannot be imported via CSV** — Google Ads Editor does not support image
> asset import. After importing this file, open the campaign in the Google Ads UI and
> add images manually to the Responsive Display Ad:
> - At least 1 landscape image (1.91:1, min 1200×628 px)
> - At least 1 square image (1:1, min 1200×1200 px) — Design team must provide this;
>   auto-crop from event page often fails
> - Logo recommended (1:1 format)
> Flag this in the handoff summary as a required post-import action.

### A3. Meta Ads — Bulk Upload Spreadsheet

> ⚠️ **Meta's template must be downloaded from inside Ads Manager.**
> There is no public URL and the column names differ from the Ads Manager UI.
> Go to: Ads Manager → any campaign view → Import/Export icon → "Import Ads in Bulk"
> → "Download a sample spreadsheet". Use that file as the base.

**Critical: UI names vs spreadsheet column names**

| What you see in Ads Manager UI | Actual column name in the spreadsheet |
|-------------------------------|---------------------------------------|
| Primary Text | `Body` |
| Headline | `Title` |
| Campaign ID | Leave blank (new campaign) |
| Ad Set ID | Leave blank (new ad set) |
| Ad ID | Leave blank (new ad) |

**Key required fields and correct values:**

| Column | Value |
|--------|-------|
| `Campaign Name` | From naming pattern |
| `Campaign Objective` | `OUTCOME_LEADS` (API enum — NOT "Lead Generation") |
| `Daily Budget` | `[TO BE FILLED]` |
| `Start Date` | Required — use campaign start date or leave for stakeholder |
| `Ad Set Name` | `{Event Name} - Prospecting - India` |
| `Age Min` / `Age Max` | `25` / `55` |
| `Body` | Primary text Variant 1 from brief's Meta tab |
| `Title` | Headline Variant 1 from brief's Meta tab |
| `Call to Action` | `SIGN_UP` |
| `Link` | Registration URL + UTM (utm_source=facebook, utm_medium=paid-social) |
| Image hash | `[UPLOAD IMAGE FIRST — get hash from Meta media library]` |

**Other common objective API enum values for reference:**
`OUTCOME_TRAFFIC`, `OUTCOME_AWARENESS`, `OUTCOME_ENGAGEMENT`, `OUTCOME_SALES`

Add a top-row note in the file:
```
INSTRUCTIONS: 1) Upload your ad image to Meta's media library first to get the image hash.
2) Fill [TO BE FILLED] fields. 3) Start Date is required (format: YYYY-MM-DD).
4) Import via Ads Manager → Import/Export → Import Ads in Bulk.
```

### A4. LinkedIn — Campaign + Campaign Group CSV

> ⚠️ **LinkedIn bulk CSV cannot create ads (creatives).** It only supports creating
> campaign groups and campaigns. Ad creative must still be added in the Campaign Manager
> UI after importing the CSV. The template must be downloaded from Campaign Manager:
> Campaigns tab → Bulk Actions → Download Template.

**What LinkedIn bulk CSV covers:**
- ✅ Campaign group creation
- ✅ Campaign settings (name, budget, dates, status, targeting)
- ❌ Ad creation — must be done in UI after import

Generate two files:

**File 1: `{event_slug}-linkedin-campaign-groups.csv`**

Download the Campaign Group template from Campaign Manager and fill:

| Column | Value |
|--------|-------|
| Account ID | *(read-only, pre-filled in template)* |
| Campaign Group Name | `Events \| {Event Name} {Year}` |
| Campaign Group Status | `paused` |
| Start Date | MM/DD/YYYY — use campaign start date |
| End Date | *(leave blank)* |

**File 2: `{event_slug}-linkedin-campaigns.csv`**

Download the Campaign template and fill:

| Column | Value |
|--------|-------|
| Account ID | *(read-only)* |
| Campaign Name | From naming pattern |
| Campaign Status | `paused` |
| Campaign Start Date | MM/DD/YYYY |
| Campaign Objective | `WEBSITE_VISITS` |
| Daily Budget | `[TO BE FILLED]` |

> After importing both files, add ad creatives manually in Campaign Manager:
> open the new campaign → Ads tab → + Create ad → fill from brief's LinkedIn tab.

Add a top-row note: `INSTRUCTIONS: 1) Download template from Campaign Manager → Bulk Actions → Download Template. 2) Copy these values into that template (do not use this file directly). 3) Import via Bulk Actions → Upload. 4) After import, add ad creatives in the UI.`

### A5. Save files and update state

Write all files to working directory. Update `{event_slug}-campaign-state.json`:

```json
{
  "campaigns": {
    "google_search":  { "bulk_file": "{slug}-google-search.csv",  "status": "bulk_ready" },
    "google_display": { "bulk_file": "{slug}-google-display.csv", "status": "bulk_ready", "blocker": "needs square image" },
    "meta":           { "bulk_file": "{slug}-meta-bulk.csv",      "status": "bulk_ready" },
    "linkedin":       { "bulk_file": "{slug}-linkedin-campaigns.csv", "status": "bulk_ready", "note": "ads must be created in UI after CSV import" }
  },
  "last_updated": "YYYY-MM-DD"
}
```

### A6. Present import instructions

```
✅ Bulk upload files generated:

  Google Ads (Search + Display):
    {slug}-google-search.csv   → Google Ads Editor → File → Import CSV
    {slug}-google-display.csv  → Google Ads Editor → File → Import CSV

  Meta Ads:
    {slug}-meta-bulk.csv       → use as a reference/fill-in guide ONLY
    ⚠️ Must use Meta's own template: Ads Manager → Import/Export → Import Ads in Bulk
       → Download a sample spreadsheet → copy values from reference file into template

  LinkedIn:
    {slug}-linkedin-campaign-groups.csv  → reference for Campaign Group values
    {slug}-linkedin-campaigns.csv        → reference for Campaign values
    ⚠️ Must use LinkedIn's own template: Campaign Manager → Bulk Actions → Download Template
       → copy values into that template, then upload

──── POST-IMPORT REQUIRED ACTIONS ────────────────────────────────────────────
  Google Display:
    □ Open campaign in Google Ads UI → add images manually
    □ Need: 1 landscape (1.91:1, ≥1200×628) + 1 square (1:1, ≥1200×1200) — Design team
  Meta:
    □ Upload ad image to Meta media library first → get image hash
    □ Paste image hash into spreadsheet before importing
    □ Start Date field is required — fill before import
  LinkedIn:
    □ After CSV import creates campaign, open it in Campaign Manager
    □ Add ad creative manually (Ads tab → + Create ad) using copy from brief
──────────────────────────────────────────────────────────────────────────────

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
Google Display   draft/ready    ⚠️ Add images in UI after import (landscape + square)
Meta             bulk_ready     ⚠️ Use Meta's own template; upload image hash first
LinkedIn         bulk_ready     ⚠️ Campaigns only via CSV; add ad creative in UI

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
