package audiencetools

import (
	"regexp"
	"strings"
)

var masterListIDPatterns = []*regexp.Regexp{
	// lf-event-studio: "🏆 Master list created — ID: 12345 — https://..."
	regexp.MustCompile(`🏆[^\n]*?ID:\s*(\d+)`),
	// RULE 10/RULE 6 reuse-check: "🔁 [Master list name] updated in place — ID: 12345 — https://..."
	regexp.MustCompile(`(?i)🔁[^\n]*?master[^\n]*?ID:\s*(\d+)`),
	// CLI explicit marker: "MASTER_LIST_ID: 12345"
	regexp.MustCompile(`MASTER_LIST_ID:\s*(\d+)`),
	// HubSpot list URLs — both objectLists and contacts/<portal>/lists/ formats
	regexp.MustCompile(`(?i)master[^\n]{0,400}objectLists/(\d+)`),
	regexp.MustCompile(`(?i)objectLists/(\d+)[^\n]{0,400}master`),
	regexp.MustCompile(`(?i)master[^\n]{0,400}/lists/(\d+)`),
	regexp.MustCompile(`(?i)/lists/(\d+)[^\n]{0,400}master`),
	// Prose patterns: "Master Audience list — ID: 12345" / "listId: 12345" near "master"
	regexp.MustCompile(`[Mm]aster[^\n]{0,80}[Ii][Dd][:\s]+(\d{4,8})`),
	regexp.MustCompile(`[Mm]aster [Aa]udience[^\n]{0,80}\b(\d{5,8})\b`),
	regexp.MustCompile(`[Mm]aster[^\n]{0,80}[Ll]ist[^\n]{0,80}\b(\d{5,8})\b`),
	regexp.MustCompile(`listId["']?\s*:\s*["']?(\d{4,8})["']?[^\n]{0,200}[Mm]aster`),
	regexp.MustCompile(`[Mm]aster[^\n]{0,200}listId["']?\s*:\s*["']?(\d{4,8})`),
	regexp.MustCompile(`[Mm]aster[^\n]{0,200}list[_ ]id["']?\s*[:=]\s*["']?(\d{4,8})`),
	regexp.MustCompile(`[Cc]reated[^\n]{0,80}[Mm]aster[^\n]{0,80}\b(\d{5,8})\b`),
}

var masterListIDLastResort = regexp.MustCompile(`(?:objectLists|/lists)/(\d+)`)

// ExtractMasterListID ports extract_master_list_id verbatim: parses the
// master list ID from accumulated agent output, trying each pattern in
// order and falling back to "the last list ID mentioned anywhere" — the
// master list is always built last, per RULE 4.
func ExtractMasterListID(text string) string {
	for _, pat := range masterListIDPatterns {
		if m := pat.FindStringSubmatch(text); m != nil {
			return m[1]
		}
	}
	allIDs := masterListIDLastResort.FindAllStringSubmatch(text, -1)
	if len(allIDs) > 0 {
		return allIDs[len(allIDs)-1][1]
	}
	return ""
}

var suppressionSectionPattern = regexp.MustCompile(`(?is)##\s*SUPPRESSION LISTS(.*?)(?:##\s*FLAGGED FOR REVIEW|$)`)

// SuppressionListRow mirrors the {name, list_id, url} dicts
// extract_suppression_lists returns.
type SuppressionListRow struct {
	Name   string `json:"name"`
	ListID string `json:"list_id"`
	URL    string `json:"url"`
}

// ExtractSuppressionLists ports extract_suppression_lists verbatim: finds
// the "## SUPPRESSION LISTS" markdown section (up to the next "##" heading
// or end of text) and parses its "| name | list_id | url |" table rows,
// skipping separator rows ("---") and a header row named "list name"/"name".
func ExtractSuppressionLists(text string) []SuppressionListRow {
	sectionM := suppressionSectionPattern.FindStringSubmatch(text)
	if sectionM == nil {
		return []SuppressionListRow{}
	}
	section := sectionM[1]
	var rows []SuppressionListRow
	for _, line := range strings.Split(section, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "|") || strings.Contains(line, "---") {
			continue
		}
		trimmed := strings.Trim(line, "|")
		parts := strings.Split(trimmed, "|")
		cols := make([]string, len(parts))
		for i, c := range parts {
			cols[i] = strings.TrimSpace(c)
		}
		if len(cols) >= 2 && cols[0] != "" &&
			strings.ToLower(cols[0]) != "list name" && strings.ToLower(cols[0]) != "name" {
			row := SuppressionListRow{Name: cols[0], ListID: cols[1]}
			if len(cols) > 2 {
				row.URL = cols[2]
			}
			rows = append(rows, row)
		}
	}
	if rows == nil {
		return []SuppressionListRow{}
	}
	return rows
}
