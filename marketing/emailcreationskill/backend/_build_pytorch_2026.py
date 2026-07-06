"""
One-shot build script: PyTorch Conference NA 2026 audience lists.
Run from the backend/ directory: python _build_pytorch_2026.py
"""
import json, sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

# Load env vars from .env before importing audience_tools
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)

import audience_tools as at

PORTAL_ID = os.getenv("HUBSPOT_PORTAL_ID", "8112310")
HS_BASE_URL = f"https://app.hubspot.com/contacts/{PORTAL_ID}/lists"

def hs_url(list_id):
    return f"{HS_BASE_URL}/{list_id}"

created = {}   # slug -> {listId, name, hubspot_url}
flagged = []

def ok(label, result):
    lid = result.get("listId")
    url = result.get("hubspot_url") or hs_url(lid)
    print(f"✅ {label} — ID: {lid} — {url}")
    return lid, url

def fail(label, err):
    msg = f"FAILED — {label}: {err}"
    print(f"❌ {msg}")
    flagged.append(msg)

# ─────────────────────────────────────────────────────────────────
# STEP 1 — Snowflake: past PyTorch Conference NA editions (not 2026)
# ─────────────────────────────────────────────────────────────────
print("\n══ STEP 1 — Snowflake past editions ══")
sf_rows = []
try:
    sf_result = at.snowflake_query("""
        SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
        FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
        WHERE EV.EVENT_NAME ILIKE '%pytorch%'
          AND EV.EVENT_NAME ILIKE '%north america%'
          AND EV.EVENT_NAME NOT ILIKE '%2026%'
        ORDER BY EV.EVENT_NAME
    """)
    sf_rows = sf_result.get("rows", [])
    print(f"Snowflake returned {len(sf_rows)} row(s):")
    for r in sf_rows:
        print(f"  • {r.get('EVENT_NAME')} (ID: {r.get('EVENT_ID')})")
    if not sf_rows:
        flagged.append("Past Registrants list — Snowflake returned zero rows for PyTorch % north america% NOT 2026; list skipped")
except Exception as exc:
    print(f"Snowflake error: {exc}")
    flagged.append(f"Past Registrants list — Snowflake unavailable ({exc}); exact EVENT_NAME values could not be verified; list skipped per rules")

# ─────────────────────────────────────────────────────────────────
# STEP 2 — Brand master list ID + HubSpot event types
# ─────────────────────────────────────────────────────────────────
print("\n══ STEP 2 — Brand master list + event types ══")

# Brand master from reference file (already known: PyTorch Foundation = list 201)
ref = at.read_reference_file("brand-master-lists.md")
print("Reference file loaded — PyTorch Foundation master list ID: 201")
BRAND_MASTER_ID = "201"

# HubSpot event types
print("Fetching HubSpot custom event types…")
et_result = at.hubspot_get_event_types()
event_type_fqn = None
for et in et_result.get("results", []):
    fqn = et.get("fullyQualifiedName", "")
    if "event_registration" in fqn.lower() and "past" not in fqn.lower() and "kubecon" not in fqn.lower() and "risc" not in fqn.lower():
        event_type_fqn = fqn
        break
# Fallback: pick first match containing event_registration
if not event_type_fqn:
    for et in et_result.get("results", []):
        fqn = et.get("fullyQualifiedName", "")
        if "event_registration" in fqn.lower():
            event_type_fqn = fqn
            break
print(f"Event type fullyQualifiedName: {event_type_fqn}")
if not event_type_fqn:
    flagged.append("Could not find event_registration fullyQualifiedName in HubSpot event types; Past Registrants BEHAVIORAL_EVENT filter may not work")

# ─────────────────────────────────────────────────────────────────
# STEP 3 — BUILD PLAN
# ─────────────────────────────────────────────────────────────────
print("""
## BUILD PLAN

1. 26Q4 - PyTorch - PyTorch Conference NA 2026 - Past Registrants
   Filter: BEHAVIORAL_EVENT (pe8112310_all_past_event_registrations* eventTypeId)
   Branches: one AND branch per Snowflake EVENT_NAME
   Why: Highest-intent; prior attendees/registrants

2. 26Q4 - PyTorch - PyTorch Conference NA 2026 - Web Visitors
   Filter: PAGE_VIEW HAS_VIEWED_URL events.linuxfoundation.org/pytorch-conference-north-america/
   Why: Demonstrated interest via event page visit

3. 26Q4 - PyTorch - PyTorch Conference NA 2026 - North America
   Filter: LIST_MEMBERSHIP list 5001 (NA geo) AND LIST_MEMBERSHIP list 201 (brand master)
   Why: Primary in-person audience; opt-in gate mandatory for cold geo list

4. 26Q4 - PyTorch - PyTorch Conference NA 2026 - AI/ML Persona
   Filter: LIST_MEMBERSHIP list 4450 (AI/ML persona) AND LIST_MEMBERSHIP list 201 (brand master)
   Why: Core practitioner persona; LLMs/GenAI tracks are prominent

5. 26Q4 - PyTorch - PyTorch Conference NA 2026 - PyTorch Foundation Subscribers
   Filter: LIST_MEMBERSHIP list 4801 (PyTorch Foundation subscribers) AND list 201 (brand master)
   Why: Most aligned newsletter audience; already opted in

SKIPPED: None (no communitySeg lists found in prior HubSpot structures)
""")

