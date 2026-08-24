package domain

import "errors"

// Sentinel domain errors. Transport/handler code maps these to HTTP status
// codes; service code should return one of these (wrapped with fmt.Errorf
// %w where extra context is useful) rather than ad hoc strings.
var (
	ErrNotFound        = errors.New("resource not found")
	ErrInvalidInput    = errors.New("invalid input")
	ErrUnauthorized    = errors.New("unauthorized")
	ErrUpstream        = errors.New("upstream service error")
	ErrSessionNotFound = errors.New("session not found")
	ErrJobNotFound     = errors.New("job not found")

	// ErrGoogleDocsUnsupported is returned by EventPageScraper.PrepareContent
	// for a Google Doc URL — the Python service's Google Docs API credential
	// flow was explicitly left out of scope for this migration pass.
	ErrGoogleDocsUnsupported = errors.New("google docs content source is not supported; paste the email content directly instead")
)
