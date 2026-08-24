// Package utmtools holds pure UTM URL-tagging helpers with no HubSpot API
// dependency — ports integrations/utm.py. Used by dispatch.HubSpotClient's
// content-writer methods to tag every outbound link in a staged email.
package utmtools

import (
	"fmt"
	"net/url"
	"regexp"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

var slugCollapseRe = regexp.MustCompile(`[^a-z0-9]+`)

// AddUTM merges utm_source/utm_medium/utm_campaign/utm_content into url's
// query string. No-op if url is empty/falsy, utmParams is empty, url is a
// mailto:/tel:/anchor link, or the url already carries a non-empty
// utm_campaign (never double-tag pre-tagged links).
func AddUTM(rawURL string, utmParams map[string]string, utmContent string) string {
	if rawURL == "" || len(utmParams) == 0 {
		return rawURL
	}
	if strings.HasPrefix(rawURL, "mailto:") || strings.HasPrefix(rawURL, "tel:") || strings.HasPrefix(rawURL, "#") {
		return rawURL
	}

	u, err := url.Parse(rawURL)
	if err != nil {
		return rawURL
	}
	q := u.Query()
	if q.Get("utm_campaign") != "" {
		return rawURL
	}

	source := utmParams["utm_source"]
	if source == "" {
		source = "email"
	}
	medium := utmParams["utm_medium"]
	if medium == "" {
		medium = "email"
	}
	q.Set("utm_source", source)
	q.Set("utm_medium", medium)
	q.Set("utm_campaign", utmParams["utm_campaign"])
	if utmContent != "" {
		q.Set("utm_content", utmContent)
	}
	if term := utmParams["utm_term"]; term != "" {
		q.Set("utm_term", term)
	}

	u.RawQuery = q.Encode()
	return u.String()
}

// SlugifyUTMContent turns "Register Now" into "register-now-cta" (suffix
// defaults appended unless already present; suffix used as the whole slug
// when text collapses to nothing).
func SlugifyUTMContent(text, suffix string) string {
	slug := slugCollapseRe.ReplaceAllString(strings.ToLower(strings.TrimSpace(text)), "-")
	slug = strings.Trim(slug, "-")
	if slug == "" {
		return suffix
	}
	if suffix != "" && !strings.HasSuffix(slug, suffix) {
		slug = slug + "-" + suffix
	}
	return slug
}

// TagHTMLLinks tags every <a href> in a rich_text HTML fragment, skipping
// mailto:/tel:/anchor-only links and any link that already carries a
// non-empty utm_campaign. Uses goquery for parsing rather than an exact
// html.parser-equivalent walk — sufficient for the flat rich-text fragments
// HubSpot widgets contain, not guaranteed byte-identical to BeautifulSoup's
// serialization for deeply nested markup.
func TagHTMLLinks(html string, utmParams map[string]string, prefix string) string {
	if html == "" || len(utmParams) == 0 {
		return html
	}

	doc, err := goquery.NewDocumentFromReader(strings.NewReader(html))
	if err != nil {
		return html
	}

	count := 0
	doc.Find("a[href]").Each(func(_ int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		if strings.HasPrefix(href, "mailto:") || strings.HasPrefix(href, "tel:") || strings.HasPrefix(href, "#") {
			return
		}
		count++
		s.SetAttr("href", AddUTM(href, utmParams, fmt.Sprintf("%s-%d", prefix, count)))
	})

	out, err := doc.Find("body").Html()
	if err != nil {
		return html
	}
	return out
}
