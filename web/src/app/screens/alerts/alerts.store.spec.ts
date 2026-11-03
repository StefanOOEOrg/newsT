import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { AlertsQuery, AlertsService } from '../../api/alerts.service';
import { AlertRow, Page } from '../../api/models';
import { alertRowsFixture, pageOf } from '../../api/testing/fixtures';
import { AlertsStore } from './alerts.store';

/** In-memory `/api/alerts` answer of the spec. */
class FakeAlerts {
  answer: Page<AlertRow> = pageOf(alertRowsFixture());
  failure: HttpErrorResponse | null = null;
  readonly queries: AlertsQuery[] = [];

  list(query: AlertsQuery): Observable<Page<AlertRow>> {
    this.queries.push(query);
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function setup(fake: FakeAlerts): AlertsStore {
  TestBed.configureTestingModule({ providers: [{ provide: AlertsService, useValue: fake }] });
  const store = TestBed.inject(AlertsStore);
  TestBed.tick();
  return store;
}

describe('AlertsStore', () => {
  it('maps the full payload onto its signals', () => {
    const fake = new FakeAlerts();
    const store = setup(fake);

    expect(fake.queries).toEqual([{ page: 1, per_page: 25, severity: null }]);
    expect(store.items()).toEqual(alertRowsFixture());
    expect(store.total()).toBe(2);
    expect(store.error()).toBeNull();
    expect(store.empty()).toBe(false);
    expect(store.rows()[0]).toEqual({
      id: 91,
      asset: 'AAPL',
      alertType: 'long_signal',
      severity: 'high',
      description: 'Strong bullish signal on AAPL',
      confidence: '0.87',
      timestamp: '2026-11-02 18:02',
      notified: 'yes',
      return7d: '+4.1 %',
      correct7d: 'yes',
    });
  });

  it('maps an empty payload to the empty state', () => {
    const fake = new FakeAlerts();
    fake.answer = { items: [], total: 0, page: 1, per_page: 25 };
    const store = setup(fake);

    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(true);
    expect(store.rows()).toEqual([]);
  });

  it('keeps null fields null and shows an em dash instead of 0', () => {
    const fake = new FakeAlerts();
    const store = setup(fake);

    expect(store.items()[1].confidence_score).toBeNull();
    expect(store.items()[1].return_7d).toBeNull();
    expect(store.items()[1].correct_7d).toBeNull();
    expect(store.rows()[1]).toEqual({
      id: 90,
      asset: '—',
      alertType: 'short_signal',
      severity: 'low',
      description: 'Mild bearish signal',
      confidence: '—',
      timestamp: '2026-11-01 09:30',
      notified: '—',
      return7d: '—',
      correct7d: '—',
    });
  });

  it('sets the error signal with the status when the call fails', () => {
    const fake = new FakeAlerts();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const store = setup(fake);

    expect(store.error()).toEqual({ status: 503, message: 'Service Unavailable' });
    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(false);
    expect(store.loading()).toBe(false);
  });

  it('pages and filters by severity, and a new filter starts at page 1', () => {
    const fake = new FakeAlerts();
    fake.answer = pageOf(alertRowsFixture(), 60);
    const store = setup(fake);

    expect(store.pages()).toBe(3);
    store.next();
    TestBed.tick();
    expect(fake.queries.at(-1)).toEqual({ page: 2, per_page: 25, severity: null });

    store.setSeverity('high');
    TestBed.tick();
    expect(store.page()).toBe(1);
    expect(store.filtered()).toBe(true);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 25, severity: 'high' });

    store.setSeverity('');
    TestBed.tick();
    expect(store.filtered()).toBe(false);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 25, severity: null });
  });

  it('asks the endpoint exactly once per page change', () => {
    const fake = new FakeAlerts();
    fake.answer = pageOf(alertRowsFixture(), 60);
    const store = setup(fake);
    const before = fake.queries.length;

    store.next();
    TestBed.tick();
    expect(fake.queries.length).toBe(before + 1);
    expect(fake.queries.at(-1)?.page).toBe(2);

    store.setPage(3);
    TestBed.tick();
    expect(fake.queries.length).toBe(before + 2);
    expect(fake.queries.at(-1)?.page).toBe(3);

    store.previous();
    TestBed.tick();
    expect(fake.queries.length).toBe(before + 3);
    expect(fake.queries.at(-1)?.page).toBe(2);
  });

  it('clamps a page beyond the last one to the last page and says so', () => {
    const fake = new FakeAlerts();
    fake.answer = pageOf(alertRowsFixture(), 60);
    const store = setup(fake);
    const before = fake.queries.length;

    store.setPage(42);
    TestBed.tick();

    expect(store.pages()).toBe(3);
    expect(store.page()).toBe(3);
    expect(fake.queries.length).toBe(before + 1);
    expect(fake.queries.at(-1)?.page).toBe(3);
    expect(store.pageNotice()).toContain('page 3');
    expect(store.pageNotice()).toContain('does not exist');

    store.previous();
    TestBed.tick();
    expect(store.page()).toBe(2);
    expect(store.pageNotice()).toBeNull();
  });

  it('changes the page size, starts again at page 1 and keeps the window inside the list', () => {
    const fake = new FakeAlerts();
    fake.answer = pageOf(alertRowsFixture(), 60);
    const store = setup(fake);

    store.setPage(3);
    TestBed.tick();

    store.setPerPage(50);
    TestBed.tick();

    expect(store.perPage()).toBe(50);
    expect(store.page()).toBe(1);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 50, severity: null });
    expect(store.pages()).toBe(2);
  });
});
