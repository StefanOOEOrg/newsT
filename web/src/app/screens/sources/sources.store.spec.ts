import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { Page, SourceRow } from '../../api/models';
import { SourcesService } from '../../api/sources.service';
import { pageOf, sourceRowsFixture } from '../../api/testing/fixtures';
import { SourcesStore } from './sources.store';

/** In-memory `/api/sources` answer of the spec. */
class FakeSources {
  answer: Page<SourceRow> = pageOf(sourceRowsFixture());
  failure: HttpErrorResponse | null = null;
  calls = 0;

  list(): Observable<Page<SourceRow>> {
    this.calls += 1;
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function setup(fake: FakeSources): SourcesStore {
  TestBed.configureTestingModule({ providers: [{ provide: SourcesService, useValue: fake }] });
  const store = TestBed.inject(SourcesStore);
  TestBed.tick();
  return store;
}

describe('SourcesStore', () => {
  it('maps the full payload onto its signals', () => {
    const fake = new FakeSources();
    const store = setup(fake);

    expect(fake.calls).toBe(1);
    expect(store.items()).toEqual(sourceRowsFixture());
    expect(store.error()).toBeNull();
    expect(store.empty()).toBe(false);
    expect(store.rows()[0]).toEqual({
      collector: 'rss',
      lastRun: '2026-11-03 06:15',
      calls: '120',
      failures: '2',
      totalErrors: '3',
      quotaLimit: '—',
      quotaRemaining: '—',
      enabled: 'yes',
    });
    expect(store.summary()).toEqual({ collectors: '2', failing: '1', disabled: '1' });
  });

  it('maps an empty payload to the empty state', () => {
    const fake = new FakeSources();
    fake.answer = { items: [], total: 0, page: 1, per_page: 50 };
    const store = setup(fake);

    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(true);
    expect(store.rows()).toEqual([]);
    expect(store.summary()).toEqual({ collectors: '0', failing: '0', disabled: '0' });
  });

  it('keeps null fields null and shows an em dash instead of 0', () => {
    const fake = new FakeSources();
    const store = setup(fake);

    expect(store.items()[1].last_run).toBeNull();
    expect(store.items()[0].quota_limit).toBeNull();
    expect(store.rows()[1].lastRun).toBe('—');
    expect(store.rows()[0].quotaLimit).toBe('—');
    expect(store.rows()[0].quotaRemaining).toBe('—');
    expect(store.rows()[1].quotaLimit).toBe('100');
    expect(store.rows()[1].quotaRemaining).toBe('100');
  });

  it('sets the error signal with the status when the call fails', () => {
    const fake = new FakeSources();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const store = setup(fake);

    expect(store.error()).toEqual({ status: 503, message: 'Service Unavailable' });
    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(false);
    expect(store.loading()).toBe(false);
  });

  it('reloads on demand', () => {
    const fake = new FakeSources();
    const store = setup(fake);

    store.reload();
    TestBed.tick();

    expect(fake.calls).toBe(2);
    expect(store.items()).toHaveLength(2);
  });
});
