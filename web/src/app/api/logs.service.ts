import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { LogRow, Page } from './models';

/** The window and the filter of one `/api/logs` call. */
export interface LogsQuery {
  readonly page: number;
  readonly per_page: number;
  /** `system_logs.level`, `null` for every level. */
  readonly level: string | null;
}

/** `/api/logs`: `system_logs`, newest first (#56). */
@Injectable({ providedIn: 'root' })
export class LogsService {
  private readonly http = inject(HttpClient);

  /** `GET /api/logs?page=&per_page=&level=` -> one page of log lines. */
  list(query: LogsQuery): Observable<Page<LogRow>> {
    let params = new HttpParams().set('page', query.page).set('per_page', query.per_page);
    if (query.level !== null) {
      params = params.set('level', query.level);
    }
    return this.http.get<Page<LogRow>>('/api/logs', { params });
  }
}
