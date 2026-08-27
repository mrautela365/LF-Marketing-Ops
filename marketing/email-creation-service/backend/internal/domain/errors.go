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
)
