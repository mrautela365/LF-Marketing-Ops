package discovery

import (
	"context"
	"sync"

	"github.com/google/uuid"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/audiencetools"
)

// jobQueueCapacity mirrors audiencetools' own constant — see that
// package's jobs.go for the rationale (Python's queue.Queue is unbounded;
// a large buffer is the practical Go equivalent).
const jobQueueCapacity = 4096

// Service owns discovery's own job store — a map[string]chan any,
// completely separate from audiencetools.Service's _jobs-equivalent map,
// mirroring discovery_agent.py's own module-level `_jobs` dict (kept
// decoupled from the list-building flow it does not touch).
type Service struct {
	Toolkit *audiencetools.Toolkit
	Gateway domain.LLMGateway

	mu   sync.Mutex
	jobs map[string]chan any
}

// NewService constructs the discovery job-running service. tk is the same
// audiencetools.Toolkit instance the audience-builder flows use — reused by
// composition, never reimplemented.
func NewService(tk *audiencetools.Toolkit, gw domain.LLMGateway) *Service {
	return &Service{Toolkit: tk, Gateway: gw, jobs: map[string]chan any{}}
}

// StartDiscoveryJob ports start_discovery_job. Returns the job_id for SSE
// polling via GET /api/audience-builder/discover-stream/{job_id}.
func (s *Service) StartDiscoveryJob(ctx context.Context, eventURL, qa string) string {
	id := uuid.NewString()
	q := make(chan any, jobQueueCapacity)
	s.mu.Lock()
	s.jobs[id] = q
	s.mu.Unlock()

	prompt := BuildDiscoveryPrompt(eventURL, qa)
	go runDiscoveryAgent(ctx, s.Gateway, s.Toolkit, prompt, q)
	return id
}

// GetJobQueue ports get_job_queue.
func (s *Service) GetJobQueue(jobID string) (chan any, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	q, ok := s.jobs[jobID]
	return q, ok
}

// RemoveJob ports remove_job.
func (s *Service) RemoveJob(jobID string) {
	s.mu.Lock()
	delete(s.jobs, jobID)
	s.mu.Unlock()
}