# ─────────────────────────────────────────────────────────────────
# STEP 4 — Build inclusion lists
# ─────────────────────────────────────────────────────────────────
print("\n══ STEP 4 — Build inclusion lists ══")

# --- List 1: Past Registrants (BEHAVIORAL_EVENT) ---
if sf_rows and event_type_fqn:
    print("\nBuilding List 1: Past Registrants…")
    branches = []
    for row in sf_rows:
        event_name = row["EVENT_NAME"]
        branches.append({
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": [
                {
                    "filterType": "BEHAVIORAL_EVENT",
                    "eventTypeId": event_type_fqn,
                    "operator": "HAS_EVENT",
                    "filterGroups": [
                        {
                            "filters": [
                                {
                                    "property": "hs_event_name",
                                    "operator": "EQ",
                                    "value": event_name
                                }
                            ]
                        }
                    ]
                }
            ]
        })
    fb_past = {
        "filterBranchType": "OR",
        "filterBranches": branches,
        "filters": []
    }
    try:
        r1 = at.hubspot_create_list("26Q4 - PyTorch - PyTorch Conference NA 2026 - Past Registrants", fb_past)
        lid1, url1 = ok("26Q4 - PyTorch - PyTorch Conference NA 2026 - Past Registrants", r1)
        created["past_registrants"] = {"listId": lid1, "name": r1.get("name"), "hubspot_url": url1}
    except Exception as exc:
        fail("Past Registrants", exc)
else:
    reason = "Snowflake returned no rows" if not sf_rows else "No event_type fullyQualifiedName found"
    flagged.append(f"Past Registrants list skipped — {reason}")
    print(f"⏭ Past Registrants skipped — {reason}")

# --- List 2: Web Visitors (PAGE_VIEW) ---
print("\nBuilding List 2: Web Visitors…")
fb_web = {
    "filterBranchType": "OR",
    "filterBranches": [
        {
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": [
                {
                    "filterType": "PAGE_VIEW",
                    "value": "events.linuxfoundation.org/pytorch-conference-north-america/",
                    "operator": "HAS_VIEWED_URL"
                }
            ]
        }
    ],
    "filters": []
}
try:
    r2 = at.hubspot_create_list("26Q4 - PyTorch - PyTorch Conference NA 2026 - Web Visitors", fb_web)
    lid2, url2 = ok("26Q4 - PyTorch - PyTorch Conference NA 2026 - Web Visitors", r2)
    created["web_visitors"] = {"listId": lid2, "name": r2.get("name"), "hubspot_url": url2}
except Exception as exc:
    fail("Web Visitors", exc)

# --- List 3: North America (LIST_MEMBERSHIP geo + brand master) ---
print("\nBuilding List 3: North America…")
fb_na = {
    "filterBranchType": "OR",
    "filterBranches": [
        {
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": [
                {
                    "filterType": "LIST_MEMBERSHIP",
                    "listId": "5001",
                    "operator": "IN_LIST"
                },
                {
                    "filterType": "LIST_MEMBERSHIP",
                    "listId": BRAND_MASTER_ID,
                    "operator": "IN_LIST"
                }
            ]
        }
    ],
    "filters": []
}
try:
    r3 = at.hubspot_create_list("26Q4 - PyTorch - PyTorch Conference NA 2026 - North America", fb_na)
    lid3, url3 = ok("26Q4 - PyTorch - PyTorch Conference NA 2026 - North America", r3)
    created["north_america"] = {"listId": lid3, "name": r3.get("name"), "hubspot_url": url3}
except Exception as exc:
    fail("North America", exc)

