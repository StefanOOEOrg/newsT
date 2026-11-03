import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { AlertRow, Page } from './models';

/** The window and the filter of one `/api/alerts` call. */
export interface AlertsQuery {
  readonly page: number;
  readonly per_page: number;
  /** `alerts.severity` (`low`, `medium`, `high`, `critical`), `null` for every severity. */
  readonly severity: string | null;
}

/** `/api/alerts`: the alerts with their 7-day performance, newest first (#56). */
@Injectable({ providedIn: 'root' })
export class AlertsService {
  private readonly http = inject(HttpClient);

  /** `GET /api/alerts?page=&per_page=&severity=` -> one page of alerts. */
  list(query: AlertsQuery): Observable<Page<AlertRow>> {
    let params = new HttpParams().set('page', query.page).set('per_page', query.per_page);
    if (query.severity !== null) {
      params = params.set('severity', query.severity);
    }
    return this.http.get<Page<AlertRow>>('/api/alerts', { params });
  }
}
