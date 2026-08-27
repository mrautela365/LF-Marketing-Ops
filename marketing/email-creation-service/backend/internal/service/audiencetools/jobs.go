package audiencetools

import (
	"context"
	"strings"
	"sync"

	"github.com/google/uuid"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
)

// jobQueueCapacity bounds each job's event channel. Python's queue.Queue is
// unbounded; a large buffer is the practical Go equivalent so the agent
// goroutine never blocks waiting on a slow/absent SSE consumer during a
// single plan/build run.
const jobQueueCapacity = 4096

// Service owns audiencetools' own job store (a map[string]chan any,
// independent of the wizard's session store and the SSE broker's token
// namespace — mirrors audience_tools.py's own module-level `_jobs` dict)
// plus the shared Toolkit and LLMGateway every job's agent loop uses.
type Service struct {
	Toolkit *Toolkit
	Gateway domain.LLMGateway

	mu   sync.Mutex
	jobs map[string]chan any
}

// NewService constructs the audiencetools job-running service.
func NewService(tk *Toolkit, gw domain.LLMGateway) *Service {
	return &Service{Toolkit: tk, Gateway: gw, jobs: map[string]chan any{}}
}

func (s *Service) newJob() (string, chan any) {
	id := uuid.NewString()
	q := make(chan any, jobQueueCapacity)
	s.mu.Lock()
	s.jobs[id] = q
	s.mu.Unlock()
	return id, q
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

// StartPlanJob ports start_plan_job. Returns the job_id for SSE polling;
// the agent runs in its own goroutine, mirroring Python's daemon thread.
func (s *Service) StartPlanJob(ctx context.Context, eventURL string, prescraped *Prescraped, qa string) string {
	jobID, q := s.newJob()
	prompt := BuildPlanningPrompt(eventURL, prescraped, qa)
	go s.runAgent(ctx, prompt, q)
	return jobID
}

// StartBuildJob ports start_build_job: plan provided -> Phase 2 only; plan
// empty -> Phase 1 + Phase 2 chained automatically in one job.
func (s *Service) StartBuildJob(ctx context.Context, eventURL, plan, qa string, prescraped *Prescraped) string {
	jobID, q := s.newJob()
	if plan != "" {
		prompt := BuildBuildingPrompt(eventURL, plan, qa)
		go s.runAgent(ctx, prompt, q)
	} else {
		go s.runTwoPhase(ctx, eventURL, qa, q, prescraped)
	}
	return jobID
}

// runTwoPhase ports _run_two_phase verbatim: runs the planning prompt then
// the building prompt in sequence within one job, forwarding phase-1's
// "output" events to q but swallowing its "done" event (only phase 2's
// done=True is forwarded), and passing phase 1's accumulated output lines
// as {plan} to phase 2.
func (s *Service) runTwoPhase(ctx context.Context, eventURL, qa string, q chan any, prescraped *Prescraped) {
	if prescraped != nil {
		q <- map[string]any{"type": "output", "text": "═══ Phase 1: Segment Planning (reusing already-scraped event data) ═══"}
	} else {
		q <- map[string]any{"type": "output", "text": "═══ Phase 1: Segment Planning ═══"}
	}
	planQ := make(chan any, jobQueueCapacity)
	planPrompt := BuildPlanningPrompt(eventURL, prescraped, "")
	go s.runAgent(ctx, planPrompt, planQ)

	var planLines []string
	planSuccess := false
	for item := range planQ {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if m["type"] == "output" {
			planLines = append(planLines, strOf(m["text"]))
			q <- m
		} else if done, _ := m["done"].(bool); done {
			planSuccess, _ = m["success"].(bool)
			break
		}
	}

	if !planSuccess {
		q <- map[string]any{"type": "output", "text": "⚠ Planning phase failed — cannot continue to building."}
		q <- map[string]any{"type": "done", "done": true, "success": false}
		return
	}

	q <- map[string]any{"type": "output", "text": "\n═══ Phase 2: Building HubSpot Lists ═══"}
	planText := strings.Join(planLines, "\n")
	buildPrompt := BuildBuildingPrompt(eventURL, planText, qa)
	s.runAgent(ctx, buildPrompt, q) // puts done=true when building completes
}

// StartCustomPlanJob ports start_custom_plan_job.
func (s *Service) StartCustomPlanJob(ctx context.Context, requestText, qa string) string {
	jobID, q := s.newJob()
	prompt := BuildCustomPlanningPrompt(requestText, qa)
	go s.runAgent(ctx, prompt, q)
	return jobID
}

// StartCustomBuildJob ports start_custom_build_job.
func (s *Service) StartCustomBuildJob(ctx context.Context, requestText, plan, qa string) string {
	jobID, q := s.newJob()
	if plan != "" {
		prompt := BuildCustomBuildingPrompt(requestText, plan, qa)
		go s.runAgent(ctx, prompt, q)
	} else {
		go s.runCustomTwoPhase(ctx, requestText, qa, q)
	}
	return jobID
}

// runCustomTwoPhase ports _run_custom_two_phase verbatim.
func (s *Service) runCustomTwoPhase(ctx context.Context, requestText, qa string, q chan any) {
	q <- map[string]any{"type": "output", "text": "═══ Phase 1: Segment Planning ═══"}
	planQ := make(chan any, jobQueueCapacity)
	planPrompt := BuildCustomPlanningPrompt(requestText, "")
	go s.runAgent(ctx, planPrompt, planQ)

	var planLines []string
	planSuccess := false
	for item := range planQ {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if m["type"] == "output" {
			planLines = append(planLines, strOf(m["text"]))
			q <- m
		} else if done, _ := m["done"].(bool); done {
			planSuccess, _ = m["success"].(bool)
			break
		}
	}

	if !planSuccess {
		q <- map[string]any{"type": "output", "text": "⚠ Planning phase failed — cannot continue to building."}
		q <- map[string]any{"type": "done", "done": true, "success": false}
		return
	}

	q <- map[string]any{"type": "output", "text": "\n═══ Phase 2: Building HubSpot Lists ═══"}
	planText := strings.Join(planLines, "\n")
	buildPrompt := BuildCustomBuildingPrompt(requestText, planText, qa)
	s.runAgent(ctx, buildPrompt, q)
}
