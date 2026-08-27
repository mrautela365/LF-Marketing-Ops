// Package stagedetector maps an event date to its position in the 13-stage
// marketing journey, porting utils/stage_detector.py. Pure/deterministic —
// no external calls.
package stagedetector

import (
	_ "embed"
	"encoding/json"
	"regexp"
	"strconv"
	"strings"
	"time"
)

//go:embed data/marketing_journey_stages.json
var journeyJSON []byte

// Journey is one entry of MARKETING_JOURNEY — detailed stage guidance keyed
// by the STAGES name field. Source of truth: data/marketing_journey_stages.json
// (byte-for-byte copy of the Python service's templates/marketing_journey_stages.json).
type Journey struct {
	StageNumber           int               `json:"stage_number"`
	Timeline              string            `json:"timeline"`
	MarketingStrategy     string            `json:"marketing_strategy"`
	ContentIdeas          []string          `json:"content_ideas"`
	IndustryBestPractices map[string]string `json:"industry_best_practices"`
}

var marketingJourney map[string]Journey

func init() {
	if err := json.Unmarshal(journeyJSON, &marketingJourney); err != nil {
		panic("stagedetector: failed to parse embedded marketing_journey_stages.json: " + err.Error())
	}
}

type stage struct {
	Name      string
	Funnel    string
	EmailType string
	Min       int
	Max       int
}

var stages = []stage{
	{"Event Announcement", "TOFU", "Invite", 105, 9999},
	{"CFP Launch", "TOFU", "Invite", 98, 104},
	{"Registration Launch", "TOFU", "Invite", 84, 97},
	{"Co-Located Events + CFP Reminder", "MOFU", "Invite", 70, 83},
	{"DEI & Travel Fund", "MOFU", "Invite", 63, 69},
	{"Schedule Announcement", "MOFU", "Invite", 49, 62},
	{"Main Registration Push", "BOFU", "Invite", 35, 48},
	{"Final Countdown", "BOFU", "Invite", 14, 34},
	{"Event Week", "BOFU", "Invite", 0, 13},
	{"Thank You + Survey", "FOLLOW-UP", "Invite", -3, -1},
	{"Content & Recordings Release", "FOLLOW-UP", "Invite", -17, -4},
	{"Next Event CFP Teaser", "FOLLOW-UP", "Invite", -31, -18},
	{"Community Nurture", "FOLLOW-UP", "Invite", -9999, -32},
}

var stageGoals = map[string]string{
	"Event Announcement":               "Generate excitement, announce key details, drive awareness",
	"CFP Launch":                       "Invite speakers to submit proposals, emphasize visibility and impact",
	"Registration Launch":              "Drive early registrations, highlight early-bird pricing and value",
	"Co-Located Events + CFP Reminder": "Highlight co-located events, create urgency around CFP deadline",
	"DEI & Travel Fund":                "Promote DEI scholarships and travel funding opportunities",
	"Schedule Announcement":            "Highlight keynotes and sessions, build anticipation, drive ticket purchases",
	"Main Registration Push":           "Strong registration CTA with social proof, speaker highlights, urgency",
	"Final Countdown":                  "Urgency-driven messaging — registration closes very soon",
	"Event Week":                       "Logistics, venue details, what to expect, build on-site excitement",
	"Thank You + Survey":               "Thank attendees for joining, gather feedback via post-event survey",
	"Content & Recordings Release":     "Share session recordings, slides, and key community takeaways",
	"Next Event CFP Teaser":            "Tease upcoming event dates/location, invite early speaker interest",
	"Community Nurture":                "Stay connected, share community updates, preview upcoming events",
}

var ctaLabels = map[string]string{
	"Event Announcement":               "Learn More",
	"CFP Launch":                       "Submit Your Proposal",
	"Registration Launch":              "Register Now",
	"Co-Located Events + CFP Reminder": "Register & Submit CFP",
	"DEI & Travel Fund":                "Apply for Funding",
	"Schedule Announcement":            "View the Schedule",
	"Main Registration Push":           "Register Now",
	"Final Countdown":                  "Register Before It's Too Late",
	"Event Week":                       "View Event Details",
	"Thank You + Survey":               "Take the Survey",
	"Content & Recordings Release":     "Watch the Sessions",
	"Next Event CFP Teaser":            "Stay Informed",
	"Community Nurture":                "Stay Connected",
}

