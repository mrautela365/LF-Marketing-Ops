// Package eventbrands resolves the HubSpot brand name, short brand code, and
// short event name for a scraped event name, and filters HubSpot email
// candidates down to the same event locale. Ports utils/event_brands.py.
// Pure/deterministic — no external calls.
package eventbrands

import (
	"regexp"
	"strings"
)

// BrandEntry is one known event → brand mapping.
type BrandEntry struct {
	EventName      string
	EventShortName string
	BrandName      string
	ShortBrandName string
}

var brandMap = []BrandEntry{
	{"LF Decentralized Trust Member Summit", "LFDT Member Summit", "LF Decentralized Trust", "LFDT"},
	{"PyTorch Day India", "PT Day India", "PyTorch Foundation", "PTF"},
	{"The Linux Foundation Member Summit", "LF Member Summit", "The Linux Foundation", "LF"},
	{"HPSF Conference", "HPSF Conf", "High Performance Software Foundation", "HPSF"},
	{"OpenSearchCon China", "OSC China", "OpenSearch Software Foundation", "OSSF"},
	{"OpenSearchCon North America", "OSC NA", "OpenSearch Software Foundation", "OSSF"},
	{"KubeCon + CloudNativeCon Europe", "KubeCon EU", "Cloud Native Computing Foundation", "CNCF"},
	{"Agentics Day: MCP + Agents Europe", "Agentics Day EU", "Agentic AI Foundation", "AIF"},
	{"CiliumCon Europe", "CiliumCon EU", "Cloud Native Computing Foundation", "CNCF"},
	{"Cloud Native AI + Kubeflow Day Europe", "Kubeflow Day EU", "Cloud Native Computing Foundation", "CNCF"},
	{"MCP Dev Summit North America", "MCP Dev Summit NA", "Agentic AI Foundation", "AIF"},
	{"PyTorch Conference Europe", "PyTorch EU", "PyTorch Foundation", "PTF"},
	{"Open Source in Finance Forum Toronto", "OSFF Toronto", "FINOS", "FINOS"},
	{"OpenSearchCon Europe", "OSC Europe", "OpenSearch Software Foundation", "OSSF"},
	{"Overture Member Summit", "OMF Member Summit", "Overture Maps Foundation", "OMF"},
	{"Linux Storage, Filesystem, MM & BPF Summit", "LSFMM+BPF", "The Linux Foundation", "LF"},
	{"Open Source Summit North America", "OSS NA", "The Linux Foundation", "LF"},
	{"Embedded Linux Conference North America", "ELC NA", "The Linux Foundation", "LF"},
	{"OpenSSF Community Day North America", "Community Day NA", "Open Source Security Foundation", "OpenSSF"},
	{"Open Source Policy & Ecosystem Forum", "OSPE Forum", "The Linux Foundation", "LF"},
	{"European Open Source Security Forum", "OSS EU", "Open Source Security Foundation", "OpenSSF"},
	{"MCP Dev Summit Bengaluru", "MCP Bengaluru", "Agentic AI Foundation", "AIF"},
	{"OpenSearchCon India", "OSC India", "OpenSearch Software Foundation", "OSSF"},
	{"Open Source Summit India", "OSSI", "The Linux Foundation", "LF"},
	{"KubeCon + CloudNativeCon India", "KubeCon India", "Cloud Native Computing Foundation", "CNCF"},
	{"Open Source in Finance Forum London", "OSFF London", "FINOS", "FINOS"},
	{"ASWF Open Source Days", "ASWF OSD", "Academy Software Foundation", "ASWF"},
	{"KubeCon + CloudNativeCon Japan", "KubeCon Japan", "Cloud Native Computing Foundation", "CNCF"},
	{"MCP Dev Summit Toronto", "MCP Toronto", "Agentic AI Foundation", "AIF"},
	{"Observability Summit Europe", "Obs Summit EU", "Cloud Native Computing Foundation", "CNCF"},
	{"Linux Foundation Member European Forum", "LF Forum EU", "The Linux Foundation", "LF"},
	{"OpenSSF Community Day Europe", "Community Day EU", "Open Source Security Foundation", "OpenSSF"},
	{"Embedded Linux Conference Europe", "ELC Europe", "The Linux Foundation", "LF"},
	{"Open Source Summit Europe", "OSS Europe", "The Linux Foundation", "LF"},
	{"Linux Kernel Maintainer Summit", "LKMS", "The Linux Foundation", "LF"},
	{"Linux Security Summit Europe", "LSS Europe", "The Linux Foundation", "LF"},
	{"BazelCon", "BazelCon", "Bazel Project", "BAZEL"},
	{"PyTorch Conference North America", "PyTorch NA", "PyTorch Foundation", "PTF"},
	{"AGNTCon + MCPCon North America", "AGNTCon", "Agentic AI Foundation", "AIF"},
	{"Open Source in Finance Forum New York", "OSFF New York", "FINOS", "FINOS"},
	{"Observability Day North America", "Obs Day NA", "Cloud Native Computing Foundation", "CNCF"},
	{"Open Source SecurityCon North America", "SecurityCon", "Open Source Security Foundation", "OpenSSF"},
	{"Platform Engineering Day North America", "PED NA", "Cloud Native Computing Foundation", "CNCF"},
	{"KubeCon + CloudNativeCon North America", "KubeCon NA", "Cloud Native Computing Foundation", "CNCF"},
	{"Open Source Summit Korea", "OSS Korea", "The Linux Foundation", "LF"},
	{"Open Source Summit Japan", "OSS Japan", "The Linux Foundation", "LF"},
	{"ONE Summit Japan", "ONE Summit", "LF Networking", "LFN"},
	{"Automotive Linux Summit", "ALS", "Automotive Grade Linux", "AGL"},
	{"Embedded Linux Conference Asia", "ELC Asia", "The Linux Foundation", "LF"},
	{"Open Compliance Summit", "OCS", "The Linux Foundation", "LF"},
	{"seL4 Summit", "seL4 Summit", "seL4 Foundation", "SEL4"},
	{"LF Energy Summit", "LF Energy Summit", "LF Energy", "LFE"},
	{"LF Energy Summit Europe", "LF Energy Summit EU", "LF Energy", "LFE"},
	{"Cloud Foundry Day", "CF Day", "Cloud Foundry Foundation", "CFF"},
	{"Cloud Foundry Summit", "CF Summit", "Cloud Foundry Foundation", "CFF"},
	{"Confidential Computing Summit", "CC Summit", "Confidential Computing Consortium", "CCC"},
	{"ArgoCon Japan", "ArgoCon Japan", "Cloud Native Computing Foundation", "CNCF"},
	{"ArgoCon North America", "ArgoCon NA", "Cloud Native Computing Foundation", "CNCF"},
	{"KeyCloakCon Japan", "KeycloakCon Japan", "Keycloak Project", "KEYCLOAK"},
	{"MCP Dev Summit Seoul", "MCP Seoul", "Agentic AI Foundation", "AIF"},
	{"MCP Dev Summit Nairobi", "MCP Nairobi", "Agentic AI Foundation", "AIF"},
	{"Kubeflow Community Showcase 2026: GenAI and MLOps in Action", "Kubeflow Showcase", "Cloud Native Computing Foundation", "CNCF"},
	{"gRPConf North America", "gRPConf NA", "gRPC", "GRPC"},
	{"AGNTCon + MCPCon China", "AGNTCon China", "Agentic AI Foundation", "AIF"},
	{"AGNTCon + MCPCon Japan", "AGNTCon Japan", "Agentic AI Foundation", "AIF"},
	{"AGNTCon + MCPCon Europe", "AGNTCon Europe", "Agentic AI Foundation", "AIF"},
	{"KubeCon + CloudNativeCon + OpenInfra Summit + PyTorch Conference China", "KubeCon China", "Cloud Native Computing Foundation", "CNCF"},
	{"Automotive Grade Linux All Member Meeting Europe", "AGL Member Meeting EU", "Automotive Grade Linux", "AGL"},
	{"kcpCON", "kcpCON", "kcp Project", "KCP"},
	{"Linux Plumbers Conference", "LPC", "The Linux Foundation", "LF"},
	{"Agentics Day: MCP + Agents North America", "Agentics Day NA", "Agentic AI Foundation", "AIF"},
	{"BackstageCon North America", "BackstageCon NA", "Cloud Native Computing Foundation", "CNCF"},
	{"CiliumCon North America", "CiliumCon NA", "Cloud Native Computing Foundation", "CNCF"},
	{"Cloud Native AI & Inference Day North America", "AI & Inference Day", "Cloud Native Computing Foundation", "CNCF"},
	{"FluxCon North America", "FluxCon NA", "Cloud Native Computing Foundation", "CNCF"},
	{"Kubernetes on Edge Day North America", "KubeEdge Day", "Cloud Native Computing Foundation", "CNCF"},
}

