import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { PerformanceAnswer } from './models';

/**
 * `/api/performance` (#69): the hit rate the database aggregates for the performance screen.
 *
 * A service only builds the request and returns the observable - error handling and state live in
 * the store.
 */
@Injectable({ providedIn: 'root' })
export class PerformanceService {
  private readonly http = inject(HttpClient);

  /** `GET /api/performance` -> three horizons and the per-alert-type rows of the 7d horizon. */
  get(): Observable<PerformanceAnswer> {
    return this.http.get<PerformanceAnswer>('/api/performance');
  }
}
