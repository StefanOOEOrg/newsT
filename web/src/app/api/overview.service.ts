import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Overview } from './models';

/**
 * `/api/overview` (#56): the counters of the overview screen.
 *
 * A service only builds the request and returns the observable - error handling and state live in
 * the store.
 */
@Injectable({ providedIn: 'root' })
export class OverviewService {
  private readonly http = inject(HttpClient);

  /** `GET /api/overview` -> five counters, the last collector run and the database size. */
  get(): Observable<Overview> {
    return this.http.get<Overview>('/api/overview');
  }
}