type cityInfo struct {
	Country string
	Region  string
}

// cityToCountry maps city → (country, broad_region). Used to build the
// fallback chain: city match → country match → region match → AI decides
// from the full pool.
var cityToCountry = map[string]cityInfo{
	// North America
	"toronto": {"Canada", "North America"}, "vancouver": {"Canada", "North America"}, "montreal": {"Canada", "North America"},
	"chicago": {"USA", "North America"}, "seattle": {"USA", "North America"}, "san francisco": {"USA", "North America"},
	"new york": {"USA", "North America"}, "austin": {"USA", "North America"}, "denver": {"USA", "North America"},
	"atlanta": {"USA", "North America"}, "los angeles": {"USA", "North America"}, "boston": {"USA", "North America"},
	"washington": {"USA", "North America"}, "miami": {"USA", "North America"}, "detroit": {"USA", "North America"},
	// Europe
	"amsterdam": {"Netherlands", "Europe"}, "paris": {"France", "Europe"}, "berlin": {"Germany", "Europe"},
	"munich": {"Germany", "Europe"}, "london": {"UK", "Europe"}, "barcelona": {"Spain", "Europe"},
	"madrid": {"Spain", "Europe"}, "vienna": {"Austria", "Europe"}, "brussels": {"Belgium", "Europe"},
	"stockholm": {"Sweden", "Europe"}, "dublin": {"Ireland", "Europe"}, "copenhagen": {"Denmark", "Europe"},
	"milan": {"Italy", "Europe"}, "rome": {"Italy", "Europe"}, "prague": {"Czech Republic", "Europe"},
	"warsaw": {"Poland", "Europe"}, "zurich": {"Switzerland", "Europe"}, "geneva": {"Switzerland", "Europe"},
	"lisbon": {"Portugal", "Europe"}, "oslo": {"Norway", "Europe"}, "helsinki": {"Finland", "Europe"},
	// Asia
	"shanghai": {"China", "Asia"}, "beijing": {"China", "Asia"}, "shenzhen": {"China", "Asia"},
	"tokyo": {"Japan", "Asia"}, "osaka": {"Japan", "Asia"}, "seoul": {"South Korea", "Asia"},
	"bangalore": {"India", "Asia"}, "bengaluru": {"India", "Asia"}, "mumbai": {"India", "Asia"},
	"hyderabad": {"India", "Asia"}, "delhi": {"India", "Asia"},
	"singapore": {"Singapore", "Asia Pacific"}, "sydney": {"Australia", "Asia Pacific"}, "melbourne": {"Australia", "Asia Pacific"},
	// Africa
	"nairobi": {"Kenya", "Africa"}, "cape town": {"South Africa", "Africa"}, "johannesburg": {"South Africa", "Africa"}, "lagos": {"Nigeria", "Africa"},
	// Middle East
	"dubai": {"UAE", "Middle East"}, "tel aviv": {"Israel", "Middle East"}, "istanbul": {"Turkey", "Middle East"},
}

