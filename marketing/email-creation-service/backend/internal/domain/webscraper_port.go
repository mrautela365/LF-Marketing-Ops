package domain

import "github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"

// EventPageScraper fetches an event/campaign URL and extracts structured
// details for email staging, porting utils/content_tools.py's fetch_url and
// scrape_event_full.
type EventPageScraper interface {
	// FetchURL extracts the base event fields (name, brand, location, dates,
	// description, headings) — ports fetch_url.
	FetchURL(url string) (model.ScrapedEvent, error)

	// ScrapeEventFull extends FetchURL with hero/logo images, speakers,
	// topics, sponsors, named action links, audience/inclusions bullets, and
	// a registration-page sub-scrape — ports scrape_event_full.
	ScrapeEventFull(url string) model.ScrapedEventFull

	// PrepareContent normalizes a Google Doc URL, raw HTML, or plain text
	// into clean email-ready HTML — ports prepare_content. Google Doc URLs
	// are fetched via the Google Docs API using the service account file at
	// GOOGLE_SERVICE_ACCOUNT_FILE; if that's unset, it returns the same error
	// message _fetch_google_doc raises in that case.
	PrepareContent(contentInput string) (string, error)
}
