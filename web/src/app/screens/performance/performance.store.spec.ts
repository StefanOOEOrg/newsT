import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { AlertsQuery, AlertsService } from '../../api/alerts.service';
import { AlertRow, Page } from '../../api/models';
import { alertRowsFixture, pageOf } from '../../api/testing/fixtures';
import { PerformanceStore } from './performance.store';

/** In-memory `/api/alerts` answer of the spec: the only source of the performance screen. */
class FakeAlerts {
  answer: Page<AlertRow> = pageOf(alertRowsFixture(), 2);
  failure: HttpErrorResponse | null = null;
  readonly queries: AlertsQuery[] = [];

  list(query: AlertsQuery): Observable<Page<AlertRow>> {
    this.queries.push(query);
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function setup(fake: FakeAlerts): PerformanceStore {
  TestBed.configureTestingModule({ providers: [{ provide: AlertsService, useValue: fake }] });
  const store = TestBed.inject(PerformanceStore);
  TestBed.tick();
  return store;
}

describe('PerformanceStore', () => {
  it('maps the full payload onto its signals', () => {
    const fake = new FakeAlerts();
    const store = setup(fake);

    expect(fake.queries).toEqual([{ page: 1, per_page: 200, severity: null }]);
    expect(store.items()).toEqual(alertRowsFixture());
    expect(store.error()).toBeNull();
    expect(store.empty()).toBe(false);
    expect(store.evaluated()).toBe(1);
    expect(store.hits()).toBe(1);
    expect(store.misses()).toBe(0);
    expect(store.hitRate()).toBe(1);
    expect(store.hitRateLabel()).toBe('100.0 %');
    expect(store.averageReturn()).toBe(0.0412);
    expect(store.averageReturnLabel()).toBe('+4.1 %');
  });

  it('groups the hit rate per alert type', () => {
    const fake = new FakeAlerts();
    const store = setup(fake);

    expect(store.rows()).toEqual([
      {
        alertType: 'long_signal',
        evaluated: '1',
        hits: '1',
        misses: '0',
        rate: '100.0 %',
        averageReturn: '+4.1 %',
      },
      {
        alertType: 'short_signal',
        evaluated: '0',
        hits: '0',
        misses: '0',
        rate: '—',
        averageReturn: '—',
      },
    ]);
  });

  it('reports the one horizon the API exposes', () => {
    const fake = new FakeAlerts();
    const store = setup(fake);

    expect(store.horizons()).toEqual([
      { horizon: '7d', evaluated: '1', hits: '1', misses: '0', rate: '100.0 %' },
    ]);
  });

  it('maps an empty payload to the empty state, not a zero hit rate', () => {
    const fake = new FakeAlerts();
    fake.answer = { items: [], total: 0, page: 1, per_page: 200 };
    const store = setup(fake);

    expect(store.empty()).toBe(true);
    expect(store.items()).toEqual([]);
    expect(store.rows()).toEqual([]);
    expect(store.horizons()).toEqual([]);
    expect(store.evaluated()).toBe(0);
    expect(store.hitRate()).toBeNull();
    expect(store.hitRateLabel()).toBe('—');
  });

  it('keeps an unjudged alert null instead of counting it as a miss', () => {
    const fake = new FakeAlerts();
    const store = setup(fake);

    expect(store.items()[1].correct_7d).toBeNull();
    expect(store.evaluated()).toBe(1);
    expect(store.misses()).toBe(0);
  });

  it('sets the error signal with the status when the call fails', () => {
    const fake = new FakeAlerts();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const store = setup(fake);

    expect(store.error()).toEqual({ status: 503, message: 'Service Unavailable' });
    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(false);
    expect(store.hitRate()).toBeNull();
  });

  it('reads every page the API reports', () => {
    const rows = alertRowsFixture();
    const queries: AlertsQuery[] = [];
    const paged = {
      list(query: AlertsQuery): Observable<Page<AlertRow>> {
        queries.push(query);
        return of(query.page === 1 ? pageOf(rows, 3, 1, 200) : pageOf([rows[0]], 3, 2, 200));
      },
    };
    TestBed.configureTestingModule({ providers: [{ provide: AlertsService, useValue: paged }] });
    const store = TestBed.inject(PerformanceStore);
    TestBed.tick();

    expect(queries.map((query) => query.page)).toEqual([1, 2]);
    expect(queries.every((query) => query.per_page === 200)).toBe(true);
    expect(store.items()).toHaveLength(3);
    expect(store.loading()).toBe(false);
  });
});