// locationAliases maps full region names ↔ their short codes used in HubSpot
// email names, so expanding "North America" also matches "NA" emails and
// vice versa.
var locationAliases = map[string]string{
	"north america":  "NA",
	"south america":  "SA",
	"latin america":  "LATAM",
	"europe":         "EU",
	"asia pacific":   "APAC",
	"middle east":    "ME",
	"north africa":   "NA",
	"united states":  "US",
	"united kingdom": "UK",
}

var aliasReverse = func() map[string]string {
	m := map[string]string{}
	for k, v := range locationAliases {
		m[strings.ToLower(v)] = k
	}
	return m
}()

// knownLocationTerms is an ordered list of known location terms to scan for
// inside event names. Longer/more-specific phrases come first so "North
// America" matches before "America".
var knownLocationTerms = []string{
	"North America", "South America", "Latin America", "Asia Pacific", "Middle East",
	"Southeast Asia", "Central Asia",
	"APAC", "LATAM",
	"Europe", "Asia", "Africa",
	"Japan", "China", "India", "Germany", "France", "Netherlands", "Spain",
	"Austria", "Belgium", "Sweden", "Ireland", "Denmark", "Italy", "Poland",
	"Switzerland", "Portugal", "Norway", "Finland", "UK", "Canada", "Australia",
	"Singapore", "South Korea", "Korea", "Kenya", "Nigeria", "South Africa",
	"UAE", "Israel", "Turkey",
	"Tokyo", "Shanghai", "Beijing", "Seoul", "Toronto", "Vancouver",
	"Berlin", "Amsterdam", "Paris", "London", "Barcelona", "Vienna",
	"Brussels", "Stockholm", "Dublin", "Copenhagen", "Milan", "Prague",
	"Bengaluru", "Bangalore", "Mumbai", "Hyderabad", "Delhi", "Singapore",
	"Sydney", "Melbourne", "Nairobi", "Cape Town", "Dubai", "Chicago",
	"Seattle", "Austin", "Denver", "Atlanta", "New York", "San Francisco",
}

