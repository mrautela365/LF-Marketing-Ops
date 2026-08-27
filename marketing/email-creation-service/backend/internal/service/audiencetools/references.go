package audiencetools

import (
	"embed"
	"path/filepath"
)

// referencesFS embeds the 3 reference markdown files audience_tools.py's
// read_reference_file reads from disk (references/*.md) — copied verbatim
// from marketing/emailcreationskill/skills/hubspot-event-list-builder/references/.
//
//go:embed references/*.md
var referencesFS embed.FS

// readReferenceFile ports read_reference_file. filepath.Base mirrors
// Python's Path(filename).name — strips any directory component so a
// caller-supplied path can't escape the references/ directory.
func readReferenceFile(filename string) map[string]any {
	safe := filepath.Base(filename)
	b, err := referencesFS.ReadFile("references/" + safe)
	if err != nil {
		return map[string]any{"error": safe + " not found in references/"}
	}
	return map[string]any{"filename": safe, "content": string(b)}
}
