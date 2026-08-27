// Package aiemailtemplates ports templates/ai_email_templates.py verbatim —
// the "AI Template" variant (Variant A) prompt scaffolding, funnel-stage
// mapping, and placeholder filler.
package aiemailtemplates

// StageTemplate is one AI_STAGE_TEMPLATES entry.
type StageTemplate struct {
	StageName       string
	Purpose         string
	Timing          string
	Tone            string
	UrgencyLevel    int
	SubjectPattern  string
	SubjectExamples []string
	PreviewPattern  string
	ContentPrompt   string
	CTAStrategy     []string
	FooterNote      string
}
