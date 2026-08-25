"""
Static brand/design-system constants (manual picker — no live HubSpot lookup yet).

Encodes the design-system table from the project brief: header logo, hero style,
CTA color, sender identity, and the type-level rules (survey heroes are abstract
tech-pattern; report heroes are flat-color + tablet mockup; surveys carry the
Privacy/Visibility/Questions legal block, reports do not).
"""

BRANDS = {
    "lf_research": {
        "label": "LF Research (general)",
        "header_logo_text": "The Linux Foundation | Research",
        "hero_accent": "#1a3c6e",
        "cta_color": "#e2231a",
        "sender_name": "LF Research",
        "sender_address": "The Linux Foundation, 548 Market St, PMB 57274, San Francisco, CA 94104",
        "data_host": "Zenodo",
        "extra_blocks": [],
        "hubspot_search_term": "LF Research",
        "clone_source_overrides": {
            "survey": "26Q2 - LF Research - FINOS 2026: Email Outreach: Email 3 (Survey Promo)",
        },
    },
    "cncf": {
        "label": "CNCF (fielded with LF Research)",
        "header_logo_text": "CNCF",
        "hero_accent": "#0a2540",
        "cta_color": "#f5841f",
        "sender_name": "CNCF",
        "sender_address": "Cloud Native Computing Foundation, 548 Market St, PMB 57274, San Francisco, CA 94104",
        "data_host": "Zenodo",
        "extra_blocks": [],
        "hubspot_search_term": "CNCF",
    },
    "finos": {
        "label": "FINOS (+ LF Research, GitHub, Scott Logic, BrightQuery)",
        "header_logo_text": "The Linux Foundation | Research",
        "hero_accent": "#0f4c4c",
        "cta_color": "#3fbfad",
        "sender_name": "FINOS",
        "sender_address": "Fintech Open Source Foundation, 548 Market St, PMB 57274, San Francisco, CA 94104",
        "data_host": "Data.World",
        "extra_blocks": [],
        "hubspot_search_term": "FINOS",
        "clone_source_overrides": {
            "survey": "26Q2 - LF Research - FINOS 2026: Email Outreach: Email 3 (Survey Promo)",
        },
    },
    "openssf": {
        "label": "OpenSSF (+ ActiveState, LF AI & Data)",
        "header_logo_text": "OpenSSF",
        "hero_accent": "#0b1e3d",
        "cta_color": "#f5841f",
        "sender_name": "OpenSSF",
        "sender_address": "Open Source Security Foundation, 548 Market St, PMB 57274, San Francisco, CA 94104",
        "data_host": "Zenodo",
        "extra_blocks": ["next_steps", "about_org"],
        "hubspot_search_term": "OpenSSF",
    },
    "todo_group": {
        "label": "CNCF + TODO Group (+ LF Research, FinOps Foundation)",
        "header_logo_text": "CNCF",
        "hero_accent": "#0a2540",
        "cta_color": "#2ecc71",
        "sender_name": "CNCF / TODO Group",
        "sender_address": "Cloud Native Computing Foundation, 548 Market St, PMB 57274, San Francisco, CA 94104",
        "data_host": "Zenodo",
        "extra_blocks": [],
        "hubspot_search_term": "TODO Group",
    },
}


def list_brands() -> list:
    return [{"id": bid, "label": b["label"]} for bid, b in BRANDS.items()]


def get_brand(brand_id: str) -> dict:
    if brand_id not in BRANDS:
        raise KeyError(f"Unknown brand: {brand_id}")
    return BRANDS[brand_id]