var funnelColors = map[string]string{
	"TOFU":      "#16a34a",
	"MOFU":      "#d97706",
	"BOFU":      "#dc2626",
	"FOLLOW-UP": "#7c3aed",
}

const monthRe = `(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?` +
	`|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)`

var (
	isoDateRe    = regexp.MustCompile(`^(\d{4})[-/](\d{1,2})[-/](\d{1,2})`)
	rangeRe      = regexp.MustCompile(`(?i)^(` + monthRe + `)[\s,]+\d{1,2}(?:st|nd|rd|th)?[\s,\x{2013}\-]+(\d{1,2})(?:st|nd|rd|th)?[\s,]+(20\d{2})`)
	rangeStripRe = regexp.MustCompile(`(\b\w+ \d+)[\x{2013}-]\d+`)
	ordinalRe    = regexp.MustCompile(`(\d+)(?:st|nd|rd|th)`)
)

var dateFormats = []string{"January 2, 2006", "January 2 2006", "Jan 2, 2006", "Jan 2 2006"}

// daysInMonth mirrors Python's strict calendar validation (constructing a
// datetime with an out-of-range day, e.g. Feb 30, raises and the string is
// discarded) — unlike time.Date, which silently normalizes overflow days
// into the next month.
func daysInMonth(year, month int) int {
	return time.Date(year, time.Month(month)+1, 0, 0, 0, 0, 0, time.UTC).Day()
}

// parseAllDates parses scraped date strings into time.Time values, including
// BOTH ends of any range found in a single string (e.g. "June 15-16, 2026" →
// [June 15, June 16]), so callers can derive the full event date range, not
// just the earliest day.
func parseAllDates(dateStrings []string) []time.Time {
	var parsed []time.Time
	for _, raw := range dateStrings {
		ds := strings.TrimSpace(raw)
		if ds == "" {
			continue
		}

		if m := isoDateRe.FindStringSubmatch(ds); m != nil {
			y, _ := strconv.Atoi(m[1])
			mo, _ := strconv.Atoi(m[2])
			d, _ := strconv.Atoi(m[3])
			if mo >= 1 && mo <= 12 && d >= 1 && d <= daysInMonth(y, mo) {
				parsed = append(parsed, time.Date(y, time.Month(mo), d, 0, 0, 0, 0, time.UTC))
			}
			continue
		}

		// Capture the end day of an inline range ("June 15-16, 2026") before
		// it gets stripped below, so the range's last day isn't lost.
		rangeMatch := rangeRe.FindStringSubmatch(ds)

		// Normalize ranges like "June 15-16, 2026" → "June 15, 2026"
		dsClean := rangeStripRe.ReplaceAllString(ds, "$1")
		// Remove ordinal suffixes: 1st, 2nd, 3rd, 15th → 1, 2, 3, 15
		dsClean = ordinalRe.ReplaceAllString(dsClean, "$1")

		for _, format := range dateFormats {
			if t, err := time.Parse(format, dsClean); err == nil {
				parsed = append(parsed, t)
				break
			}
		}

		if rangeMatch != nil {
			month, endDay, year := rangeMatch[1], rangeMatch[2], rangeMatch[3]
			for _, format := range []string{"January 2, 2006", "Jan 2, 2006"} {
				if t, err := time.Parse(format, month+" "+endDay+", "+year); err == nil {
					parsed = append(parsed, t)
					break
				}
			}
		}
	}
	return parsed
}

// ParseEventDate parses scraped date strings and returns the earliest found.
func ParseEventDate(dateStrings []string) (time.Time, bool) {
	parsed := parseAllDates(dateStrings)
	if len(parsed) == 0 {
		return time.Time{}, false
	}
	min := parsed[0]
	for _, t := range parsed[1:] {
		if t.Before(min) {
			min = t
		}
	}
	return min, true
}