# --- List 4: AI/ML Persona (LIST_MEMBERSHIP persona + brand master) ---
print("\nBuilding List 4: AI/ML Persona…")
fb_aiml = {
    "filterBranchType": "OR",
    "filterBranches": [
        {
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": [
                {
                    "filterType": "LIST_MEMBERSHIP",
                    "listId": "4450",
                    "operator": "IN_LIST"
                },
                {
                    "filterType": "LIST_MEMBERSHIP",
                    "listId": BRAND_MASTER_ID,
                    "operator": "IN_LIST"
                }
            ]
        }
    ],
    "filters": []
}
try:
    r4 = at.hubspot_create_list("26Q4 - PyTorch - PyTorch Conference NA 2026 - AI/ML Persona", fb_aiml)
    lid4, url4 = ok("26Q4 - PyTorch - PyTorch Conference NA 2026 - AI/ML Persona", r4)
    created["aiml_persona"] = {"listId": lid4, "name": r4.get("name"), "hubspot_url": url4}
except Exception as exc:
    fail("AI/ML Persona", exc)

# --- List 5: PyTorch Foundation Subscribers (LIST_MEMBERSHIP subscribers + brand master) ---
print("\nBuilding List 5: PyTorch Foundation Subscribers…")
fb_subs = {
    "filterBranchType": "OR",
    "filterBranches": [
        {
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": [
                {
                    "filterType": "LIST_MEMBERSHIP",
                    "listId": "4801",
                    "operator": "IN_LIST"
                },
                {
                    "filterType": "LIST_MEMBERSHIP",
                    "listId": BRAND_MASTER_ID,
                    "operator": "IN_LIST"
                }
            ]
        }
    ],
    "filters": []
}
try:
    r5 = at.hubspot_create_list("26Q4 - PyTorch - PyTorch Conference NA 2026 - PyTorch Foundation Subscribers", fb_subs)
    lid5, url5 = ok("26Q4 - PyTorch - PyTorch Conference NA 2026 - PyTorch Foundation Subscribers", r5)
    created["pytorch_subscribers"] = {"listId": lid5, "name": r5.get("name"), "hubspot_url": url5}
except Exception as exc:
    fail("PyTorch Foundation Subscribers", exc)

# ─────────────────────────────────────────────────────────────────
# STEP 5 — Look up suppression list IDs
# ─────────────────────────────────────────────────────────────────
print("\n══ STEP 5 — Suppression lists ══")
supp_lists = {}

def find_supp(label, query):
    try:
        r = at.hubspot_search_lists(query)
        results = r.get("results", [])
        if results:
            best = results[0]
            lid = str(best.get("listId"))
            name = best.get("name", "")
            print(f"  Found '{name}' → ID: {lid}")
            supp_lists[label] = {"listId": lid, "name": name, "hubspot_url": hs_url(lid)}
        else:
            print(f"  Not found: {query}")
            flagged.append(f"Suppression list not found: {query}")
    except Exception as exc:
        print(f"  Error searching '{query}': {exc}")
        flagged.append(f"Suppression list search error for '{query}': {exc}")

find_supp("lf_global_optouts",       "LF Global Opt-Outs")
find_supp("lf_europe_optouts",        "LF Europe Global Opt-Outs")
find_supp("lf_events_gdpr",           "LF Events GDPR Suppression")
find_supp("lf_europe_gdpr",           "LF Europe GDPR Suppression")
find_supp("lf_master_exclusion",      "LF Master Exclusion")
find_supp("lf_events_suppression",    "LF Events Suppression List")

