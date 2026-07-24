# QA Guide — LF Email Automation (Campaign Builder + Audience Builder)

This guide walks a teammate through installing the app locally, understanding what
it does, and running through a set of test cases — with special focus on the
**Audience Builder** tab (existing-list discovery, master-list composition, and the
new direct "Create list" shortcut for missing signals).

---

## 1. What this app does

A FastAPI backend + vanilla-JS frontend that:
- Drafts and stages Linux Foundation marketing emails in HubSpot (**Campaign Builder** tab).
- Builds the HubSpot audience/segment lists that back those emails, either from
  scratch (LLM-authored filters) or by discovering and reusing lists that already
  exist (**Audience Builder** tab).

Nothing is emailed to real contacts during this flow — the app creates **draft**
emails and HubSpot **lists**. The risk during QA is accidentally creating a lot of
clutter in the shared HubSpot portal, not sending anything. See the `ASSET_TAG`
note in Section 3 — use it.

---

## 2. Prerequisites

- Python 3.12
- Git access to this repo, on branch `prasad/skills` (or whichever branch you're QA'ing)
- A `.env` file in the repo root with at least:
  - `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID` — HubSpot private-app token (Marketing Email + CRM Lists scopes)
  - One AI backend: `ANTHROPIC_API_KEY` (simplest), or `LITELLM_BASE_URL`+`LITELLM_API_KEY`
  - `SNOWFLAKE_*` vars — required for audience list building (both tabs query Snowflake for contact counts/filters)
  - `ASSET_TAG` — **set this for QA**, e.g. `ASSET_TAG=qa-<yourname>`. Every HubSpot
    list or cloned email this app creates gets `" [qa-<yourname>]"` appended to its
    name, so your test data is easy to find and bulk-delete afterward, and easy to
    tell apart from a teammate's test run.
- Ask whoever owns the repo for a working `.env` (or copy `.env.example` and fill in
  values) — do not commit `.env`, it's git-ignored on purpose.

---

## 3. Install & run locally

```bash
git clone <repo-url>
cd emailcreationskill
git checkout prasad/skills   # or the branch you're testing
pip install -r requirements.txt
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000/** in a browser.

**Sanity check before testing anything else:**
- `GET http://localhost:8000/api/status` should return 200 with the active AI mode
  and `hubspot_configured: true`. If `hubspot_configured` is false, list-building
  tests will fail — check your `.env`.
- The page should load with a **Campaign Builder** / **Audience Builder** tab bar at
  the top and no errors in the browser console (F12 → Console).

(Docker alternative: `docker compose up --build`, same URL.)

---

## 4. How to use the app

### 4a. Campaign Builder tab (default view)

A 4-step linear wizard:

1. **Planning** — paste an event/campaign URL → "Generate Campaign Brief". The
   agent scrapes the page, identifies the brand, and drafts a plan.
2. **Email Preview** — review the generated subject/preview text/content sections,
   optionally "Refine Content" with free-text change requests, then continue.
3. **Audience Preview** — choose how to set the send list:
   - **Event Audience** — auto-builds a segment from the event's own HubSpot
     registration/engagement data ("Generate Audience Plan" → review → "Approve & Build Audience").
   - **Custom Audience** — describe the audience in free text, same plan → review → approve flow.
   - **Use an existing list** — search and attach a list that already exists, no building.
   - **Skip** — create the email with no send list attached.
4. **Implementation** — clones the email as a HubSpot **draft** and attaches the
   chosen list. Nothing is sent — verify the draft in HubSpot manually if needed.

### 4b. Audience Builder tab

Standalone tool for finding/reusing lists an event already has in HubSpot, and
rolling them into one new master list. Three sections, top to bottom:

1. **Discover Existing Lists** — paste an event URL → "Discover Existing Lists".
   Read-only: the agent searches HubSpot and classifies what it finds into 5
   signals (Project Opt-In, LF Newsletter Opt-In, Event Registration, Education
   Enrollment, Page View). Nothing is created here.
2. **Review & Build Master List** — discovered lists render as cards grouped by
   signal. Select the ones you want (whole card is clickable, or "Select All" /
   "Clear"), optionally search-and-add another list manually, then "Build Master
   List" combines your selection into one new HubSpot list (OR of the selected
   lists, size shown once built).
3. **Qualifying Lists Not Found** (only shown if a signal had zero matches) — one
   card per missing signal with a **"Create list"** button. Clicking it skips the
   plan-review step entirely and directly builds that signal's list via a custom
   event / contact property / subscription filter — no "Generate Audience Plan" →
   "Approve" round-trip. On success it's added straight into the card grid above,
   pre-selected.
4. **Build From Scratch** (optional) — same free-text → plan → review → approve
   flow as the wizard's Custom Audience sub-tab, for anything not covered by
   discovery or the missing-signal shortcut.

---

## 5. Test cases

Use a real LF event URL you know has HubSpot history for the discovery/event-audience
cases (ask the team for a known-good one), and a **fresh, obviously-fake** description
for custom-audience cases so it's easy to eyeball whether the segment logic makes sense.

