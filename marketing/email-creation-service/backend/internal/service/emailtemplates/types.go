// Package emailtemplates ports templates/email_templates.py verbatim —
// stage-matched messaging-variant templates plus the separate
// "best practice" B2B templates and their campaign-type mapping.
package emailtemplates

// Variant is one messaging-strategy variant within a funnel stage.
type Variant struct {
	ID        string
	Label     string
	Strategy  string
	Subject   string
	Preheader string
	Body      string
}

// Stage holds the variants for one funnel stage. A stage with no
// "variants" key in the Python source (only "Main Registration Push")
// has a nil Variants slice — its RawSubject/RawPreheader/RawBody are
// stored for fidelity but are unreachable through any of the query
// functions below, exactly as in Python (dict.get("variants", []) is
// empty, so get_template/get_template_variants both return None for it).
type Stage struct {
	Variants     []Variant
	RawSubject   string
	RawPreheader string
	RawBody      string
}

// VariantStrategy is the {id, label, strategy} projection returned by
// ListVariantStrategies.
type VariantStrategy struct {
	ID       string
	Label    string
	Strategy string
}

// BestPracticeTemplate is one B2B best-practice reference template.
type BestPracticeTemplate struct {
	Source          string
	QualityRating   int
	ConversionType  string
	SenderProfile   string
	ExpectedOpenPct float64
	ExpectedCTRPct  float64
	Template        BestPracticeVariant
}

// BestPracticeVariant is the actual template content of a
// BestPracticeTemplate.
type BestPracticeVariant struct {
	ID        string
	Label     string
	Strategy  string
	Subject   string
	Preheader string
	Body      string
}

// RecommendedTemplate is the legacy recommend_best_practice_template
// return shape — kept even though the Python function is "deprecated",
// since core/agent.py still calls it, per the no-behavior-change
// constraint.
type RecommendedTemplate struct {
	Key           string
	Template      *BestPracticeTemplate
	QualityRating int
	Source        string
}
