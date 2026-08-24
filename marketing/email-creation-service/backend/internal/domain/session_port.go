package domain

import "github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"

// SessionStore is the wizard's in-memory session port, mirroring
// core/session.py's create/get/update trio. No expiration or persistence —
// sessions die on process restart, matching the Python behavior exactly (no
// TTL exists there either).
type SessionStore interface {
	Create() *model.SessionState
	Get(sessionID string) (*model.SessionState, bool)
	Update(s *model.SessionState)
}
