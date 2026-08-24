// Package memory holds in-process, non-persistent stores — swappable later
// without callers changing, since they only see the domain ports.
package memory

import (
	"sync"

	"github.com/google/uuid"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// SessionStore implements domain.SessionStore with a plain in-memory map,
// mirroring core/session.py's module-level dict — no eviction/TTL, matching
// the Python behavior (sessions die on process restart there too).
type SessionStore struct {
	mu       sync.RWMutex
	sessions map[string]*model.SessionState
}

var _ domain.SessionStore = (*SessionStore)(nil)

func NewSessionStore() *SessionStore {
	return &SessionStore{sessions: map[string]*model.SessionState{}}
}

func (s *SessionStore) Create() *model.SessionState {
	sess := model.NewSessionState(uuid.NewString())
	s.mu.Lock()
	s.sessions[sess.SessionID] = sess
	s.mu.Unlock()
	return sess
}

func (s *SessionStore) Get(sessionID string) (*model.SessionState, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	sess, ok := s.sessions[sessionID]
	return sess, ok
}

// Update is a no-op beyond re-storing the pointer — sessions are mutated in
// place elsewhere, same as Python's update() (which just re-assigns the
// same object into the dict).
func (s *SessionStore) Update(sess *model.SessionState) {
	s.mu.Lock()
	s.sessions[sess.SessionID] = sess
	s.mu.Unlock()
}
