import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Page, SourceRow } from './models';

/**
 * `/api/sources`: the collector health (#56).
 *
 * The endpoint answers the page envelope with `page: 1` and the default page size, but the list
 * itself is not paged - every collector is in the answer.
 */
@Injectable({ providedIn: 'root' })
export class SourcesService {
  private readonly http = inject(HttpClient);

  /** `GET /api/sources` -> one row per collector in `rate_limit_config`. */
  list(): Observable<Page<SourceRow>> {
    return this.http.get<Page<SourceRow>>('/api/sources');
  }
}
