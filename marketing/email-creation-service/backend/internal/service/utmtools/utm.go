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

	merged := orderedQuery{}
	merged.setAll(u.RawQuery)
	merged.set("utm_source", source)
	merged.set("utm_medium", medium)
	merged.set("utm_campaign", utmParams["utm_campaign"])
	if utmContent != "" {
		merged.set("utm_content", utmContent)
	}
	if term := utmParams["utm_term"]; term != "" {
		merged.set("utm_term", term)
	}

	u.RawQuery = merged.encode()
	return u.String()
}

// orderedQuery preserves query-parameter insertion order, mirroring Python's
// urlencode(dict) — existing params first (in their original order), then
// newly-set utm_* keys in the order they were set. Go's url.Values.Encode()
// always sorts keys alphabetically, which would produce a byte-different
// (though semantically equivalent) query string.
type orderedQuery struct {
	keys   []string
	values map[string]string
}

func (o *orderedQuery) set(key, value string) {
	if o.values == nil {
		o.values = map[string]string{}
	}
	if _, exists := o.values[key]; !exists {
		o.keys = append(o.keys, key)
	}
	o.values[key] = value
}

func (o *orderedQuery) setAll(rawQuery string) {
	for _, pair := range strings.Split(rawQuery, "&") {
		if pair == "" {
			continue
		}
		kv := strings.SplitN(pair, "=", 2)
		key, err := url.QueryUnescape(kv[0])
		if err != nil || key == "" {
			continue
		}
		value := ""
		if len(kv) == 2 {
			value, err = url.QueryUnescape(kv[1])
			if err != nil {
				value = kv[1]
			}
		}
		o.set(key, value)
	}
}

func (o *orderedQuery) encode() string {
	var sb strings.Builder
	for _, k := range o.keys {
		if sb.Len() > 0 {
			sb.WriteByte('&')
		}
		sb.WriteString(url.QueryEscape(k))
		sb.WriteByte('=')
		sb.WriteString(url.QueryEscape(o.values[k]))
	}
	return sb.String()
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