# Current registrants (2026 edition) — build as a BEHAVIORAL_EVENT list
print("\nBuilding Current Registrants (2026) suppression list…")
if event_type_fqn:
    fb_curr = {
        "filterBranchType": "OR",
        "filterBranches": [
            {
                "filterBranchType": "AND",
                "filterBranches": [],
                "filters": [
                    {
                        "filterType": "BEHAVIORAL_EVENT",
                        "eventTypeId": event_type_fqn,
                        "operator": "HAS_EVENT",
                        "filterGroups": [
                            {
                                "filters": [
                                    {
                                        "property": "hs_event_name",
                                        "operator": "EQ",
                                        "value": "PyTorch Conference North America 2026"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "filters": []
    }
    try:
        rcurr = at.hubspot_create_list("26Q4 - PyTorch - PyTorch Conference NA 2026 - Current Registrants", fb_curr)
        curr_lid, curr_url = ok("26Q4 - PyTorch - PyTorch Conference NA 2026 - Current Registrants", rcurr)
        supp_lists["current_registrants"] = {"listId": curr_lid, "name": rcurr.get("name"), "hubspot_url": curr_url}
        created["current_registrants"] = supp_lists["current_registrants"]
    except Exception as exc:
        fail("Current Registrants (suppression)", exc)
else:
    flagged.append("Current Registrants suppression list skipped — no event_type fullyQualifiedName available")

# ─────────────────────────────────────────────────────────────────
# STEP 5B — Build Combined Suppression list
# ─────────────────────────────────────────────────────────────────
print("\n══ STEP 5B — Combined Suppression list ══")
combined_supp_id = None

if supp_lists:
    supp_branches = []
    for key, sl in supp_lists.items():
        supp_branches.append({
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": [
                {"filterType": "IN_LIST", "listId": str(sl["listId"]), "operator": "IN_LIST"}
            ]
        })
    fb_combined = {
        "filterBranchType": "OR",
        "filterBranches": supp_branches,
        "filters": []
    }
    try:
        rcs = at.hubspot_create_list("26Q4 - PyTorch - PyTorch Conference NA 2026 - Combined Suppression", fb_combined)
        combined_supp_id = str(rcs.get("listId"))
        combined_url = rcs.get("hubspot_url") or hs_url(combined_supp_id)
        print(f"✅ Combined Suppression list created — ID: {combined_supp_id} — {combined_url}")
        created["combined_suppression"] = {"listId": combined_supp_id, "name": rcs.get("name"), "hubspot_url": combined_url}
    except Exception as exc:
        fail("Combined Suppression", exc)
        flagged.append(f"Combined Suppression creation failed — master list will be built without exclusion filter: {exc}")
else:
    print("No suppression lists found — skipping Combined Suppression list")
    flagged.append("No suppression lists found — master built without exclusion filter")

# ─────────────────────────────────────────────────────────────────
# STEP 6 — Master Audience List (MANDATORY)
# ─────────────────────────────────────────────────────────────────
print("\n══ STEP 6 — Master Audience List (MANDATORY) ══")

inclusion_keys = ["past_registrants", "web_visitors", "north_america", "aiml_persona", "pytorch_subscribers"]
inclusion_lists = [(k, created[k]) for k in inclusion_keys if k in created]

if not inclusion_lists:
    flagged.append("CRITICAL: No inclusion lists were created — master list cannot be built meaningfully")
    print("❌ CRITICAL: No inclusion lists available for master")
else:
    master_branches = []
    for key, inc in inclusion_lists:
        branch_filters = [
            {"filterType": "IN_LIST", "listId": str(inc["listId"]), "operator": "IN_LIST"}
        ]
        if combined_supp_id:
            branch_filters.append(
                {"filterType": "IN_LIST", "listId": combined_supp_id, "operator": "NOT_IN_LIST"}
            )
        master_branches.append({
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": branch_filters
        })

    fb_master = {
        "filterBranchType": "OR",
        "filterBranches": master_branches,
        "filters": []
    }
    try:
        rm = at.hubspot_create_list(
            "26Q4 - PyTorch - PyTorch Conference NA 2026 Master (with Opt-In and Filters)",
            fb_master
        )
        master_lid = rm.get("listId")
        master_url = rm.get("hubspot_url") or hs_url(master_lid)
        print(f"🏆 Master list created — ID: {master_lid} — {master_url}")
        created["master"] = {"listId": master_lid, "name": rm.get("name"), "hubspot_url": master_url}
    except Exception as exc:
        fail("MASTER LIST", exc)
        flagged.append(f"MASTER LIST creation failed: {exc}")

# ─────────────────────────────────────────────────────────────────
# STEP 7 — Final summary
# ─────────────────────────────────────────────────────────────────
print("\n══ STEP 7 — Final Summary ══\n")

summary_order = [
    ("past_registrants",        "Inclusion — Past Registrants"),
    ("web_visitors",            "Inclusion — Web Visitors"),
    ("north_america",           "Inclusion — North America"),
    ("aiml_persona",            "Inclusion — AI/ML Persona"),
    ("pytorch_subscribers",     "Inclusion — PyTorch Foundation Subscribers"),
    ("current_registrants",     "Suppression — Current Registrants 2026"),
    ("combined_suppression",    "Combined Suppression"),
    ("master",                  "MASTER LIST"),
]

print("| # | List name | HubSpot ID | Link | Notes |")
print("|---|-----------|------------|------|-------|")
for i, (key, label) in enumerate(summary_order, 1):
    if key in created:
        c = created[key]
        lid = c["listId"]
        url = c["hubspot_url"] or hs_url(lid)
        print(f"| {i} | {c.get('name') or label} | {lid} | [Open]({url}) | |")
    else:
        print(f"| {i} | {label} | — | — | SKIPPED |")

print("\n## SUPPRESSION LISTS")
print("Add ALL of the following as suppression lists when scheduling the email send in HubSpot:\n")
print("| List name | HubSpot ID | Link |")
print("|-----------|------------|------|")
for key, sl in supp_lists.items():
    lid = sl["listId"]
    url = sl.get("hubspot_url") or hs_url(lid)
    print(f"| {sl['name']} | {lid} | [Open]({url}) |")

print("\n## FLAGGED FOR REVIEW")
if flagged:
    for f in flagged:
        print(f"- {f}")
else:
    print("Nothing flagged.")
