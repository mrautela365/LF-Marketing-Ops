import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import type {
  ComposeMasterListRequest,
  ComposeMasterListResponse,
  ExistingMasterListsResponse,
  LastSentResponse,
  PreviewCountRequest,
  PreviewCountResponse,
  QaRunRequest,
  QaRunResponse,
  SuppressionListsResponse,
} from '@email-creation/shared';

/**
 * Wraps the 8 deterministic /api/audience-builder/* routes (ported from
 * audience_builder/routes.py). Discovery (/discover, /discover-stream) is
 * deferred to migration phase 5 (LLM gateway) and has no client here yet.
 */
@Injectable({ providedIn: 'root' })
export class AudienceBuilderService {
  constructor(private readonly http: HttpClient) {}

  suppressionLists(brandShort: string, eventName: string): Observable<SuppressionListsResponse> {
    return this.http.get<SuppressionListsResponse>('/api/audience-builder/suppression-lists', {
      params: { brand_short: brandShort, event_name: eventName },
    });
  }

  lastSent(eventName: string, brandShort: string): Observable<LastSentResponse> {
    return this.http.get<LastSentResponse>('/api/audience-builder/last-sent', {
      params: { event_name: eventName, brand_short: brandShort },
    });
  }

  existingMasterLists(brandShort: string, eventName: string): Observable<ExistingMasterListsResponse> {
    return this.http.get<ExistingMasterListsResponse>('/api/audience-builder/existing-master-lists', {
      params: { brand_short: brandShort, event_name: eventName },
    });
  }

  previewCount(req: PreviewCountRequest): Observable<PreviewCountResponse> {
    return this.http.post<PreviewCountResponse>('/api/audience-builder/preview-count', req);
  }

  composeMaster(req: ComposeMasterListRequest): Observable<ComposeMasterListResponse> {
    return this.http.post<ComposeMasterListResponse>('/api/audience-builder/compose-master', req);
  }

  qaRun(req: QaRunRequest): Observable<QaRunResponse> {
    return this.http.post<QaRunResponse>('/api/audience-builder/qa/run', req);
  }

  qaReportUrl(listId: string, targetsEU: boolean, targetsCA: boolean): string {
    const params = new URLSearchParams({
      list_id: listId,
      targets_eu: String(targetsEU),
      targets_ca: String(targetsCA),
    });
    return `/api/audience-builder/qa/report.xlsx?${params.toString()}`;
  }
}
