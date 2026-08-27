package dispatch

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
	"golang.org/x/net/html"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

const scraperUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

// WebScraper implements domain.EventPageScraper over plain net/http +
// goquery, porting utils/content_tools.py.
type WebScraper struct {
	client *http.Client

	// googleServiceAccountFile is GOOGLE_SERVICE_ACCOUNT_FILE — when unset,
	// PrepareContent on a Google Doc URL fails the same way Python's
	// _fetch_google_doc does when the env var is unset.
	googleServiceAccountFile string
}

var _ domain.EventPageScraper = (*WebScraper)(nil)

// sliceUpTo returns sel.Slice(0, n), clamped to sel's actual length.
// goquery's Slice panics (like a raw Go slice expression) if the end index
// exceeds the selection's length, which real event pages hit constantly —
// e.g. a page with only one <h1> panics on Slice(0, 5). Every fixed-size cap
// applied to a live DOM selection in this file must go through this helper
// instead of calling .Slice directly.
func sliceUpTo(sel *goquery.Selection, n int) *goquery.Selection {
	if l := sel.Length(); l < n {
		n = l
	}
	return sel.Slice(0, n)
}

func NewWebScraper(googleServiceAccountFile string) *WebScraper {
	return &WebScraper{
		client:                   &http.Client{Timeout: 15 * time.Second},
		googleServiceAccountFile: googleServiceAccountFile,
	}
}

func (w *WebScraper) get(rawURL string, timeout time.Duration) (*goquery.Document, string, error) {
	req, err := http.NewRequest(http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, "", err
	}
	req.Header.Set("User-Agent", scraperUserAgent)

	client := w.client
	if timeout > 0 && timeout != w.client.Timeout {
		client = &http.Client{Timeout: timeout}
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return nil, "", fmt.Errorf("%s returned status %d", rawURL, resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, "", err
	}
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(string(body)))
	if err != nil {
		return nil, "", err
	}
	return doc, string(body), nil
}

// --- JSON-LD extraction ------------------------------------------------------

type jsonldEvent struct {
	Name        string
	Dates       []string
	Location    string
	Description string
	Image       string
}

func formatJSONLDLocation(loc any) string {
	if list, ok := loc.([]any); ok {
		if len(list) == 0 {
			return ""
		}
		loc = list[0]
	}
	if s, ok := loc.(string); ok {
		return strings.TrimSpace(s)
	}
	m, ok := loc.(map[string]any)
	if !ok {
		return ""
	}
	addr := m["address"]
	if s, ok := addr.(string); ok {
		return strings.TrimSpace(s)
	}
	if am, ok := addr.(map[string]any); ok {
		city := strings.TrimSpace(asString(am["addressLocality"]))
		region := strings.TrimSpace(asString(am["addressRegion"]))
		country := strings.TrimSpace(asString(am["addressCountry"]))
		if city != "" && region != "" {
			return city + ", " + region
		}
		if city != "" && country != "" {
			return city + ", " + country
		}
		if city != "" {
			return city
		}
		if country != "" {
			return country
		}
		return region
	}
	return strings.TrimSpace(asString(m["name"]))
}

func asString(v any) string {
	s, _ := v.(string)
	return s
}

var isoDatePrefixRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}`)

func extractJSONLDEvent(doc *goquery.Document) jsonldEvent {
	out := jsonldEvent{}
	doc.Find(`script[type="application/ld+json"]`).Each(func(_ int, s *goquery.Selection) {
		var data any
		if err := json.Unmarshal([]byte(s.Text()), &data); err != nil {
			return
		}
		var objs []any
		if list, ok := data.([]any); ok {
			objs = list
		} else {
			objs = []any{data}
		}
		for _, o := range objs {
			m, ok := o.(map[string]any)
			if !ok {
				continue
			}
			typeStr := fmt.Sprintf("%v", m["@type"])
			if !strings.Contains(typeStr, "Event") {
				continue
			}
			if out.Name == "" {
				if name, ok := m["name"].(string); ok {
					out.Name = strings.TrimSpace(name)
				}
			}
			for _, key := range []string{"startDate", "endDate"} {
				if val, ok := m[key].(string); ok && isoDatePrefixRe.MatchString(val) {
					iso := val[:10]
					found := false
					for _, d := range out.Dates {
						if d == iso {
							found = true
							break
						}
					}
					if !found {
						out.Dates = append(out.Dates, iso)
					}
				}
			}
			if out.Description == "" {
				if desc, ok := m["description"].(string); ok {
					out.Description = strings.TrimSpace(desc)
				}
			}
			if out.Location == "" {
				out.Location = formatJSONLDLocation(m["location"])
			}
			if out.Image == "" {
				img := m["image"]
				if list, ok := img.([]any); ok {
					if len(list) > 0 {
						img = list[0]
					} else {
						img = ""
					}
				}
				if im, ok := img.(map[string]any); ok {
					img = im["url"]
				}
				if s, ok := img.(string); ok {
					out.Image = strings.TrimSpace(s)
				}
			}
		}
	})
	return out
}

// --- text helpers ------------------------------------------------------------

var whitespaceRe = regexp.MustCompile(`\s+`)

// collapsedText mirrors bs4's get_text(separator=" ", strip=True) closely
// enough for regex-based date/location extraction: goquery's Text() already
// concatenates text nodes across element boundaries (source markup nearly
// always has whitespace between block tags), so normalizing runs of
// whitespace to a single space is sufficient here.
func collapsedText(s *goquery.Selection) string {
	return strings.TrimSpace(whitespaceRe.ReplaceAllString(s.Text(), " "))
}

// textJoin mirrors bs4's get_text(separator=sep, strip=True): every text node
// under s is individually trimmed, empty ones are dropped, and the survivors
// are joined with sep — NOT the same as collapsing all whitespace to a single
// space, since bs4 never inserts a separator where the source markup had none
// (sep="") and always inserts exactly one where it does (sep=" ").
func textJoin(s *goquery.Selection, sep string) string {
	var parts []string
	var walk func(n *html.Node)
	walk = func(n *html.Node) {
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			if c.Type == html.TextNode {
				if t := strings.TrimSpace(c.Data); t != "" {
					parts = append(parts, t)
				}
			} else if c.Type == html.ElementNode {
				walk(c)
			}
		}
	}
	for _, n := range s.Nodes {
		if n.Type == html.TextNode {
			if t := strings.TrimSpace(n.Data); t != "" {
				parts = append(parts, t)
			}
		} else {
			walk(n)
		}
	}
	return strings.Join(parts, sep)
}

// textStripEmpty mirrors get_text(strip=True) (no separator).
func textStripEmpty(s *goquery.Selection) string { return textJoin(s, "") }

// textStripSpace mirrors get_text(separator=" ", strip=True).
func textStripSpace(s *goquery.Selection) string { return textJoin(s, " ") }

// soleTextChild mirrors bs4's `string=` tag filter: a tag only satisfies it
// when its ONE and ONLY child node is itself a NavigableString (no nested
// markup at all) — a heading like "<h2>Who Should <strong>Attend</strong></h2>"
// never matches, even though its rendered text does.
func soleTextChild(n *html.Node) (string, bool) {
	if n == nil || n.FirstChild == nil || n.FirstChild.NextSibling != nil {
		return "", false
	}
	if n.FirstChild.Type != html.TextNode {
		return "", false
	}
	return n.FirstChild.Data, true
}

// findHeadingsBySoleText mirrors soup.find_all([...], string=pattern): among
// the given heading tags, keep only those with a sole-text-node child whose
// text matches pattern, in document order.
func findHeadingsBySoleText(doc *goquery.Selection, tags string, pattern *regexp.Regexp) []*html.Node {
	var out []*html.Node
	doc.Find(tags).Each(func(_ int, s *goquery.Selection) {
		if s.Length() == 0 {
			return
		}
		text, ok := soleTextChild(s.Get(0))
		if !ok {
			return
		}
		if pattern.MatchString(text) {
			out = append(out, s.Get(0))
		}
	})
	return out
}

// wrapNode lets a single *html.Node (including a NextSibling walked node
// that isn't part of the original *goquery.Selection tree) be queried with
// goquery's Find, matching bs4's tag.find_all(...).
func wrapNode(n *html.Node) *goquery.Selection {
	return goquery.NewDocumentFromNode(n).Selection
}

func metaContent(doc *goquery.Document, attr, value string) string {
	sel := doc.Find(fmt.Sprintf(`meta[%s="%s"]`, attr, value)).First()
	if sel.Length() == 0 {
		return ""
	}
	v, _ := sel.Attr("content")
	return strings.TrimSpace(v)
}

// --- fetch_url ---------------------------------------------------------------

const monthRe = `(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?` +
	`|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)`

// buggyMonthGroup replicates a Python slicing bug in _normalize_day_first:
// the normalize regex is built from `month_re[4:-1]`, meant to strip the
// outer "(?:"/")" wrapper but actually stripping 4 leading chars ("(?:J")
// instead of 3 ("(?:"), eating the literal "J" off "Jan(?:uary)?". The
// resulting alternation starts with "an(?:uary)?|Feb(?:ruary)?|..." and can
// never match a real "Jan"/"January" token, so day-first January dates are
// silently left unnormalized. Preserved here rather than fixed, per the
// no-behavior-changes constraint.
var buggyMonthGroup = "(" + monthRe[4:len(monthRe)-1] + ")"

var (
	// Month-first/day-first extraction has no case-insensitive flag in
	// Python (no re.IGNORECASE on these two findall calls) — case-sensitive
	// here to match.
	monthFirstDateRe = regexp.MustCompile(monthRe + `[\s,]+\d{1,2}(?:st|nd|rd|th)?` +
		`(?:[\s,\x{2013}\-]+\d{1,2}(?:st|nd|rd|th)?[\s,]+)?20\d{2}\b`)
	dayFirstDateRe = regexp.MustCompile(`\b\d{1,2}(?:st|nd|rd|th)?(?:[\x{2013}-]\d{1,2}(?:st|nd|rd|th)?)?\s+` +
		monthRe + `\s+20\d{2}\b`)
	dayFirstNormalizeRe = regexp.MustCompile(`(?i)(\d{1,2})(?:st|nd|rd|th)?(?:[\x{2013}-]\d{1,2}(?:st|nd|rd|th)?)?\s+` +
		buggyMonthGroup + `\s+(20\d{2})`)
	locPattern1 = regexp.MustCompile(`\bin\s+([A-Z][a-zA-Z\s]+,\s*[A-Z][a-zA-Z]+)\b`)
	locPattern2 = regexp.MustCompile(`\b([A-Z][a-zA-Z]+,\s*(?:Japan|Germany|USA|UK|France|Spain|India|Canada|Australia))\b`)
)

func normalizeDayFirst(s string) string {
	m := dayFirstNormalizeRe.FindStringSubmatch(s)
	if m == nil {
		return s
	}
	return strings.Title(strings.ToLower(m[2])) + " " + m[1] + ", " + m[3]
}

func dedupeKeepOrder(items []string) []string {
	seen := map[string]struct{}{}
	var out []string
	for _, it := range items {
		if _, ok := seen[it]; ok {
			continue
		}
		seen[it] = struct{}{}
		out = append(out, it)
	}
	return out
}

func truncate(items []string, n int) []string {
	if len(items) > n {
		return items[:n]
	}
	return items
}

// FetchURL ports utils/content_tools.py's fetch_url.
func (w *WebScraper) FetchURL(rawURL string) (model.ScrapedEvent, error) {
	doc, _, err := w.get(rawURL, 15*time.Second)
	if err != nil {
		return model.ScrapedEvent{URL: rawURL, Error: err.Error()}, err
	}

	// Extract JSON-LD BEFORE stripping script/style/nav/footer/header below —
	// schema.org data lives in <script type="ld+json"> and would otherwise be
	// removed along with every other script tag. This is the authoritative source.
	jsonld := extractJSONLDEvent(doc)
	jsonldDates := jsonld.Dates

	doc.Find("script,style,nav,footer,header").Remove()

	// --- Event name ---
	eventName := jsonld.Name
	if eventName == "" {
		if og := metaContent(doc, "property", "og:title"); og != "" {
			eventName = og
		}
	}
	if eventName == "" {
		if title := strings.TrimSpace(doc.Find("title").First().Text()); title != "" {
			eventName = strings.TrimSpace(strings.SplitN(strings.SplitN(title, "|", 2)[0], "-", 2)[0])
		}
	}
	if eventName == "" {
		if h1 := doc.Find("h1").First(); h1.Length() > 0 {
			eventName = textStripEmpty(h1)
		}
	}

	// --- Organization / brand name ---
	organization := metaContent(doc, "property", "og:site_name")
	if organization == "" {
		domain := regexp.MustCompile(`https?://(www\.)?`).ReplaceAllString(rawURL, "")
		domain = strings.SplitN(domain, "/", 2)[0]
		switch {
		case strings.Contains(domain, "linuxfoundation"):
			organization = "Linux Foundation"
		case strings.Contains(domain, "cncf"):
			organization = "CNCF"
		}
	}

	// --- Description ---
	description := ""
	doc.Find("meta").EachWithBreak(func(_ int, s *goquery.Selection) bool {
		// Mirrors Python's `(meta.get("name") or meta.get("property") or
		// "").lower()` — an empty (but present) name attribute must still
		// fall through to property, matching "or" truthiness rather than
		// mere key-presence.
		name, _ := s.Attr("name")
		if name == "" {
			name, _ = s.Attr("property")
		}
		name = strings.ToLower(name)
		if name == "description" || name == "og:description" || name == "twitter:description" {
			description = strings.TrimSpace(s.AttrOr("content", ""))
			if description != "" {
				return false
			}
		}
		return true
	})
	if description == "" {
		description = jsonld.Description
	}

	bodyText := textStripSpace(doc.Selection)

	// --- Event dates ---
	monthFirst := monthFirstDateRe.FindAllString(bodyText, -1)
	dayFirst := dayFirstDateRe.FindAllString(bodyText, -1)
	normalizedDayFirst := make([]string, 0, len(dayFirst))
	for _, d := range dayFirst {
		normalizedDayFirst = append(normalizedDayFirst, normalizeDayFirst(d))
	}

	var allDates []string
	if len(jsonldDates) > 0 {
		allDates = truncate(jsonldDates, 3)
	} else {
		allDates = truncate(dedupeKeepOrder(append(append([]string{}, monthFirst...), normalizedDayFirst...)), 3)
	}

	// --- Location ---
	location := jsonld.Location
	if location == "" {
		if m := locPattern1.FindStringSubmatch(bodyText); m != nil {
			location = strings.TrimSpace(m[1])
		} else if m := locPattern2.FindStringSubmatch(bodyText); m != nil {
			location = strings.TrimSpace(m[1])
		}
	}
	if location == "" {
		slug := strings.ToLower(rawURL)
		cityHints := []struct{ key, val string }{
			{"japan", "Japan"}, {"europe", "Europe"}, {"north-america", "North America"},
			{"india", "India"}, {"china", "China"}, {"tokyo", "Tokyo"},
			{"amsterdam", "Amsterdam"}, {"paris", "Paris"}, {"london", "London"},
		}
		for _, h := range cityHints {
			if strings.Contains(slug, h.key) {
				location = h.val
				break
			}
		}
	}

	// --- H1-H3 headings ---
	headings := make([]string, 0, 6)
	for _, tag := range []string{"h1", "h2", "h3"} {
		sliceUpTo(doc.Find(tag), 5).EachWithBreak(func(_ int, s *goquery.Selection) bool {
			text := textStripEmpty(s)
			if text != "" && !contains(headings, text) {
				headings = append(headings, text)
			}
			return true
		})
	}

	if allDates == nil {
		allDates = []string{}
	}

	return model.ScrapedEvent{
		URL:         rawURL,
		EventName:   eventName,
		BrandName:   organization,
		Location:    location,
		EventDates:  allDates,
		Description: description,
		Headings:    truncate(headings, 6),
		BodyPreview: truncateRunes(bodyText, 2000),
	}, nil
}

