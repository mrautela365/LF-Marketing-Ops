// Package sse is a tiny in-memory pub/sub used by every long-running wizard
// turn (plan generation, content generation) to stream progress lines to a
// browser EventSource, porting main.py's `_progress` dict + `progress_emit`.
package sse

import (
	"sync"
	"time"
)

// Broker holds one buffered channel per progress token. Single-consumer,
// single-use per token, matching Python: once a subscriber reads Close() (or
// the token is popped), the token is dead and cannot be re-subscribed.
type Broker struct {
	mu       sync.Mutex
	channels map[string]chan any
}

func NewBroker() *Broker {
	return &Broker{channels: map[string]chan any{}}
}

// Open creates (or returns the existing) channel for token. Buffered
// generously since a fast producer (progress lines) must never block on a
// slow/absent SSE consumer.
func (b *Broker) Open(token string) chan any {
	b.mu.Lock()
	defer b.mu.Unlock()
	if ch, ok := b.channels[token]; ok {
		return ch
	}
	ch := make(chan any, 256)
	b.channels[token] = ch
	return ch
}

// Emit pushes an event to token's channel. Silently drops if no one ever
// opened the token (mirrors Python's channel being a no-op sink when
// progress_token wasn't supplied).
func (b *Broker) Emit(token string, event any) {
	b.mu.Lock()
	ch, ok := b.channels[token]
	b.mu.Unlock()
	if !ok {
		return
	}
	select {
	case ch <- event:
	case <-time.After(2 * time.Second):
		// A stuck consumer must never wedge the producing goroutine.
	}
}

// Close removes and closes token's channel — called once the SSE handler's
// subscriber loop exits (client disconnect or idle ceiling).
func (b *Broker) Close(token string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if ch, ok := b.channels[token]; ok {
		close(ch)
		delete(b.channels, token)
	}
}