var wordRe = regexp.MustCompile(`\w+`)

// ExpandLocationWords returns the set of all words (and abbreviations) that
// should match emails for this location, e.g. "North America" → {"north",
// "america", "na"}, "EU" → {"eu", "europe"}.
func ExpandLocationWords(location string) map[string]struct{} {
	words := map[string]struct{}{}
	locLower := strings.ToLower(strings.TrimSpace(location))

	for _, w := range wordRe.FindAllString(locLower, -1) {
		words[strings.ToLower(w)] = struct{}{}
	}

	for phrase, code := range locationAliases {
		if strings.Contains(locLower, phrase) {
			words[strings.ToLower(code)] = struct{}{}
		}
	}

	if full, ok := aliasReverse[locLower]; ok {
		for _, w := range wordRe.FindAllString(full, -1) {
			words[strings.ToLower(w)] = struct{}{}
		}
	}

	return words
}

// LocationFallbackChain returns, for a scraped location string, an ordered
// list of word-sets to try when filtering HubSpot email candidates:
// [city_words, country_words, region_words]. The caller tries each level in
// order and stops at the first that yields >= 1 hit(s). If none match, the
// full pool is passed to AI.
func LocationFallbackChain(location string) []map[string]struct{} {
	if location == "" {
		return nil
	}

	locLower := strings.ToLower(strings.TrimSpace(location))

	// Parse "City, Country" or "City, State, Country" format — the country
	// is always the LAST comma-separated segment; middle segments
	// (state/province) are dropped since they aren't useful for matching
	// HubSpot email names.
	var cityPart, countryPart string
	if strings.Contains(locLower, ",") {
		parts := strings.Split(locLower, ",")
		for i := range parts {
			parts[i] = strings.TrimSpace(parts[i])
		}
		cityPart = parts[0]
		countryPart = parts[len(parts)-1]
	} else {
		cityPart = locLower
	}

	var chain []map[string]struct{}

	// Level 1 — city
	if cityWords := ExpandLocationWords(cityPart); len(cityWords) > 0 {
		chain = append(chain, cityWords)
	}

	// Resolve country + region from city lookup or parsed country
	var countryName, regionName string
	if info, ok := cityToCountry[cityPart]; ok {
		countryName, regionName = info.Country, info.Region
	} else if countryPart != "" {
		countryName = countryPart
		for _, info := range cityToCountry {
			if strings.ToLower(info.Country) == countryPart {
				regionName = info.Region
				break
			}
		}
	}

	// Level 2 — country (skip if same as city, e.g. "Japan" scraped as city)
	if countryName != "" && strings.ToLower(countryName) != cityPart {
		if countryWords := ExpandLocationWords(countryName); len(countryWords) > 0 {
			chain = append(chain, countryWords)
		}
	}

	// Level 3 — broad region
	if regionName != "" && strings.ToLower(regionName) != cityPart && strings.ToLower(regionName) != strings.ToLower(countryName) {
		if regionWords := ExpandLocationWords(regionName); len(regionWords) > 0 {
			chain = append(chain, regionWords)
		}
	}

	return chain
}

// ExtractLocationFromName scans an event name for a recognised location term
// and returns it. Longer phrases are checked first so "North America" wins
// over "America". Returns "" if nothing recognised is found.
func ExtractLocationFromName(eventName string) string {
	nameLower := strings.ToLower(eventName)
	for _, term := range knownLocationTerms {
		if strings.Contains(nameLower, strings.ToLower(term)) {
			return term
		}
	}
	return ""
}

func wordSetKey(ws map[string]struct{}) string {
	keys := make([]string, 0, len(ws))
	for k := range ws {
		keys = append(keys, k)
	}
	// Order doesn't affect set identity for dedup purposes as long as it's
	// deterministic per call; a simple concatenation is enough here since
	// we only use it as a dedup key within one BuildLocationChain call.
	joined := ""
	for _, k := range keys {
		joined += "|" + k
	}
	return joined
}

// BuildLocationChain builds the full location fallback chain by combining:
//  1. Location found in the event name (highest priority — matches HubSpot naming)
//  2. Scraped city/country/region (fallback)
//
// Duplicate word-sets are skipped so the same filter is never retried twice.
func BuildLocationChain(eventName, scrapedLocation string) []map[string]struct{} {
	seen := map[string]struct{}{}
	var chain []map[string]struct{}

	add := func(ws map[string]struct{}) {
		if len(ws) == 0 {
			return
		}
		key := wordSetKey(ws)
		if _, ok := seen[key]; ok {
			return
		}
		seen[key] = struct{}{}
		chain = append(chain, ws)
	}

	if nameLoc := ExtractLocationFromName(eventName); nameLoc != "" {
		for _, level := range LocationFallbackChain(nameLoc) {
			add(level)
		}
	}

	for _, level := range LocationFallbackChain(scrapedLocation) {
		add(level)
	}

	return chain
}