func contains(list []string, v string) bool {
	for _, s := range list {
		if s == v {
			return true
		}
	}
	return false
}

func truncateRunes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

// --- scrape_event_full --------------------------------------------------------

var (
	speakerClassRe = regexp.MustCompile(`(?i)speaker|keynote|presenter`)
	topicClassRe   = regexp.MustCompile(`(?i)topic|track|tag|category|label`)
	sponsorClassRe = regexp.MustCompile(`(?i)sponsor|partner|supporter|exhibitor`)
	sponsorWordRe  = regexp.MustCompile(`(?i)sponsor|partner|exhibitor`)
	sponsorHeadRe  = regexp.MustCompile(`(?i)sponsor|partner|exhibitor`)
	noiseTitleRe   = regexp.MustCompile(`(?i)\b(director|engineer|manager|founder|president|chief|` +
		`officer|architect|consultant|professor|lead|scientist|researcher|advocate|specialist|` +
		`analyst|ceo|cto|coo|cfo|vp)\b`)
	speakerHeadingRe = regexp.MustCompile(`(?i)speakers?|keynotes?|presenters?`)
	audienceHeadRe   = regexp.MustCompile(`(?i)who\s+(should|is this for|attends?)|is\s+this\s+for\s+you|audience`)
	inclusionHeadRe  = regexp.MustCompile(`(?i)what.{0,4}included|(?:ticket|pass|registration)\s+includes?|what.{0,6}get`)
	// No case-insensitive flag in Python's re.findall for this pattern —
	// case-sensitive here to match (notably \b[A-Z]{3}\b requires an exact
	// uppercase 3-letter currency code, e.g. "JPY", not "jpy").
	ticketTypeRe = regexp.MustCompile(`(?:Early[ -]Bird|Regular|Standard|Professional|Academic|Student|Late|Final|Onsite)` +
		`[^\n]{0,40}(?:[$\x{20ac}\x{a3}\x{a5}]|\b[A-Z]{3}\b)\s?[\d,]+`)
	deadlineRe = regexp.MustCompile(`(?i)(?:deadline|closes?|ends?|last day)[^\n.]{0,60}` +
		`(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{1,2}[^\n.]{0,20}`)
)

