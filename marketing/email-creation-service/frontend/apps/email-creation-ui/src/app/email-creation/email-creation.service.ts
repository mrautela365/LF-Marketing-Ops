import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import type {
  AudienceJobResponse,
  AudiencePlanRequest,
  AudienceStreamEvent,
  BuildAudienceRequest,
  ChatRequest,
  ChatResponse,
  CloneRequest,
  CloneResponse,
  CustomAudiencePlanRequest,
  CustomAudienceRunRequest,
  GenerateContentRequest,
  GenerateContentResponse,
  PlanStartRequest,
  PlanStartResponse,
  ProgressEvent,
  SetSendListRequest,
  SetSendListResponse,
  UpdateSectionsRequest,
  UpdateSectionsResponse,
} from '@email-creation/shared';

/**
 * Wraps the legacy Python backend's LLM-driven wizard routes (plan-start,
 * progress SSE, generate-content, update-sections, clone, set-send-list,
 * chat) — proxied at /api/* to the legacy FastAPI service (see
 * proxy.conf.json) until the Go LLM gateway (migration phase 4) lands.
 */
@Injectable({ providedIn: 'root' })
export class EmailCreationService {
  constructor(private readonly http: HttpClient) {}

  planStart(req: PlanStartRequest): Observable<PlanStartResponse> {
    return this.http.post<PlanStartResponse>('/api/plan-start', req);
  }

  /** Opens the SSE brief/progress channel for a token. Caller must close() it when done. */
  openProgressStream(token: string, onEvent: (ev: ProgressEvent) => void): EventSource {
    const source = new EventSource(`/api/progress/${encodeURIComponent(token)}`);
    source.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data) as ProgressEvent);
      } catch {
        // ignore malformed events
      }
    };
    return source;
  }

  generateContent(req: GenerateContentRequest): Observable<GenerateContentResponse> {
    return this.http.post<GenerateContentResponse>('/api/generate-content', req);
  }

  updateSections(req: UpdateSectionsRequest): Observable<UpdateSectionsResponse> {
    return this.http.post<UpdateSectionsResponse>('/api/update-sections', req);
  }

  clone(req: CloneRequest): Observable<CloneResponse> {
    return this.http.post<CloneResponse>('/api/clone', req);
  }

  setSendList(req: SetSendListRequest): Observable<SetSendListResponse> {
    return this.http.post<SetSendListResponse>('/api/set-send-list', req);
  }

  chat(req: ChatRequest): Observable<ChatResponse> {
    return this.http.post<ChatResponse>('/api/chat', req);
  }

  /** Phase 1 (plan only, no HubSpot writes) for an event-URL audience. */
  audiencePlan(req: AudiencePlanRequest): Observable<AudienceJobResponse> {
    const path = req.session_id ? '/api/audience-plan' : '/api/audience/plan';
    return this.http.post<AudienceJobResponse>(path, req);
  }

  /** Phase 2 (creates the real HubSpot lists) for an event-URL audience. */
  buildAudience(req: BuildAudienceRequest): Observable<AudienceJobResponse> {
    const path = req.session_id ? '/api/build-audience' : '/api/audience/run';
    return this.http.post<AudienceJobResponse>(path, req);
  }

  /** Phase 1 (plan only) for a free-text custom audience description. */
  customAudiencePlan(req: CustomAudiencePlanRequest): Observable<AudienceJobResponse> {
    return this.http.post<AudienceJobResponse>('/api/audience/custom-plan', req);
  }

  /** Phase 2 (creates the real HubSpot lists) for a free-text custom audience. */
  customAudienceRun(req: CustomAudienceRunRequest): Observable<AudienceJobResponse> {
    return this.http.post<AudienceJobResponse>('/api/audience/custom-run', req);
  }

  /** Opens the SSE ticker for an audience plan/build job. Caller must close() it when done. */
  openAudienceStream(jobId: string, sessionId: string | null, onEvent: (ev: AudienceStreamEvent) => void): EventSource {
    const url = sessionId
      ? `/api/audience-stream/${encodeURIComponent(jobId)}?session_id=${encodeURIComponent(sessionId)}`
      : `/api/audience-stream/${encodeURIComponent(jobId)}`;
    const source = new EventSource(url);
    source.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data) as AudienceStreamEvent);
      } catch {
        // ignore malformed events
      }
    };
    return source;
  }
}
