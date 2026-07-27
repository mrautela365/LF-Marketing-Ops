"""
Known event → brand mapping used to resolve the correct HubSpot brand name,
short brand code, and short event name from a scraped event name.
"""
import re

BRAND_MAP = [
    {"event_name": "LF Decentralized Trust Member Summit",        "event_short_name": "LFDT Member Summit", "brand_name": "LF Decentralized Trust",            "short_brand_name": "LFDT"},
    {"event_name": "PyTorch Day India",                           "event_short_name": "PT Day India",        "brand_name": "PyTorch Foundation",                "short_brand_name": "PTF"},
    {"event_name": "The Linux Foundation Member Summit",          "event_short_name": "LF Member Summit",    "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "HPSF Conference",                             "event_short_name": "HPSF Conf",           "brand_name": "High Performance Software Foundation","short_brand_name": "HPSF"},
    {"event_name": "OpenSearchCon China",                         "event_short_name": "OSC China",           "brand_name": "OpenSearch Software Foundation",    "short_brand_name": "OSSF"},
    {"event_name": "OpenSearchCon North America",                 "event_short_name": "OSC NA",              "brand_name": "OpenSearch Software Foundation",    "short_brand_name": "OSSF"},
    {"event_name": "KubeCon + CloudNativeCon Europe",             "event_short_name": "KubeCon EU",          "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Agentics Day: MCP + Agents Europe",           "event_short_name": "Agentics Day EU",     "brand_name": "Agentic AI Foundation",            "short_brand_name": "AIF"},
    {"event_name": "CiliumCon Europe",                            "event_short_name": "CiliumCon EU",        "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Cloud Native AI + Kubeflow Day Europe",       "event_short_name": "Kubeflow Day EU",     "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "MCP Dev Summit North America",                "event_short_name": "MCP Dev Summit NA",   "brand_name": "Agentic AI Foundation",            "short_brand_name": "AIF"},
    {"event_name": "PyTorch Conference Europe",                   "event_short_name": "PyTorch EU",          "brand_name": "PyTorch Foundation",                "short_brand_name": "PTF"},
    {"event_name": "Open Source in Finance Forum Toronto",        "event_short_name": "OSFF Toronto",        "brand_name": "FINOS",                            "short_brand_name": "FINOS"},
    {"event_name": "OpenSearchCon Europe",                        "event_short_name": "OSC Europe",          "brand_name": "OpenSearch Software Foundation",   "short_brand_name": "OSSF"},
    {"event_name": "Overture Member Summit",                      "event_short_name": "OMF Member Summit",   "brand_name": "Overture Maps Foundation",         "short_brand_name": "OMF"},
    {"event_name": "Linux Storage, Filesystem, MM & BPF Summit", "event_short_name": "LSFMM+BPF",           "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Open Source Summit North America",            "event_short_name": "OSS NA",              "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Embedded Linux Conference North America",     "event_short_name": "ELC NA",              "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "OpenSSF Community Day North America",         "event_short_name": "Community Day NA",    "brand_name": "Open Source Security Foundation",  "short_brand_name": "OpenSSF"},
    {"event_name": "Open Source Policy & Ecosystem Forum",       "event_short_name": "OSPE Forum",          "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "European Open Source Security Forum",         "event_short_name": "OSS EU",              "brand_name": "Open Source Security Foundation",  "short_brand_name": "OpenSSF"},
    {"event_name": "MCP Dev Summit Bengaluru",                    "event_short_name": "MCP Bengaluru",       "brand_name": "Agentic AI Foundation",            "short_brand_name": "AIF"},
    {"event_name": "OpenSearchCon India",                         "event_short_name": "OSC India",           "brand_name": "OpenSearch Software Foundation",   "short_brand_name": "OSSF"},
    {"event_name": "Open Source Summit India",                    "event_short_name": "OSSI",                "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "KubeCon + CloudNativeCon India",              "event_short_name": "KubeCon India",       "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Open Source in Finance Forum London",         "event_short_name": "OSFF London",         "brand_name": "FINOS",                            "short_brand_name": "FINOS"},
    {"event_name": "ASWF Open Source Days",                       "event_short_name": "ASWF OSD",            "brand_name": "Academy Software Foundation",      "short_brand_name": "ASWF"},
    {"event_name": "KubeCon + CloudNativeCon Japan",              "event_short_name": "KubeCon Japan",       "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "MCP Dev Summit Toronto",                      "event_short_name": "MCP Toronto",         "brand_name": "Agentic AI Foundation",            "short_brand_name": "AIF"},
    {"event_name": "Observability Summit Europe",                 "event_short_name": "Obs Summit EU",       "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Linux Foundation Member European Forum",      "event_short_name": "LF Forum EU",         "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "OpenSSF Community Day Europe",                "event_short_name": "Community Day EU",    "brand_name": "Open Source Security Foundation",  "short_brand_name": "OpenSSF"},
    {"event_name": "Embedded Linux Conference Europe",            "event_short_name": "ELC Europe",          "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Open Source Summit Europe",                   "event_short_name": "OSS Europe",          "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Linux Kernel Maintainer Summit",              "event_short_name": "LKMS",                "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Linux Security Summit Europe",                "event_short_name": "LSS Europe",          "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "BazelCon",                                    "event_short_name": "BazelCon",            "brand_name": "Bazel Project",                    "short_brand_name": "BAZEL"},
    {"event_name": "PyTorch Conference North America",            "event_short_name": "PyTorch NA",          "brand_name": "PyTorch Foundation",                "short_brand_name": "PTF"},
    {"event_name": "AGNTCon + MCPCon North America",              "event_short_name": "AGNTCon",             "brand_name": "Agentic AI Foundation",            "short_brand_name": "AIF"},
    {"event_name": "Open Source in Finance Forum New York",       "event_short_name": "OSFF New York",       "brand_name": "FINOS",                            "short_brand_name": "FINOS"},
    {"event_name": "Observability Day North America",             "event_short_name": "Obs Day NA",          "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Open Source SecurityCon North America",       "event_short_name": "SecurityCon",         "brand_name": "Open Source Security Foundation",  "short_brand_name": "OpenSSF"},
    {"event_name": "Platform Engineering Day North America",      "event_short_name": "PED NA",              "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "KubeCon + CloudNativeCon North America",      "event_short_name": "KubeCon NA",          "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Open Source Summit Korea",                    "event_short_name": "OSS Korea",           "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Open Source Summit Japan",                    "event_short_name": "OSS Japan",           "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "ONE Summit Japan",                            "event_short_name": "ONE Summit",          "brand_name": "LF Networking",                    "short_brand_name": "LFN"},
    {"event_name": "Automotive Linux Summit",                     "event_short_name": "ALS",                 "brand_name": "Automotive Grade Linux",           "short_brand_name": "AGL"},
    {"event_name": "Embedded Linux Conference Asia",              "event_short_name": "ELC Asia",            "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Open Compliance Summit",                                                      "event_short_name": "OCS",                     "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    # ── Additional events ────────────────────────────────────────────────────────────────────────
    {"event_name": "seL4 Summit",                                                                  "event_short_name": "seL4 Summit",             "brand_name": "seL4 Foundation",                   "short_brand_name": "SEL4"},
    {"event_name": "LF Energy Summit",                                                             "event_short_name": "LF Energy Summit",        "brand_name": "LF Energy",                         "short_brand_name": "LFE"},
    {"event_name": "LF Energy Summit Europe",                                                      "event_short_name": "LF Energy Summit EU",     "brand_name": "LF Energy",                         "short_brand_name": "LFE"},
    {"event_name": "Cloud Foundry Day",                                                            "event_short_name": "CF Day",                  "brand_name": "Cloud Foundry Foundation",          "short_brand_name": "CFF"},
    {"event_name": "Cloud Foundry Summit",                                                         "event_short_name": "CF Summit",               "brand_name": "Cloud Foundry Foundation",          "short_brand_name": "CFF"},
    {"event_name": "Confidential Computing Summit",                                                "event_short_name": "CC Summit",               "brand_name": "Confidential Computing Consortium", "short_brand_name": "CCC"},
    {"event_name": "ArgoCon Japan",                                                                "event_short_name": "ArgoCon Japan",           "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "ArgoCon North America",                                                        "event_short_name": "ArgoCon NA",              "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "KeyCloakCon Japan",                                                            "event_short_name": "KeycloakCon Japan",       "brand_name": "Keycloak Project",                  "short_brand_name": "KEYCLOAK"},
    {"event_name": "MCP Dev Summit Seoul",                                                         "event_short_name": "MCP Seoul",               "brand_name": "Agentic AI Foundation",             "short_brand_name": "AIF"},
    {"event_name": "MCP Dev Summit Nairobi",                                                       "event_short_name": "MCP Nairobi",             "brand_name": "Agentic AI Foundation",             "short_brand_name": "AIF"},
    {"event_name": "Kubeflow Community Showcase 2026: GenAI and MLOps in Action",                  "event_short_name": "Kubeflow Showcase",       "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "gRPConf North America",                                                        "event_short_name": "gRPConf NA",              "brand_name": "gRPC",                              "short_brand_name": "GRPC"},
    {"event_name": "AGNTCon + MCPCon China",                                                       "event_short_name": "AGNTCon China",           "brand_name": "Agentic AI Foundation",             "short_brand_name": "AIF"},
    {"event_name": "AGNTCon + MCPCon Japan",                                                       "event_short_name": "AGNTCon Japan",           "brand_name": "Agentic AI Foundation",             "short_brand_name": "AIF"},
    {"event_name": "AGNTCon + MCPCon Europe",                                                      "event_short_name": "AGNTCon Europe",          "brand_name": "Agentic AI Foundation",             "short_brand_name": "AIF"},
    {"event_name": "KubeCon + CloudNativeCon + OpenInfra Summit + PyTorch Conference China",       "event_short_name": "KubeCon China",           "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Automotive Grade Linux All Member Meeting Europe",                             "event_short_name": "AGL Member Meeting EU",   "brand_name": "Automotive Grade Linux",            "short_brand_name": "AGL"},
    {"event_name": "kcpCON",                                                                       "event_short_name": "kcpCON",                  "brand_name": "kcp Project",                       "short_brand_name": "KCP"},
    {"event_name": "Linux Plumbers Conference",                                                    "event_short_name": "LPC",                     "brand_name": "The Linux Foundation",              "short_brand_name": "LF"},
    {"event_name": "Agentics Day: MCP + Agents North America",                                     "event_short_name": "Agentics Day NA",         "brand_name": "Agentic AI Foundation",             "short_brand_name": "AIF"},
    {"event_name": "BackstageCon North America",                                                   "event_short_name": "BackstageCon NA",         "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "CiliumCon North America",                                                      "event_short_name": "CiliumCon NA",            "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Cloud Native AI & Inference Day North America",                                "event_short_name": "AI & Inference Day",      "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "FluxCon North America",                                                        "event_short_name": "FluxCon NA",              "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
    {"event_name": "Kubernetes on Edge Day North America",                                         "event_short_name": "KubeEdge Day",            "brand_name": "Cloud Native Computing Foundation", "short_brand_name": "CNCF"},
]

# City → (country, broad_region).  Used to build the fallback chain:
#   city match → country match → region match → AI decides from full pool
CITY_TO_COUNTRY: dict[str, tuple[str, str]] = {
    # North America
    "toronto":       ("Canada",  "North America"),
    "vancouver":     ("Canada",  "North America"),
    "montreal":      ("Canada",  "North America"),
    "chicago":       ("USA",     "North America"),
    "seattle":       ("USA",     "North America"),
    "san francisco": ("USA",     "North America"),
    "new york":      ("USA",     "North America"),
    "austin":        ("USA",     "North America"),
    "denver":        ("USA",     "North America"),
    "atlanta":       ("USA",     "North America"),
    "los angeles":   ("USA",     "North America"),
    "boston":        ("USA",     "North America"),
    "washington":    ("USA",     "North America"),
    "miami":         ("USA",     "North America"),
    "detroit":       ("USA",     "North America"),
    # Europe
    "amsterdam":     ("Netherlands", "Europe"),
    "paris":         ("France",      "Europe"),
    "berlin":        ("Germany",     "Europe"),
    "munich":        ("Germany",     "Europe"),
    "london":        ("UK",          "Europe"),
    "barcelona":     ("Spain",       "Europe"),
    "madrid":        ("Spain",       "Europe"),
    "vienna":        ("Austria",     "Europe"),
    "brussels":      ("Belgium",     "Europe"),
    "stockholm":     ("Sweden",      "Europe"),
    "dublin":        ("Ireland",     "Europe"),
    "copenhagen":    ("Denmark",     "Europe"),
    "milan":         ("Italy",       "Europe"),
    "rome":          ("Italy",       "Europe"),
    "prague":        ("Czech Republic", "Europe"),
    "warsaw":        ("Poland",      "Europe"),
    "zurich":        ("Switzerland", "Europe"),
    "geneva":        ("Switzerland", "Europe"),
    "lisbon":        ("Portugal",    "Europe"),
    "oslo":          ("Norway",      "Europe"),
    "helsinki":      ("Finland",     "Europe"),
    # Asia
    "shanghai":      ("China",       "Asia"),
    "beijing":       ("China",       "Asia"),
    "shenzhen":      ("China",       "Asia"),
    "tokyo":         ("Japan",       "Asia"),
    "osaka":         ("Japan",       "Asia"),
    "seoul":         ("South Korea", "Asia"),
    "bangalore":     ("India",       "Asia"),
    "bengaluru":     ("India",       "Asia"),
    "mumbai":        ("India",       "Asia"),
    "hyderabad":     ("India",       "Asia"),
    "delhi":         ("India",       "Asia"),
    "singapore":     ("Singapore",   "Asia Pacific"),
    "sydney":        ("Australia",   "Asia Pacific"),
    "melbourne":     ("Australia",   "Asia Pacific"),
    # Africa
    "nairobi":       ("Kenya",        "Africa"),
    "cape town":     ("South Africa", "Africa"),
    "johannesburg":  ("South Africa", "Africa"),
    "lagos":         ("Nigeria",      "Africa"),
    # Middle East
    "dubai":         ("UAE",   "Middle East"),
    "tel aviv":      ("Israel","Middle East"),
    "istanbul":      ("Turkey","Middle East"),
}


def location_fallback_chain(location: str) -> list[set]:
    """
    Given a scraped location string, return an ordered list of word-sets to try
    when filtering HubSpot email candidates:
      [city_words, country_words, region_words]
    The caller tries each level in order and stops at the first that yields >= 2 hits.
    If none match, the full pool is passed to AI.

    Examples:
      "Toronto"              → [{"toronto"}, {"canada","ca"}, {"north","america","na"}]
      "Amsterdam, Netherlands" → [{"amsterdam"}, {"netherlands","nl"}, {"europe","eu"}]
      "North America"        → [{"north","america","na"}]   (already a region — 1 level)
    """
    if not location:
        return []

    loc_lower = location.lower().strip()

    # Parse "City, Country" or "City, State, Country" format — the country is
    # always the LAST comma-separated segment; middle segments (state/province)
    # are dropped since they aren't useful for matching HubSpot email names.
    if "," in loc_lower:
        parts        = [p.strip() for p in loc_lower.split(",")]
        city_part    = parts[0]
        country_part = parts[-1]
    else:
        city_part    = loc_lower
        country_part = ""

    chain: list[set] = []

    # Level 1 — city
    city_words = expand_location_words(city_part)
    if city_words:
        chain.append(city_words)

    # Resolve country + region from city lookup or parsed country
    country_name, region_name = "", ""
    if city_part in CITY_TO_COUNTRY:
        country_name, region_name = CITY_TO_COUNTRY[city_part]
    elif country_part:
        country_name = country_part
        # Try to infer region from any matching city entry
        for _city, (cn, rn) in CITY_TO_COUNTRY.items():
            if cn.lower() == country_part:
                region_name = rn
                break

    # Level 2 — country (skip if same as city, e.g. "Japan" scraped as city)
    if country_name and country_name.lower() != city_part:
        country_words = expand_location_words(country_name)
        if country_words:
            chain.append(country_words)

    # Level 3 — broad region
    if region_name and region_name.lower() not in {city_part, country_name.lower()}:
        region_words = expand_location_words(region_name)
        if region_words:
            chain.append(region_words)

    return chain


# Ordered list of known location terms to scan for inside event names.
# Longer/more-specific phrases first so "North America" matches before "America".
_KNOWN_LOCATION_TERMS = [
    # Multi-word regions first
    "North America", "South America", "Latin America", "Asia Pacific", "Middle East",
    "Southeast Asia", "Central Asia",
    # Abbreviations
    "APAC", "LATAM",
    # Single-word regions
    "Europe", "Asia", "Africa",
    # Countries
    "Japan", "China", "India", "Germany", "France", "Netherlands", "Spain",
    "Austria", "Belgium", "Sweden", "Ireland", "Denmark", "Italy", "Poland",
    "Switzerland", "Portugal", "Norway", "Finland", "UK", "Canada", "Australia",
    "Singapore", "South Korea", "Korea", "Kenya", "Nigeria", "South Africa",
    "UAE", "Israel", "Turkey",
    # Common cities used in LF event names
    "Tokyo", "Shanghai", "Beijing", "Seoul", "Toronto", "Vancouver",
    "Berlin", "Amsterdam", "Paris", "London", "Barcelona", "Vienna",
    "Brussels", "Stockholm", "Dublin", "Copenhagen", "Milan", "Prague",
    "Bengaluru", "Bangalore", "Mumbai", "Hyderabad", "Delhi", "Singapore",
    "Sydney", "Melbourne", "Nairobi", "Cape Town", "Dubai", "Chicago",
    "Seattle", "Austin", "Denver", "Atlanta", "New York", "San Francisco",
]


def extract_location_from_name(event_name: str) -> str:
    """
    Scan an event name for a recognised location term and return it.
    Longer phrases are checked first so "North America" wins over "America".
    Returns "" if nothing recognised is found.

    Examples:
      "LF Energy Summit Europe"          → "Europe"
      "KubeCon + CloudNativeCon Japan"   → "Japan"
      "Open Source Summit North America" → "North America"
      "OpenSearchCon"                    → ""
    """
    name_lower = event_name.lower()
    for term in _KNOWN_LOCATION_TERMS:
        if term.lower() in name_lower:
            return term
    return ""


def build_location_chain(event_name: str, scraped_location: str) -> list[set]:
    """
    Build the full location fallback chain by combining:
      1. Location found in the event name (highest priority — matches HubSpot naming)
      2. Scraped city/country/region (fallback)

    Duplicate word-sets are skipped so we never retry the same filter twice.
    """
    seen: list[frozenset] = []
    chain: list[set] = []

    def _add(word_set: set) -> None:
        fs = frozenset(word_set)
        if fs and fs not in seen:
            seen.append(fs)
            chain.append(word_set)

    # Priority 1: location embedded in the event name (e.g. "Europe" in "LF Energy Summit Europe")
    name_loc = extract_location_from_name(event_name)
    if name_loc:
        for level in location_fallback_chain(name_loc):
            _add(level)

    # Priority 2: scraped city → country → region
    for level in location_fallback_chain(scraped_location):
        _add(level)

    return chain


def filter_candidates_by_locale(candidates: list, event_name: str, location: str,
                                 name_key: str = "name") -> tuple[list, str]:
    """
    Restrict `candidates` (HubSpot email dicts) to the SAME event locale (city, or
    name-embedded region/country) as the current event — e.g. a "MCP Dev Summit
    Bengaluru" plan must never reuse "MCP Dev Summit Toronto" history, and a
    "KubeCon + CloudNativeCon Europe" plan must never reuse the North America edition.

    Tries the single most specific locale level available (event-name-embedded
    location first, then scraped city/country/region — see build_location_chain)
    and returns the FIRST level with at least one match. Unlike a broadening
    cascade, this does NOT fall back to a broader region or an unfiltered
    cross-locale pool when the most specific level comes up empty: a locale
    mismatch means "no matching past event for this location", not "let the AI
    (or a keyword search) guess from every country".

    Returns (candidates, "no_location_data") unchanged only when neither the event
    name nor the scraped location contain any recognised locale at all — i.e.
    there's nothing to filter by, not that filtering was skipped.
    """
    chain = build_location_chain(event_name, location)
    if not chain:
        return candidates, "no_location_data"

    for idx, loc_words in enumerate(chain):
        hits = [c for c in candidates if any(w in (c.get(name_key) or "").lower() for w in loc_words)]
        if hits:
            return hits, f"level_{idx + 1} ({', '.join(sorted(loc_words))})"

    return [], "no_locale_match"


# Maps full region names ↔ their short codes used in HubSpot email names.
# Used to expand location words so "North America" also matches "NA" emails and vice versa.
LOCATION_ALIASES: dict[str, str] = {
    "north america": "NA",
    "south america": "SA",
    "latin america": "LATAM",
    "europe":        "EU",
    "asia pacific":  "APAC",
    "middle east":   "ME",
    "north africa":  "NA",   # rare but present
    "united states": "US",
    "united kingdom": "UK",
}
# Reverse map: short code → full name
_ALIAS_REVERSE: dict[str, str] = {v.lower(): k for k, v in LOCATION_ALIASES.items()}


def expand_location_words(location: str) -> set:
    """
    Return a set of all words (and abbreviations) that should match emails for this location.
    e.g. "North America" → {"north", "america", "na"}
         "EU"            → {"eu", "europe"}
    """
    words: set = set()
    loc_lower = location.lower().strip()

    # Add individual words from the location string
    for w in re.findall(r'\w+', loc_lower):
        words.add(w)

    # Add short code if the full phrase matches
    for phrase, code in LOCATION_ALIASES.items():
        if phrase in loc_lower:
            words.add(code.lower())

    # Add full name if a short code was given
    full = _ALIAS_REVERSE.get(loc_lower)
    if full:
        for w in re.findall(r'\w+', full):
            words.add(w)

    return words


_STOP = {"the", "a", "an", "and", "or", "of", "in", "at", "for", "on", "to", "is",
         "lf", "linux", "foundation", "events"}


def _keywords(text: str) -> set:
    return {w.lower() for w in re.findall(r'\w+', text) if len(w) > 2 and w.lower() not in _STOP}


def get_brand_events(short_brand_name: str) -> list:
    """Return all BRAND_MAP entries that share the same short_brand_name."""
    return [e for e in BRAND_MAP if e["short_brand_name"] == short_brand_name]


def lookup_event_brand(event_name: str) -> dict | None:
    """
    Return the best-matching BRAND_MAP entry for a scraped event name,
    or None if no entry scores >= 2 keyword overlaps.
    """
    query_kw = _keywords(event_name)
    if not query_kw:
        return None
    best_score, best = 0, None
    for entry in BRAND_MAP:
        score = len(query_kw & _keywords(entry["event_name"]))
        if score > best_score:
            best_score, best = score, entry
    return best if best_score >= 2 else None