func hasClassMatch(s *goquery.Selection, re *regexp.Regexp) bool {
	cls, _ := s.Attr("class")
	return re.MatchString(cls)
}

// extractBulletsAfterHeading finds a heading matching headRe (e.g. "Who
// Should Attend"), then pulls short bullet-like strings (<li>, or short <p>)
// from the section right after it. Mirrors Python's find_next_sibling()
// walk, which advances through EVERY sibling node (including whitespace-only
// text nodes between tags) rather than only element siblings — each such
// node still counts against the hop budget, and only element nodes can be
// searched for <li>/<p> descendants (hasattr(section, "find_all") gates
// text nodes out without erroring).
func extractBulletsAfterHeading(doc *goquery.Selection, headRe *regexp.Regexp, maxItems int) []string {
	items := make([]string, 0, maxItems)
	for _, h := range findHeadingsBySoleText(doc, "h1,h2,h3,h4", headRe) {
		section := h.NextSibling
		hops := 0
		for section != nil && hops < 3 && len(items) == 0 {
			if section.Type == html.ElementNode {
				sel := wrapNode(section)
				sliceUpTo(sel.Find("li"), maxItems).Each(func(_ int, li *goquery.Selection) {
					text := textStripSpace(li)
					if len(text) > 3 && len(text) < 140 && !contains(items, text) {
						items = append(items, text)
					}
				})
				if len(items) == 0 {
					sliceUpTo(sel.Find("p"), maxItems).Each(func(_ int, p *goquery.Selection) {
						text := textStripSpace(p)
						if len(text) > 10 && len(text) < 140 && !contains(items, text) {
							items = append(items, text)
						}
					})
				}
			}
			section = section.NextSibling
			hops++
		}
		if len(items) > 0 {
			break
		}
	}
	return truncate(items, maxItems)
}

