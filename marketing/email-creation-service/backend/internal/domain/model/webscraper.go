// Package model's webscraper.go holds the shapes returned by
// EventPageScraper, porting utils/content_tools.py's fetch_url and
// scrape_event_full return dicts.
package model

// ScrapedEvent is fetch_url's return shape.
type ScrapedEvent struct {
	URL         string   `json:"url"`
	EventName   string   `json:"event_name"`
	BrandName   string   `json:"brand_name"`
	Location    string   `json:"location"`
	EventDates  []string `json:"event_dates"`
	Description string   `json:"description"`
	Headings    []string `json:"headings"`
	BodyPreview string   `json:"body_preview"`

	// Error is set instead of the fields above when the fetch itself failed
	// (network error, non-2xx status, etc.) — mirrors fetch_url's
	// except-branch {"url":..., "error":...} shape.
	Error string `json:"error,omitempty"`
}

// Sponsor is one sponsor/partner logo discovered on the event page.
type ScrapedSponsor struct {
	Name    string `json:"name"`
	LogoURL string `json:"logo_url"`
}

// RegistrationDetails is the registration-page sub-scrape result.
type RegistrationDetails struct {
	URL          string   `json:"url,omitempty"`
	TicketTypes  []string `json:"ticket_types,omitempty"`
	Deadlines    []string `json:"deadlines,omitempty"`
}

// EventLinks is the named-action-link map: register/sponsor/cfp/schedule/venue.
type EventLinks struct {
	Register string `json:"register,omitempty"`
	Sponsor  string `json:"sponsor,omitempty"`
	CFP      string `json:"cfp,omitempty"`
	Schedule string `json:"schedule,omitempty"`
	Venue    string `json:"venue,omitempty"`
}

// ScrapedEventFull is scrape_event_full's return shape — ScrapedEvent plus
// hero/logo images, speakers, topics, sponsors, links, and audience/inclusion
// bullets.
type ScrapedEventFull struct {
	ScrapedEvent

	HeroImageURL string               `json:"hero_image_url"`
	LogoURL      string               `json:"logo_url"`
	Speakers     []string             `json:"speakers"`
	Topics       []string             `json:"topics"`
	Sponsors     []ScrapedSponsor     `json:"sponsors"`
	Registration RegistrationDetails  `json:"registration"`
	Links        EventLinks           `json:"links"`
	Audience     []string             `json:"audience"`
	Inclusions   []string             `json:"inclusions"`
}
