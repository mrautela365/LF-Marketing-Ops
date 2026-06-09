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