// extractSpeakersAfterHeading is a fallback for sites that don't mark up
// speaker cards with a speaker/keynote/presenter class. See
// extractBulletsAfterHeading for the sibling-walk/hop-accounting semantics.
func extractSpeakersAfterHeading(doc *goquery.Selection, maxItems int) []string {
	names := make([]string, 0, maxItems)
	for _, h := range findHeadingsBySoleText(doc, "h1,h2,h3,h4", speakerHeadingRe) {
		section := h.NextSibling
		hops := 0
		for section != nil && hops < 6 && len(names) < maxItems {
			if section.Type == html.ElementNode {
				sel := wrapNode(section)
				cards := sel.Find("div,li,article")
				cardSels := make([]*goquery.Selection, 0, cards.Length())
				if cards.Length() == 0 {
					cardSels = append(cardSels, sel)
				} else {
					cards.Each(func(_ int, c *goquery.Selection) { cardSels = append(cardSels, c) })
				}
				for _, card := range cardSels {
					if len(names) >= maxItems {
						break
					}
					nameEl := card.Find("h2,h3,h4,strong").First()
					if nameEl.Length() == 0 {
						continue
					}
					text := textStripEmpty(nameEl)
					if len(text) > 3 && len(text) < 60 && !strings.Contains(text, ",") &&
						!noiseTitleRe.MatchString(text) && !contains(names, text) {
						names = append(names, text)
					}
				}
			}
			section = section.NextSibling
			hops++
		}
		if len(names) > 0 {
			break
		}
	}
	return truncate(names, maxItems)
}

