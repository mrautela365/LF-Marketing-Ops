package aiemailtemplates

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// emDashRe replicates strip_em_dashes' r"\s*[—–]\s*" -> ", ".
var emDashRe = regexp.MustCompile(`\s*[—–]\s*`)

// StripEmDashes ports strip_em_dashes — a safety net replacing stray
// em/en dashes with a comma, in case the model ignores the prompt rule.
// Only intended for AI Template variant output.
func StripEmDashes(text string) string {
	if text == "" {
		return text
	}
	return emDashRe.ReplaceAllString(text, ", ")
}

// MapFunnelStageToAITemplate ports map_funnel_stage_to_ai_template.
func MapFunnelStageToAITemplate(funnelStageName string) string {
	if v, ok := FunnelStageToAITemplate[funnelStageName]; ok {
		return v
	}
	return "CFP Launch"
}

// GetAITemplate ports get_ai_template.
func GetAITemplate(stage string) (*StageTemplate, bool) {
	t, ok := AIStageTemplates[stage]
	if !ok {
		return nil, false
	}
	return &t, true
}

// GetAllAITemplates ports get_all_ai_templates.
func GetAllAITemplates() map[string]StageTemplate {
	return AIStageTemplates
}

// GetAIStageNames ports get_ai_stage_names.
func GetAIStageNames() []string {
	names := make([]string, 0, len(AIStageOrder))
	names = append(names, AIStageOrder...)
	return names
}

// EventData is the input to FillTemplatePlaceholders, mirroring the
// event_data dict passed to fill_template_placeholders. Fields left as the
// zero value (empty string / nil / zero) fall back to the same defaults
// Python's event_data.get(key, default) uses.
type EventData struct {
	EventName               string
	Location                string
	Dates                   string
	Month                   string
	Year                    string
	EarlyPrice              string
	RegularPrice            string
	SavingsAmount           string
	DiscountPrice           string
	DiscountAmount          string
	PromoCode               string
	DeadlineDate            string
	DaysLeft                *int
	HoursLeft               *int
	TimeLeft                string
	AttendeeCount           string
	SessionCount            string
	SpeakerCount            string
	Topics                  []string
	RecipientSegment        string
	FirstName               string
	PastEvent               string
	FeaturedCompanies       string
	Date                    string
	DeadlineTime            string
	StartTime               string
	EndTime                 string
	Timezone                string
	VenueName               string
	Address                 string
	ParkingInfo             string
	TransitInfo             string
	SupportEmail            string
	CommunityLink           string
	CommunityCount          string
	NextEventDate           string
	RecordingsAvailableDate string
	TrackCount              *int
	TrackName               string
	SessionHighlight        string
	KeySessions             string
}

