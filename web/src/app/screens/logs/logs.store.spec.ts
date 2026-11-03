import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { LogRow, Page } from '../../api/models';
import { LogsQuery, LogsService } from '../../api/logs.service';
import { logRowsFixture, pageOf } from '../../api/testing/fixtures';
import { LogsStore } from './logs.store';

/** In-memory `/api/logs` answer of the spec. */
class FakeLogs {
  answer: Page<LogRow> = pageOf(logRowsFixture());
  failure: HttpErrorResponse | null = null;
  readonly queries: LogsQuery[] = [];

  list(query: LogsQuery): Observable<Page<LogRow>> {
    this.queries.push(query);
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function setup(fake: FakeLogs): LogsStore {
  TestBed.configureTestingModule({ providers: [{ provide: LogsService, useValue: fake }] });
  const store = TestBed.inject(LogsStore);
  TestBed.tick();
  return store;
}

describe('LogsStore', () => {
  it('maps the full payload onto its signals', () => {
    const fake = new FakeLogs();
    const store = setup(fake);

    expect(fake.queries).toEqual([{ page: 1, per_page: 50, level: null }]);
    expect(store.items()).toEqual(logRowsFixture());
    expect(store.total()).toBe(2);
    expect(store.error()).toBeNull();
    expect(store.empty()).toBe(false);
    expect(store.rows()[0]).toEqual({
      id: 77,
      timestamp: '2026-11-03 06:05',
      level: 'ERROR',
      tone: 'err',
      logger: 'newstrading.collectors.rss',
      service: 'collector',
      message: 'feed unavailable',
      function: 'collect',
      line: '142',
      exception: 'TimeoutError: 30s',
      metadata: '{"url":"https://example.test/feed"}',
    });
  });

  it('maps an empty payload to the empty state', () => {
    const fake = new FakeLogs();
    fake.answer = { items: [], total: 0, page: 1, per_page: 50 };
    const store = setup(fake);

    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(true);
    expect(store.rows()).toEqual([]);
  });

  it('keeps null fields null and shows an em dash instead of 0', () => {
    const fake = new FakeLogs();
    const store = setup(fake);

    expect(store.items()[1].function).toBeNull();
    expect(store.items()[1].line_number).toBeNull();
    expect(store.items()[1].exception).toBeNull();
    expect(store.items()[1].metadata).toBeNull();
    expect(store.rows()[1]).toEqual({
      id: 76,
      timestamp: '2026-11-03 06:00',
      level: 'INFO',
      tone: 'ok',
      logger: 'newstrading.cli',
      service: 'cli',
      message: 'collect finished',
      function: '—',
      line: '—',
      exception: '—',
      metadata: '—',
    });
  });

  it('sets the error signal with the status when the call fails', () => {
    const fake = new FakeLogs();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const store = setup(fake);

    expect(store.error()).toEqual({ status: 503, message: 'Service Unavailable' });
    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(false);
    expect(store.loading()).toBe(false);
  });

  it('pages and filters by level, and a new filter starts at page 1', () => {
    const fake = new FakeLogs();
    fake.answer = pageOf(logRowsFixture(), 120);
    const store = setup(fake);

    expect(store.pages()).toBe(3);
    store.next();
    TestBed.tick();
    expect(fake.queries.at(-1)).toEqual({ page: 2, per_page: 50, level: null });

    store.setLevel('ERROR');
    TestBed.tick();
    expect(store.page()).toBe(1);
    expect(store.filtered()).toBe(true);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 50, level: 'ERROR' });

    store.setLevel('');
    TestBed.tick();
    expect(store.filtered()).toBe(false);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 50, level: null });
  });

  it('asks the endpoint exactly once per page change', () => {
    const fake = new FakeLogs();
    fake.answer = pageOf(logRowsFixture(), 120);
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
    const fake = new FakeLogs();
    fake.answer = pageOf(logRowsFixture(), 120);
    const store = setup(fake);
    const before = fake.queries.length;

    store.setPage(99);
    TestBed.tick();

    expect(store.pages()).toBe(3);
    expect(store.page()).toBe(3);
    expect(fake.queries.length).toBe(before + 1);
    expect(fake.queries.at(-1)?.page).toBe(3);
    expect(store.pageNotice()).toContain('page 3');
    expect(store.pageNotice()).toContain('does not exist');

    store.setLevel('ERROR');
    TestBed.tick();
    expect(store.pageNotice()).toBeNull();
  });

  it('changes the page size, starts again at page 1 and keeps the window inside the list', () => {
    const fake = new FakeLogs();
    fake.answer = pageOf(logRowsFixture(), 120);
    const store = setup(fake);

    store.setPage(3);
    TestBed.tick();

    store.setPerPage(100);
    TestBed.tick();

    expect(store.perPage()).toBe(100);
    expect(store.page()).toBe(1);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 100, level: null });
    expect(store.pages()).toBe(2);
  });
});