func absURL(base, ref string) string {
	if ref == "" || strings.HasPrefix(ref, "data:") {
		return ""
	}
	b, err := url.Parse(base)
	if err != nil {
		return ref
	}
	r, err := url.Parse(ref)
	if err != nil {
		return ""
	}
	return b.ResolveReference(r).String()
}

// ScrapeEventFull ports utils/content_tools.py's scrape_event_full. Python's
// fetch_url() failure never short-circuits this function — the enhanced
// scrape runs its own, independent second fetch of the same URL regardless
// of whether the first one (inside fetch_url) succeeded, so a transient
// failure on the first request doesn't lose the hero image/speakers/etc.
// that a successful second request would still recover.
func (w *WebScraper) ScrapeEventFull(rawURL string) model.ScrapedEventFull {
	base, _ := w.FetchURL(rawURL)
	empty := model.ScrapedEventFull{
		ScrapedEvent: base,
		Speakers:     []string{}, Topics: []string{}, Sponsors: []model.ScrapedSponsor{},
		Audience: []string{}, Inclusions: []string{},
	}

	doc, _, err := w.get(rawURL, 15*time.Second)
	if err != nil {
		return empty
	}

	// --- Hero image ---
	heroImageURL := metaContent(doc, "property", "og:image")
	if heroImageURL == "" {
		heroImageURL = extractJSONLDEvent(doc).Image
	}

	// --- Logo ---
	logoURL := ""
	doc.Find("img").EachWithBreak(func(_ int, img *goquery.Selection) bool {
		src := strings.TrimSpace(img.AttrOr("src", ""))
		alt := strings.ToLower(img.AttrOr("alt", ""))
		cls := strings.ToLower(img.AttrOr("class", ""))
		haystack := strings.ToLower(src) + alt + cls
		if strings.Contains(haystack, "logo") || strings.Contains(haystack, "brand") {
			if strings.HasPrefix(src, "http") {
				logoURL = src
			} else if strings.HasPrefix(src, "/") {
				logoURL = absURL(rawURL, src)
			}
			if logoURL != "" {
				return false
			}
		}
		return true
	})

	// --- Speakers ---
	speakers := make([]string, 0, 12)
	count := 0
	doc.Find("div,article,li,section").EachWithBreak(func(_ int, el *goquery.Selection) bool {
		if count >= 8 {
			return false
		}
		if !hasClassMatch(el, speakerClassRe) {
			return true
		}
		count++
		nameEl := el.Find("h2,h3,h4,strong").First()
		if nameEl.Length() == 0 {
			return true
		}
		name := textStripEmpty(nameEl)
		if len(name) > 3 && len(name) < 60 && !contains(speakers, name) {
			speakers = append(speakers, name)
		}
		return true
	})

	if len(speakers) < 3 {
		for _, name := range extractSpeakersAfterHeading(doc.Selection, 12) {
			if !contains(speakers, name) {
				speakers = append(speakers, name)
			}
		}
	}

	// --- Topics / tracks ---
	topics := make([]string, 0, 10)
	count = 0
	doc.Find("span,div,li,a").EachWithBreak(func(_ int, el *goquery.Selection) bool {
		if count >= 10 {
			return false
		}
		if !hasClassMatch(el, topicClassRe) {
			return true
		}
		count++
		text := textStripEmpty(el)
		if len(text) > 3 && len(text) < 50 && !contains(topics, text) {
			topics = append(topics, text)
		}
		return true
	})

	// --- Sponsors / partners ---
	sponsors := make([]model.ScrapedSponsor, 0, 10)
	seenSponsorNames := map[string]struct{}{}
	noiseNames := map[string]struct{}{
		"sponsors": {}, "partners": {}, "our sponsors": {}, "our partners": {},
		"supported by": {}, "thank you sponsors": {}, "gold": {}, "silver": {},
		"platinum": {}, "bronze": {}, "media partner": {}, "community partner": {},
	}
	addSponsor := func(name, logoURL string) {
		name = strings.TrimSpace(name)
		if len(name) < 3 || len(name) > 80 {
			return
		}
		if _, noise := noiseNames[strings.ToLower(name)]; noise {
			return
		}
		if _, ok := seenSponsorNames[name]; ok {
			if logoURL != "" {
				for i := range sponsors {
					if sponsors[i].Name == name && sponsors[i].LogoURL == "" {
						sponsors[i].LogoURL = logoURL
					}
				}
			}
			return
		}
		seenSponsorNames[name] = struct{}{}
		sponsors = append(sponsors, model.ScrapedSponsor{Name: name, LogoURL: logoURL})
	}

	// Strategy 1: elements whose class names contain sponsor/partner keywords
	count = 0
	doc.Find("div,section,article,li,figure,a").EachWithBreak(func(_ int, el *goquery.Selection) bool {
		if count >= 20 {
			return false
		}
		if !hasClassMatch(el, sponsorClassRe) {
			return true
		}
		count++
		img := el.Find("img").First()
		logoURL := ""
		name := ""
		if img.Length() > 0 {
			src := img.AttrOr("src", img.AttrOr("data-src", ""))
			logoURL = absURL(rawURL, src)
			name = strings.TrimSpace(img.AttrOr("alt", ""))
		}
		if name == "" {
			name = truncateRunes(textStripSpace(el), 80)
		}
		addSponsor(name, logoURL)
		return true
	})

	// Strategy 2: headings like "Sponsors" / "Partners" followed by img
	// elements. Python's `h.find_next_sibling()` (no args) skips
	// non-element nodes (e.g. whitespace text between tags) and returns
	// the next actual Tag, so mirror that by walking siblings to the next
	// ElementNode rather than taking the immediate raw next node.
	for _, h := range findHeadingsBySoleText(doc.Selection, "h2,h3,h4", sponsorHeadRe) {
		sibling := h.NextSibling
		for sibling != nil && sibling.Type != html.ElementNode {
			sibling = sibling.NextSibling
		}
		if sibling == nil {
			continue
		}
		sliceUpTo(wrapNode(sibling).Find("img"), 10).Each(func(_ int, img *goquery.Selection) {
			src := img.AttrOr("src", img.AttrOr("data-src", ""))
			logoURL := absURL(rawURL, src)
			name := strings.TrimSpace(img.AttrOr("alt", ""))
			addSponsor(name, logoURL)
		})
	}

	// Strategy 3: any <img> with "sponsor" / "partner" in its src path or alt
	sliceUpTo(doc.Find("img"), 60).Each(func(_ int, img *goquery.Selection) {
		src := img.AttrOr("src", img.AttrOr("data-src", ""))
		alt := strings.TrimSpace(img.AttrOr("alt", ""))
		if sponsorWordRe.MatchString(src) || sponsorWordRe.MatchString(alt) {
			logoURL := absURL(rawURL, src)
			if len(alt) > 3 && len(alt) < 80 {
				addSponsor(alt, logoURL)
			}
		}
	})

	// --- Named action links ---
	eventHost := ""
	if u, err := url.Parse(rawURL); err == nil {
		eventHost = strings.ToLower(u.Host)
	}
	type linkPurpose struct {
		key      string
		keywords []string
	}
	linkPurposes := []linkPurpose{
		{"register", []string{"register", "registration", "get ticket", "buy ticket", "attend"}},
		{"sponsor", []string{"sponsor", "sponsorship", "exhibit", "become a sponsor"}},
		{"cfp", []string{"call for proposal", "cfp", "submit a proposal", "submit a talk", "submit a poster", "poster", "propose", "speak"}},
		{"schedule", []string{"schedule", "agenda", "view sessions"}},
		{"venue", []string{"venue", "travel", "hotel", "getting here"}},
	}
	links := map[string]string{}
	doc.Find("a[href]").Each(func(_ int, a *goquery.Selection) {
		href := a.AttrOr("href", "")
		if strings.HasPrefix(href, "#") || strings.HasPrefix(href, "mailto:") || strings.HasPrefix(href, "tel:") {
			return
		}
		absu := absURL(rawURL, href)
		if absu == "" {
			return
		}
		u, err := url.Parse(absu)
		if err != nil || strings.ToLower(u.Host) != eventHost {
			return
		}
		lowTxt := strings.ToLower(textStripEmpty(a))
		lowHref := strings.ToLower(absu)
		if lowTxt == "" {
			return
		}
		for _, lp := range linkPurposes {
			if _, ok := links[lp.key]; ok {
				continue
			}
			for _, kw := range lp.keywords {
				if strings.Contains(lowTxt, kw) || strings.Contains(lowHref, kw) {
					links[lp.key] = absu
					break
				}
			}
		}
	})

	regURL := links["register"]

	// --- Audience / inclusions ---
	audience := extractBulletsAfterHeading(doc.Selection, audienceHeadRe, 6)
	inclusions := extractBulletsAfterHeading(doc.Selection, inclusionHeadRe, 6)

	// --- Scrape registration page ---
	regDetails := model.RegistrationDetails{}
	if regURL != "" && strings.TrimRight(regURL, "/") != strings.TrimRight(rawURL, "/") {
		if regDoc, regBody, err := w.get(regURL, 10*time.Second); err == nil {
			if len(inclusions) == 0 {
				inclusions = extractBulletsAfterHeading(regDoc.Selection, inclusionHeadRe, 6)
			}
			if len(audience) == 0 {
				audience = extractBulletsAfterHeading(regDoc.Selection, audienceHeadRe, 6)
			}
			rt := textStripSpace(regDoc.Selection)
			_ = regBody
			regDetails = model.RegistrationDetails{
				URL:         regURL,
				TicketTypes: truncate(ticketTypeRe.FindAllString(rt, -1), 3),
				Deadlines:   truncate(deadlineRe.FindAllString(rt, -1), 2),
			}
		} else {
			regDetails = model.RegistrationDetails{URL: regURL}
		}
	}

	return model.ScrapedEventFull{
		ScrapedEvent: base,
		HeroImageURL: heroImageURL,
		LogoURL:      logoURL,
		Speakers:     truncate(speakers, 12),
		Topics:       truncate(topics, 6),
		Sponsors:     sponsorsTruncate(sponsors, 10),
		Registration: regDetails,
		Links: model.EventLinks{
			Register: links["register"],
			Sponsor:  links["sponsor"],
			CFP:      links["cfp"],
			Schedule: links["schedule"],
			Venue:    links["venue"],
		},
		Audience:   audience,
		Inclusions: inclusions,
	}
}

func sponsorsTruncate(s []model.ScrapedSponsor, n int) []model.ScrapedSponsor {
	if len(s) > n {
		return s[:n]
	}
	return s
}

// --- prepare_content -----------------------------------------------------------

var (
	googleDocURLRe = regexp.MustCompile(`^https://docs\.google\.com/document/`)
	htmlTagRe      = regexp.MustCompile(`<[a-zA-Z][^>]*>`)
)

// PrepareContent ports utils/content_tools.py's prepare_content.
func (w *WebScraper) PrepareContent(contentInput string) (string, error) {
	text := strings.TrimSpace(contentInput)
	if googleDocURLRe.MatchString(text) {
		return w.fetchGoogleDoc(text)
	}
	if htmlTagRe.MatchString(text) {
		return text, nil
	}
	return plainToHTML(text), nil
}

func plainToHTML(text string) string {
	lines := strings.Split(text, "\n")
	var parts []string
	for _, line := range lines {
		if strings.TrimSpace(line) != "" {
			parts = append(parts, "<p>"+line+"</p>")
		}
	}
	return strings.Join(parts, "\n")
}