func orDefault2(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

// FillTemplatePlaceholders ports fill_template_placeholders — a sequential
// dict-ordered series of .replace() calls. Go map iteration order is
// randomized, so replacements are applied via the fixed placeholderOrder
// slice below rather than ranging over a map, to preserve Python's
// insertion-order-dependent replace sequence (relevant because some
// placeholder values could themselves, in principle, contain another
// placeholder's literal token).
func FillTemplatePlaceholders(templateText string, eventData EventData) string {
	topic1 := "open source"
	topic2 := "community"
	topic3 := "innovation"
	if len(eventData.Topics) > 0 {
		topic1 = eventData.Topics[0]
	}
	if len(eventData.Topics) > 1 {
		topic2 = eventData.Topics[1]
	}
	if len(eventData.Topics) > 2 {
		topic3 = eventData.Topics[2]
	}

	daysLeft := "X"
	if eventData.DaysLeft != nil {
		daysLeft = strconv.Itoa(*eventData.DaysLeft)
	}
	hoursLeft := "X"
	if eventData.HoursLeft != nil {
		hoursLeft = strconv.Itoa(*eventData.HoursLeft)
	}
	trackCount := "5"
	if eventData.TrackCount != nil {
		trackCount = strconv.Itoa(*eventData.TrackCount)
	}

	locationShort := strings.SplitN(eventData.Location, ",", 2)[0]

	date := eventData.Date
	if date == "" {
		date = orDefault2(eventData.Dates, "TBD")
	}

	availableDate := orDefault2(eventData.RecordingsAvailableDate, "[DATE]")

	replacements := []struct {
		placeholder, value string
	}{
		{"[EVENT_NAME]", orDefault2(eventData.EventName, "Event")},
		{"[LOCATION]", orDefault2(eventData.Location, "Location")},
		{"[DATES]", orDefault2(eventData.Dates, "TBD")},
		{"[LOCATION_SHORT]", locationShort},
		{"[MONTH]", eventData.Month},
		{"[YEAR]", eventData.Year},
		{"[EARLY_PRICE]", orDefault2(eventData.EarlyPrice, "$X")},
		{"[REGULAR_PRICE]", orDefault2(eventData.RegularPrice, "$Y")},
		{"[SAVINGS_AMOUNT]", orDefault2(eventData.SavingsAmount, "$Z")},
		{"[DISCOUNT_PRICE]", orDefault2(eventData.DiscountPrice, "$X")},
		{"[DISCOUNT_AMOUNT]", orDefault2(eventData.DiscountAmount, "$Z")},
		{"[PROMO_CODE]", orDefault2(eventData.PromoCode, "PROMO")},
		{"[DEADLINE]", orDefault2(eventData.DeadlineDate, "TBD")},
		{"[DEADLINE_DATE]", orDefault2(eventData.DeadlineDate, "TBD")},
		{"[DAYS_LEFT]", daysLeft},
		{"[HOURS_LEFT]", hoursLeft},
		{"[TIME_LEFT]", orDefault2(eventData.TimeLeft, "TBD")},
		{"[ATTENDEE_COUNT]", orDefault2(eventData.AttendeeCount, "1,000+")},
		{"[SESSION_COUNT]", orDefault2(eventData.SessionCount, "100+")},
		{"[SPEAKER_COUNT]", orDefault2(eventData.SpeakerCount, "50+")},
		{"[TOPICS]", strings.Join(eventData.Topics, ", ")},
		{"[TOPIC_1]", topic1},
		{"[TOPIC_2]", topic2},
		{"[TOPIC_3]", topic3},
		{"[SEGMENT]", orDefault2(eventData.RecipientSegment, "valued member")},
		{"[FIRST_NAME]", eventData.FirstName},
		{"[PAST_EVENT]", orDefault2(eventData.PastEvent, "past event")},
		{"[COMPANIES]", orDefault2(eventData.FeaturedCompanies, "leading companies")},
		{"[DATE]", date},
		{"[DEADLINE_TIME]", orDefault2(eventData.DeadlineTime, "11:59 PM")},
		{"[START_TIME]", orDefault2(eventData.StartTime, "9:00 AM")},
		{"[END_TIME]", orDefault2(eventData.EndTime, "5:00 PM")},
		{"[TIMEZONE]", orDefault2(eventData.Timezone, "PT")},
		{"[VENUE_NAME]", orDefault2(eventData.VenueName, "Venue")},
		{"[ADDRESS]", orDefault2(eventData.Address, "Address")},
		{"[PARKING_INFO]", orDefault2(eventData.ParkingInfo, "Info available on event site")},
		{"[TRANSIT_INFO]", orDefault2(eventData.TransitInfo, "Info available on event site")},
		{"[SUPPORT_EMAIL]", orDefault2(eventData.SupportEmail, "support@event.com")},
		{"[SLACK/DISCORD_LINK]", orDefault2(eventData.CommunityLink, "#")},
		{"[COMMUNITY_COUNT]", orDefault2(eventData.CommunityCount, "5,000+")},
		{"[NEXT_EVENT_DATE]", orDefault2(eventData.NextEventDate, "TBD")},
		{"[AVAILABLE_DATE]", availableDate},
		{"[TRACK_COUNT]", trackCount},
		{"[TRACK_NAME]", orDefault2(eventData.TrackName, "Track")},
		{"[SESSION_HIGHLIGHT]", orDefault2(eventData.SessionHighlight, "sessions")},
		{"[KEY_SESSIONS]", eventData.KeySessions},
	}

	result := templateText
	for _, r := range replacements {
		result = strings.ReplaceAll(result, r.placeholder, fmt.Sprint(r.value))
	}
	return result
}