// FilterCandidatesByLocale restricts candidates to the SAME event locale
// (city, or name-embedded region/country) as the current event — e.g. a
// "MCP Dev Summit Bengaluru" plan must never reuse "MCP Dev Summit Toronto"
// history, and a "KubeCon + CloudNativeCon Europe" plan must never reuse the
// North America edition.
//
// Tries the single most specific locale level available (event-name-embedded
// location first, then scraped city/country/region — see BuildLocationChain)
// and returns the FIRST level with at least one match. Unlike a broadening
// cascade, this does NOT fall back to a broader region or an unfiltered
// cross-locale pool when the most specific level comes up empty: a locale
// mismatch means "no matching past event for this location", not "let the AI
// (or a keyword search) guess from every country".
//
// Returns (candidates, "no_location_data") unchanged only when neither the
// event name nor the scraped location contain any recognised locale at all —
// i.e. there's nothing to filter by, not that filtering was skipped.
//
// getName extracts the matchable name string from each candidate (mirroring
// Python's dict[name_key] access, generalized to work over any candidate
// type rather than requiring map[string]any).
func FilterCandidatesByLocale[T any](candidates []T, eventName, location string, getName func(T) string) ([]T, string) {
	chain := BuildLocationChain(eventName, location)
	if len(chain) == 0 {
		return candidates, "no_location_data"
	}

	for idx, locWords := range chain {
		var hits []T
		for _, c := range candidates {
			name := strings.ToLower(getName(c))
			for w := range locWords {
				if strings.Contains(name, w) {
					hits = append(hits, c)
					break
				}
			}
		}
		if len(hits) > 0 {
			keys := make([]string, 0, len(locWords))
			for w := range locWords {
				keys = append(keys, w)
			}
			return hits, "level_" + itoa(idx+1) + " (" + strings.Join(sortStrings(keys), ", ") + ")"
		}
	}

	return nil, "no_locale_match"
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var b []byte
	for i > 0 {
		b = append([]byte{byte('0' + i%10)}, b...)
		i /= 10
	}
	if neg {
		b = append([]byte{'-'}, b...)
	}
	return string(b)
}

func sortStrings(s []string) []string {
	out := append([]string(nil), s...)
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j-1] > out[j]; j-- {
			out[j-1], out[j] = out[j], out[j-1]
		}
	}
	return out
}

var stopWords = map[string]struct{}{
	"the": {}, "a": {}, "an": {}, "and": {}, "or": {}, "of": {}, "in": {}, "at": {}, "for": {},
	"on": {}, "to": {}, "is": {}, "lf": {}, "linux": {}, "foundation": {}, "events": {},
}

func keywords(text string) map[string]struct{} {
	out := map[string]struct{}{}
	for _, w := range wordRe.FindAllString(text, -1) {
		lw := strings.ToLower(w)
		if len(lw) <= 2 {
			continue
		}
		if _, stop := stopWords[lw]; stop {
			continue
		}
		out[lw] = struct{}{}
	}
	return out
}

func overlapCount(a, b map[string]struct{}) int {
	n := 0
	for w := range a {
		if _, ok := b[w]; ok {
			n++
		}
	}
	return n
}

// GetBrandEvents returns all BrandMap entries that share the same
// shortBrandName.
func GetBrandEvents(shortBrandName string) []BrandEntry {
	var out []BrandEntry
	for _, e := range brandMap {
		if e.ShortBrandName == shortBrandName {
			out = append(out, e)
		}
	}
	return out
}

// LookupEventBrand returns the best-matching BrandEntry for a scraped event
// name, or false if no entry scores >= 2 keyword overlaps.
func LookupEventBrand(eventName string) (BrandEntry, bool) {
	queryKw := keywords(eventName)
	if len(queryKw) == 0 {
		return BrandEntry{}, false
	}
	bestScore := 0
	var best BrandEntry
	found := false
	for _, entry := range brandMap {
		score := overlapCount(queryKw, keywords(entry.EventName))
		if score > bestScore {
			bestScore, best, found = score, entry, true
		}
	}
	if bestScore >= 2 {
		return best, found
	}
	return BrandEntry{}, false
}
