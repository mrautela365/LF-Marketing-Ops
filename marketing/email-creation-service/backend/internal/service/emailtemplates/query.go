package emailtemplates

// GetTemplate ports get_template. If variantID is nil, returns the first
// variant. Returns (nil, false) if the stage or variant isn't found — this
// includes stages with no Variants (e.g. "Main Registration Push"), exactly
// as Python's stage.get("variants", []) empty-list short-circuit does.
func GetTemplate(stageName string, variantID *string) (*Variant, bool) {
	stage, ok := StageTemplates[stageName]
	if !ok {
		return nil, false
	}
	if len(stage.Variants) == 0 {
		return nil, false
	}
	if variantID == nil {
		v := stage.Variants[0]
		return &v, true
	}
	for _, v := range stage.Variants {
		if v.ID == *variantID {
			return &v, true
		}
	}
	return nil, false
}

// GetTemplateVariants ports get_template_variants.
func GetTemplateVariants(stageName string) ([]Variant, bool) {
	stage, ok := StageTemplates[stageName]
	if !ok {
		return nil, false
	}
	return stage.Variants, true
}

// GetTemplateVariant ports get_template_variant.
func GetTemplateVariant(stageName, variantID string) (*Variant, bool) {
	variants, ok := GetTemplateVariants(stageName)
	if !ok || len(variants) == 0 {
		return nil, false
	}
	for _, v := range variants {
		if v.ID == variantID {
			return &v, true
		}
	}
	return nil, false
}

// ListVariantStrategies ports list_variant_strategies.
func ListVariantStrategies(stageName string) ([]VariantStrategy, bool) {
	variants, ok := GetTemplateVariants(stageName)
	if !ok || len(variants) == 0 {
		return nil, false
	}
	out := make([]VariantStrategy, 0, len(variants))
	for _, v := range variants {
		out = append(out, VariantStrategy{ID: v.ID, Label: v.Label, Strategy: v.Strategy})
	}
	return out, true
}

// GetAllStageNames ports get_all_stage_names. Map iteration order in Go is
// randomized, unlike Python's insertion-ordered dict.keys() — callers that
// need the Python ordering must use StageOrder instead.
func GetAllStageNames() []string {
	names := make([]string, 0, len(StageTemplates))
	for _, name := range StageOrder {
		names = append(names, name)
	}
	return names
}

// StageOrder preserves STAGE_TEMPLATES' Python insertion order, since
// get_all_stage_names() relies on dict key order.
var StageOrder = []string{
	"Event Announcement",
	"CFP Launch",
	"Registration Launch",
	"Co-Located Events + CFP Reminder",
	"DEI & Travel Fund",
	"Schedule Announcement",
	"Main Registration Push",
	"Final Countdown",
	"Event Week",
	"Thank You + Survey",
	"Content & Recordings Release",
	"Next Event CFP Teaser",
	"Community Nurture",
}

// GetBestPracticeTemplate ports get_best_practice_template.
func GetBestPracticeTemplate(templateKey string) (*BestPracticeTemplate, bool) {
	t, ok := BestPracticeTemplates[templateKey]
	if !ok {
		return nil, false
	}
	return &t, true
}

// GetAllBestPracticeTemplates ports get_all_best_practice_templates.
func GetAllBestPracticeTemplates() map[string]BestPracticeTemplate {
	return BestPracticeTemplates
}

// GetRecommendedTemplateForCampaignType ports get_recommended_template_for_campaign_type.
func GetRecommendedTemplateForCampaignType(campaignType string) (*BestPracticeTemplate, bool) {
	key, ok := TemplateTypeMapping[campaignType]
	if !ok {
		return nil, false
	}
	return GetBestPracticeTemplate(key)
}

// RecommendBestPracticeTemplate ports recommend_best_practice_template — the
// "deprecated" legacy function core/agent.py still calls, kept per the
// no-behavior-change constraint.
func RecommendBestPracticeTemplate(campaignType string) (*RecommendedTemplate, bool) {
	key, ok := TemplateTypeMapping[campaignType]
	if !ok {
		return nil, false
	}
	tmpl, found := BestPracticeTemplates[key]
	out := &RecommendedTemplate{Key: key}
	if found {
		out.Template = &tmpl
		out.QualityRating = tmpl.QualityRating
		out.Source = tmpl.Source
	}
	return out, true
}
