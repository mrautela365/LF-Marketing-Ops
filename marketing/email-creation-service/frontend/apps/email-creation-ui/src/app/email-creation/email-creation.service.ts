import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import type {
  ChatRequest,
  ChatResponse,
  CloneRequest,
  CloneResponse,
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
}
