import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import type { ListsSearchResponse } from '@email-creation/shared';

/**
 * Thin wrapper around GET /api/audience-builder/lists/search (Go backend,
 * chi route). In dev, `/api` is proxied to http://localhost:8000 via
 * proxy.conf.json.
 */
@Injectable({ providedIn: 'root' })
export class ListsService {
  constructor(private readonly http: HttpClient) {}

  searchLists(query: string): Observable<ListsSearchResponse> {
    return this.http.get<ListsSearchResponse>('/api/audience-builder/lists/search', {
      params: { q: query },
    });
  }
}
