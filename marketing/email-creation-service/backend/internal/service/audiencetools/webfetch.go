package audiencetools

import (
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/PuerkitoBio/goquery"
	"golang.org/x/net/html"
)

// webFetchCacheTTL mirrors _WEB_FETCH_CACHE_TTL (30 min — long enough to
// span discover -> create-list on the same event).
const webFetchCacheTTL = 30 * time.Minute

// webFetchMaxChars mirrors the `[:12000]` cap on cleaned page text.
const webFetchMaxChars = 12000

// webFetchCacheEntry is one cached result, keyed by URL.
type webFetchCacheEntry struct {
	at     time.Time
	result map[string]any
}

// WebFetcher is audience_tools.py's own, independently-cached web_fetch —
// deliberately NOT sharing internal/dispatch/webscraper.go's EventPageScraper
// (that adapter serves the wizard's richer ScrapeEventFull flow; Python keeps
// two separate scraping code paths and this port preserves that duplication
// rather than collapsing it). Shared by every audience flow (discovery, plan,
// build, custom-plan, custom-build) as their single "web_fetch" tool, exactly
// as in Python.
type WebFetcher struct {
	mu    sync.Mutex
	cache map[string]webFetchCacheEntry
	// httpClient is overridable in tests; defaults to a 20s-timeout client
	// matching Python's requests.get(..., timeout=20).
	httpClient *http.Client
}

func NewWebFetcher() *WebFetcher {
	return &WebFetcher{
		cache:      map[string]webFetchCacheEntry{},
		httpClient: &http.Client{Timeout: 20 * time.Second},
	}
}

// Fetch ports web_fetch(url) verbatim: GET with a desktop-Chrome UA,
// strip script/style/nav/footer/header, join remaining text with "\n",
// cap at 12000 chars, and cache successful results for 30 minutes.
func (f *WebFetcher) Fetch(url string) map[string]any {
	now := time.Now()

	f.mu.Lock()
	cached, ok := f.cache[url]
	f.mu.Unlock()
	if ok && now.Sub(cached.at) < webFetchCacheTTL {
		return cached.result
	}

	result := f.fetchUncached(url)

	if _, isErr := result["error"]; !isErr {
		f.mu.Lock()
		f.cache[url] = webFetchCacheEntry{at: now, result: result}
		f.mu.Unlock()
	}
	return result
}

func (f *WebFetcher) fetchUncached(url string) map[string]any {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return map[string]any{"url": url, "error": err.Error()}
	}
	req.Header.Set("User-Agent",
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

	resp, err := f.httpClient.Do(req)
	if err != nil {
		return map[string]any{"url": url, "error": err.Error()}
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return map[string]any{"url": url, "error": http.StatusText(resp.StatusCode)}
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return map[string]any{"url": url, "error": err.Error()}
	}

	doc, err := goquery.NewDocumentFromReader(strings.NewReader(string(body)))
	if err != nil {
		return map[string]any{"url": url, "error": err.Error()}
	}
	doc.Find("script, style, nav, footer, header").Remove()

	// text extraction mirrors BeautifulSoup's soup.get_text(separator="\n"):
	// every text node in document order, joined with "\n" — NOT goquery's
	// Text(), which concatenates adjacent text nodes with no separator and
	// would merge unrelated inline text together.
	var textNodes []string
	if doc.Nodes != nil && len(doc.Nodes) > 0 {
		collectTextNodes(doc.Nodes[0], &textNodes)
	}
	text := strings.Join(textNodes, "\n")
	var lines []string
	for _, l := range strings.Split(text, "\n") {
		l = strings.TrimSpace(l)
		if l != "" {
			lines = append(lines, l)
		}
	}
	content := strings.Join(lines, "\n")
	if len(content) > webFetchMaxChars {
		content = content[:webFetchMaxChars]
	}

	return map[string]any{"url": url, "status": resp.StatusCode, "content": content}
}

// collectTextNodes appends every html.TextNode's Data, in document order,
// to out — the traversal soup.get_text() performs internally.
func collectTextNodes(n *html.Node, out *[]string) {
	if n.Type == html.TextNode {
		*out = append(*out, n.Data)
		return
	}
	for c := n.FirstChild; c != nil; c = c.NextSibling {
		collectTextNodes(c, out)
	}
}
