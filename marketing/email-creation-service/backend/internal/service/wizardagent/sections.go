package wizardagent

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// stripPatterns ports _STRIP_PATTERNS / _STRIP_RE — regexes matching
// system-injected throwaway preview content (sponsor headings, footers,
// unsubscribe links, physical address blocks, "view in browser" links) that
// must never leak into a *new* generated email even when it was learned
// from a reference email's already-system-injected HTML.
var stripPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?is)<h[1-6][^>]*>\s*Thank You to Our Sponsors!?\s*</h[1-6]>`),
	regexp.MustCompile(`(?is)<div[^>]*class="[^"]*footer[^"]*"[^>]*>.*?</div>`),
	regexp.MustCompile(`(?is)unsubscribe`),
	regexp.MustCompile(`(?is)view (this email )?in (your )?browser`),
	regexp.MustCompile(`(?is)\{\{\s*unsubscribe_link\s*\}\}`),
	regexp.MustCompile(`(?is)548 Market St[^<]*San Francisco[^<]*`),
	regexp.MustCompile(`(?is)The Linux Foundation\s*[·|]\s*548 Market St`),
}

// stripSystemContent ports _strip_system_content — a regex-based scrub of
// throwaway preview HTML. This is intentionally cruder than
// dropSystemSections (which drops whole array entries from the real
// `sections` payload sent to HubSpot): _strip_system_content only ever
// touches disposable preview strings, never the structured content actually
// staged.
func stripSystemContent(html string) string {
	out := html
	for _, re := range stripPatterns {
		out = re.ReplaceAllString(out, "")
	}
	return out
}

// sectionForbiddenPhrases ports _SECTION_FORBIDDEN_PHRASES — lowercase
// substrings that, if found anywhere in a rich_text section's text/html,
// mark the whole section as system-injected and droppable.
var sectionForbiddenPhrases = []string{
	"thank you to our sponsors",
	"unsubscribe",
	"view in browser",
	"view this email in your browser",
	"548 market st",
	"the linux foundation is a non-profit",
	"all rights reserved",
	"subscription center",
	"you are receiving this email because",
	"manage your email preferences",
	"linux foundation events",
}

// sectionForbiddenExact ports _SECTION_FORBIDDEN_EXACT — strings that only
// mark a section forbidden when they are the section's ENTIRE (trimmed,
// lowercased) content, so a real section that merely mentions e.g. "gold
// standard support" is not falsely dropped.
var sectionForbiddenExact = map[string]bool{
	"gold":         true,
	"silver":       true,
	"bronze":       true,
	"platinum":     true,
	"sponsors":     true,
	"our sponsors": true,
	"thank you":    true,
	"sponsor":      true,
}

var htmlTagRe = regexp.MustCompile(`<[^>]+>`)

func sectionPlainText(s model.EmailSection) string {
	text, _ := s["text"].(string)
	html, _ := s["html"].(string)
	combined := text
	if html != "" {
		combined += " " + htmlTagRe.ReplaceAllString(html, " ")
	}
	return strings.TrimSpace(combined)
}

// dropSystemSections ports _drop_system_sections — drops rich_text sections
// matching a forbidden phrase, an exact-match forbidden string, or a
// sponsor-name mention, from the real `sections` array before it is sent to
// HubSpot (as opposed to stripSystemContent, which only ever touches
// disposable preview HTML).
func dropSystemSections(sections []model.EmailSection, sponsors []model.Sponsor) []model.EmailSection {
	out := make([]model.EmailSection, 0, len(sections))
	for _, s := range sections {
		sectionType, _ := s["type"].(string)
		if sectionType != "rich_text" {
			out = append(out, s)
			continue
		}

		plain := sectionPlainText(s)
		lower := strings.ToLower(plain)

		if sectionForbiddenExact[lower] {
			continue
		}

		dropped := false
		for _, phrase := range sectionForbiddenPhrases {
			if strings.Contains(lower, phrase) {
				dropped = true
				break
			}
		}
		if !dropped {
			for _, sp := range sponsors {
				if sp.Name != "" && strings.Contains(lower, strings.ToLower(sp.Name)) {
					dropped = true
					break
				}
			}
		}
		if dropped {
			continue
		}
		out = append(out, s)
	}
	return out
}

// sectionsToHTML ports _sections_to_html — deterministic (no LLM call)
// rendering of the structured `sections` array into a single HTML body,
// used both for the section-editor preview and the final email HTML.
// btnColor defaults to "#04c0da" exactly as Python's default parameter.
func sectionsToHTML(sections []model.EmailSection, btnColor string, sponsors []model.Sponsor) string {
	if btnColor == "" {
		btnColor = "#04c0da"
	}

	var b strings.Builder
	for _, s := range sections {
		sectionType, _ := s["type"].(string)
		switch sectionType {
		case "rich_text":
			html, _ := s["html"].(string)
			fmt.Fprintf(&b, `<div style="padding: 16px 24px;">%s</div>`, html)

		case "button":
			text, _ := s["text"].(string)
			dest, _ := s["destination"].(string)
			if dest == "" {
				dest, _ = s["url"].(string)
			}
			bg, _ := s["background_color"].(string)
			if bg == "" {
				bg, _ = s["color"].(string)
			}
			if bg == "" {
				bg = btnColor
			}
			fmt.Fprintf(&b, `<table role="presentation" style="margin: 16px auto;"><tr><td style="border-radius: 4px; background-color: %s;">`+
				`<a href="%s" style="display: inline-block; padding: 12px 28px; color: #ffffff; font-weight: bold; text-decoration: none; border-radius: 4px;">%s</a>`+
				`</td></tr></table>`, bg, dest, text)

		case "image":
			src, _ := s["src"].(string)
			alt, _ := s["alt"].(string)
			fmt.Fprintf(&b, `<div style="text-align: center; padding: 8px 0;"><img src="%s" alt="%s" style="max-width: 100%%; height: auto;"></div>`, src, alt)

		case "divider":
			b.WriteString(`<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 16px 24px;">`)

		default:
			// Unknown section types pass through untouched — matches Python's
			// "else: continue" (no output emitted, no error raised).
		}
	}

	b.WriteString(sponsorRowsHTML(sponsors))
	return b.String()
}

