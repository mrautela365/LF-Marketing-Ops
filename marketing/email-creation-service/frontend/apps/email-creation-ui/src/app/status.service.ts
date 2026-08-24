import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import type { StatusResponse } from '@email-creation/shared';

/**
 * Thin wrapper around GET /api/status (Go backend, `status` Goa service).
 * In dev, `/api` is proxied to http://localhost:8000 via proxy.conf.json.
 */
@Injectable({ providedIn: 'root' })
export class StatusService {
  constructor(private readonly http: HttpClient) {}

  getStatus(): Observable<StatusResponse> {
    return this.http.get<StatusResponse>('/api/status');
  }
}