// ParseEventEndDate parses scraped date strings and returns the latest found
// (the last day of the event, when the source gives a multi-day range).
func ParseEventEndDate(dateStrings []string) (time.Time, bool) {
	parsed := parseAllDates(dateStrings)
	if len(parsed) == 0 {
		return time.Time{}, false
	}
	max := parsed[0]
	for _, t := range parsed[1:] {
		if t.After(max) {
			max = t
		}
	}
	return max, true
}

// FormatEventDateRange formats a start/end date pair as a human-readable
// range, e.g. "September 7–9, 2026" or "August 30 – September 1, 2026". Falls
// back to a single date when there is no distinct end date.
func FormatEventDateRange(start time.Time, end time.Time, hasEnd bool) string {
	if !hasEnd || !end.After(start) {
		return start.Format("January 2, 2006")
	}
	if start.Year() == end.Year() && start.Month() == end.Month() {
		return start.Format("January") + " " + strconv.Itoa(start.Day()) + "–" + strconv.Itoa(end.Day()) + ", " + strconv.Itoa(start.Year())
	}
	if start.Year() == end.Year() {
		return start.Format("January") + " " + strconv.Itoa(start.Day()) + " – " + end.Format("January") + " " + strconv.Itoa(end.Day()) + ", " + strconv.Itoa(start.Year())
	}
	return start.Format("January") + " " + strconv.Itoa(start.Day()) + ", " + strconv.Itoa(start.Year()) +
		" – " + end.Format("January") + " " + strconv.Itoa(end.Day()) + ", " + strconv.Itoa(end.Year())
}

// Result is the campaign stage dict returned by DetectStage, matching
// detect_stage()'s Python return shape field-for-field.
type Result struct {
	Name                  string
	Funnel                string
	EmailType             string
	DaysToEvent           *int
	Goal                  string
	CTALabel              string
	EventDateStr          string
	Color                 string
	StageNumber           *int
	Timeline              string
	MarketingStrategy     string
	ContentIdeas          []string
	IndustryBestPractices map[string]string
}

func unknownResult() Result {
	return Result{
		Name:      "Unknown",
		Funnel:    "TOFU",
		EmailType: "Invite",
		Goal:      "Promote the event and drive registrations",
		CTALabel:  "Register Now",
		Color:     "#6b7280",
	}
}

func buildResult(name, funnel, emailType string, days int, eventDateStr string) Result {
	mj := marketingJourney[name]
	d := days
	r := Result{
		Name:                  name,
		Funnel:                funnel,
		EmailType:             emailType,
		DaysToEvent:           &d,
		Goal:                  stageGoals[name],
		CTALabel:              ctaLabels[name],
		EventDateStr:          eventDateStr,
		Color:                 funnelColors[funnel],
		Timeline:              mj.Timeline,
		MarketingStrategy:     mj.MarketingStrategy,
		ContentIdeas:          mj.ContentIdeas,
		IndustryBestPractices: mj.IndustryBestPractices,
	}
	if r.CTALabel == "" {
		r.CTALabel = "Learn More"
	}
	if mj.StageNumber != 0 {
		sn := mj.StageNumber
		r.StageNumber = &sn
	}
	return r
}

// DetectStage returns the campaign stage for a list of scraped event date
// strings, porting utils/stage_detector.py's detect_stage.
func DetectStage(eventDates []string) Result {
	eventDate, ok := ParseEventDate(eventDates)
	if !ok {
		return unknownResult()
	}

	eventEndDate, hasEnd := ParseEventEndDate(eventDates)
	eventDateStr := FormatEventDateRange(eventDate, eventEndDate, hasEnd)

	// Matches Python's date.today(), which uses the server's local
	// timezone rather than UTC.
	now := time.Now()
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
	days := int(eventDate.Sub(today).Hours() / 24)

	for _, s := range stages {
		if s.Min <= days && days <= s.Max {
			return buildResult(s.Name, s.Funnel, s.EmailType, days, eventDateStr)
		}
	}

	// Fallback for edge cases
	name, funnel := "Event Announcement", "TOFU"
	if days < 0 {
		name, funnel = "Community Nurture", "FOLLOW-UP"
	}
	return buildResult(name, funnel, "Invite", days, eventDateStr)
}