// sponsorRowsHTML ports the sponsor-logo-rendering tail of
// _sections_to_html: up to two tiers of sponsor logos (tier1 rendered 3-per
// row at height=60/max-width=180, tier2 rendered 2-per-row at
// height=45/max-width=140), preceded by an <hr> divider and a "Thank You to
// Our Sponsors!" heading, only emitted when at least one sponsor is present.
func sponsorRowsHTML(sponsors []model.Sponsor) string {
	if len(sponsors) == 0 {
		return ""
	}

	var tier1, tier2 []model.Sponsor
	for _, sp := range sponsors {
		if sp.Tier == "tier2" {
			tier2 = append(tier2, sp)
		} else {
			tier1 = append(tier1, sp)
		}
	}

	renderRow := func(row []model.Sponsor, height, maxWidth int) string {
		var cells strings.Builder
		for _, sp := range row {
			fmt.Fprintf(&cells, `<td style="padding: 8px; text-align: center;"><img src="%s" alt="%s" style="height: %dpx; max-width: %dpx;"></td>`, sp.Logo, sp.Name, height, maxWidth)
		}
		return `<tr>` + cells.String() + `</tr>`
	}

	chunk := func(sponsors []model.Sponsor, size int) [][]model.Sponsor {
		var chunks [][]model.Sponsor
		for i := 0; i < len(sponsors); i += size {
			end := i + size
			if end > len(sponsors) {
				end = len(sponsors)
			}
			chunks = append(chunks, sponsors[i:end])
		}
		return chunks
	}

	var b strings.Builder
	b.WriteString(`<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 24px;">`)
	b.WriteString(`<div style="text-align: center; padding: 8px 0; font-weight: bold;">Thank You to Our Sponsors!</div>`)
	b.WriteString(`<table role="presentation" style="width: 100%; margin: 0 auto;">`)
	for _, row := range chunk(tier1, 3) {
		b.WriteString(renderRow(row, 60, 180))
	}
	for _, row := range chunk(tier2, 2) {
		b.WriteString(renderRow(row, 45, 140))
	}
	b.WriteString(`</table>`)
	return b.String()
}

// buildEmailPreview ports _build_email_preview — the full standalone
// preview HTML document (DOCTYPE/meta/CSS-guard head, banner row, body,
// pre-footer divider, social-icons row, "sent by" text, LF address block,
// and the {{ unsubscribe_link }} Subscription Center placeholder HubSpot
// fills in at send time).
func buildEmailPreview(bannerURL, bodyHTML, eventURL, eventName string) string {
	bannerHTML := `<div style="background-color:#003366;height:120px;"></div>`
	if bannerURL != "" {
		if eventURL != "" {
			bannerHTML = fmt.Sprintf(`<a href="%s"><img src="%s" alt="%s" style="width:100%%; display:block;"></a>`, eventURL, bannerURL, eventName)
		} else {
			bannerHTML = fmt.Sprintf(`<img src="%s" alt="%s" style="width:100%%; display:block;">`, bannerURL, eventName)
		}
	}

	return fmt.Sprintf(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f4f4f4; }
  table { border-collapse: collapse; }
  a { color: #04c0da; }
</style>
</head>
<body>
<table role="presentation" width="100%%" style="max-width: 640px; margin: 0 auto; background-color: #ffffff;">
<tr><td>%s</td></tr>
<tr><td>%s</td></tr>
<tr><td>
<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 24px;">
<table role="presentation" style="margin: 0 auto;">
<tr>
<td style="padding: 4px;"><a href="https://lfx.linuxfoundation.org" style="display:inline-block;width:32px;height:32px;border-radius:50%%;background-color:#003366;text-align:center;color:#ffffff;text-decoration:none;line-height:32px;">LFX</a></td>
<td style="padding: 4px;"><a href="https://twitter.com/linuxfoundation" style="display:inline-block;width:32px;height:32px;border-radius:50%%;background-color:#000000;text-align:center;color:#ffffff;text-decoration:none;line-height:32px;">X</a></td>
<td style="padding: 4px;"><a href="https://www.linkedin.com/company/the-linux-foundation" style="display:inline-block;width:32px;height:32px;border-radius:50%%;background-color:#0077b5;text-align:center;color:#ffffff;text-decoration:none;line-height:32px;">in</a></td>
<td style="padding: 4px;"><a href="https://www.facebook.com/thelinuxfoundation" style="display:inline-block;width:32px;height:32px;border-radius:50%%;background-color:#1877f2;text-align:center;color:#ffffff;text-decoration:none;line-height:32px;">f</a></td>
</tr>
</table>
<div style="text-align:center; color:#888888; font-size:12px; padding: 16px;">
  Sent by The Linux Foundation<br>
  548 Market St, PMB 57274, San Francisco, CA 94104<br>
  <a href="{{ unsubscribe_link }}">Subscription Center</a>
</div>
</td></tr>
</table>
</body>
</html>`, bannerHTML, bodyHTML)
}