| # | Area | Steps | Expected result |
|---|---|---|---|
| 1 | Smoke test | Load `http://localhost:8000/`. | Page loads, Campaign Builder tab active by default, no console errors. |
| 2 | Campaign Builder — happy path | Paste a known event URL in Step 1 → Generate Campaign Brief → wait for Step 2 content → Generate Audience Plan (Step 3, Event Audience) → Approve & Build → Create Campaign Draft. | Each step completes without error; Step 4 shows a link to a HubSpot **draft** email with the master audience attached. Verify in HubSpot: draft exists, named with the `[ASSET_TAG]` suffix, status is Draft (not scheduled/sent). |
| 3 | Campaign Builder — refine content | In Step 2, enter a change request (e.g. "make the subject shorter") → Refine Content. | Subject/content updates in place without restarting the whole plan. |
| 4 | Campaign Builder — existing list | In Step 3, use "Or use an existing list" to search and pick a list instead of building one. | Step 4 attaches the picked list as send list; no new list is created. |
| 5 | Campaign Builder — skip audience | In Step 3, click "Skip — Create Email Only". | Step 4 completes with no send list attached; no list created. |
| 6 | Audience Builder — discovery | Switch to Audience Builder tab. Paste a known event URL → Discover Existing Lists. | Ticker shows live agent narration; cards appear grouped by signal with reasonable classifications (spot-check: a "LF Newsletter Opt-In" card's filter, if you open it in HubSpot, is actually the LF newsletter subscription type, not a project-specific one). |
| 7 | Audience Builder — select & build master | From case 6's results, Select All (or pick a subset) → Build Master List. | Button disabled until ≥1 card selected; on build, success message shows a HubSpot link; list's filter branch in HubSpot is an OR of `IN_LIST` branches referencing exactly the selected list IDs; name follows `<YYQN> - <Brand> - <Event> - Master [ASSET_TAG]`. |
| 8 | Audience Builder — duplicate name | Re-run case 7 for the *same* event a second time (same selection). | New master list is still created (not blocked) — its name gets a date/time or version suffix so it doesn't collide with the first run's list. |
| 9 | Audience Builder — search & add | In section 2, type a list name/keyword in "Add another list" (≥2 chars). | Dropdown shows matching HubSpot lists (not filtered to `MANUAL`/`SNAPSHOT` only); picking one adds it as a card, selected, without a page reload. |
| 10 | Audience Builder — missing signal direct-build | Pick an event where discovery finds fewer than 5 signals (or a low-history/test event so most signals are missing). Under "Qualifying Lists Not Found", click "Create list" on one signal card. | Button immediately shows "Building…" and is disabled. **No** plan-review step appears — it goes straight to building. On success: the card disappears from the missing-signals section and a new, pre-selected card for that signal appears in the results grid above; the built list's filter in HubSpot matches the signal (e.g. Education Enrollment uses the `UNIFIED_EVENTS` custom event, scoped to that event's own brand's courses, not all LFX Education courses). |
| 11 | Audience Builder — missing signal build failure recovery | Same as #10, but on a signal likely to fail (e.g. disconnect network briefly after clicking, or use an event URL with no resolvable brand). | Button resets from "Building…" back to "Create list" (not stuck) and an error message explains the failure. |
| 12 | Audience Builder — Build From Scratch | In section 4, describe a fake audience (e.g. "All mailable contacts in Seoul for OSS Korea and MCP Dev Summit Seoul") → Generate Audience Plan. | Plan appears in the ticker/log for review; "Approve & Build Audience" is required before anything is created in HubSpot — confirm nothing exists in HubSpot until you click Approve. |
| 13 | Audience Builder — event/education custom-event scoping | Build (via case 7, 10, or 12) any master list whose plan includes an Event Registration or Education Enrollment branch. Open the resulting list's filter in HubSpot. | Event Registration / Education Enrollment branches use `UNIFIED_EVENTS` (custom events), not a generic `IN_LIST`/property filter; the Education Enrollment branch additionally has a `CONTAINS` filter scoping it to that event's own brand/course keywords (not all LFX Education enrollments) — unless the plan's log explicitly flagged that no course-topic property could be found, in which case this is expected to be missing. |
| 14 | Regression — wizard Custom Audience untouched | Run Campaign Builder Step 3 → Custom Audience sub-tab end to end (plan → approve → build). | Behaves identically to before the Audience Builder tab existed — same IDs/behavior, no interference from the new tab's code. |
| 15 | Cross-tab isolation | Start a build in the Audience Builder tab's "Build From Scratch", then switch to Campaign Builder tab and back. | In-progress ticker/state in Audience Builder isn't lost or corrupted by switching tabs; each tab's UI state is independent. |
| 16 | Never-show check | Search for lists in cases 9 or the list-search box anywhere in the app. | No list with "communitySeg" or "CS" in its name/purpose is ever surfaced or suggested — this is a hard rule, flag immediately if seen. |

### Logging results

For each case, note: pass/fail, the event URL or input used, and (for anything
that creates a HubSpot list or email) a link to what was created so it can be
cleaned up. Since `ASSET_TAG` is set, you can find everything you created by
searching HubSpot for `[<your tag>]` and bulk-delete when done — **do not** delete
anything without the tag, that's someone else's data.

### Reporting a bug

Include: which test case #, the exact input (event URL / free-text description),
a screenshot or copy of any error banner, and — if relevant — the browser console
output (F12 → Console) and the `uvicorn` terminal output at the time of failure.
