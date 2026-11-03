import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { Overview } from '../../api/models';
import { OverviewService } from '../../api/overview.service';
import { emptyOverviewFixture, overviewFixture } from '../../api/testing/fixtures';
import { OverviewStore } from './overview.store';

/** In-memory `/api/overview` answer of the spec. */
class FakeOverview {
  answer: Overview = overviewFixture();
  failure: HttpErrorResponse | null = null;
  calls = 0;

  get(): Observable<Overview> {
    this.calls += 1;
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function setup(fake: FakeOverview): OverviewStore {
  TestBed.configureTestingModule({ providers: [{ provide: OverviewService, useValue: fake }] });
  const store = TestBed.inject(OverviewStore);
  TestBed.tick();
  return store;
}

describe('OverviewStore', () => {
  it('maps the full payload onto its signals', () => {
    const fake = new FakeOverview();
    const store = setup(fake);

    expect(fake.calls).toBe(1);
    expect(store.data()).toEqual(overviewFixture());
    expect(store.loading()).toBe(false);
    expect(store.error()).toBeNull();
    expect(store.empty()).toBe(false);
    expect(store.cards()).toEqual([
      { key: 'assets', label: 'Assets', value: '12' },
      { key: 'posts', label: 'Posts', value: '4210' },
      { key: 'analyses', label: 'Analyses', value: '3980' },
      { key: 'alerts', label: 'Alerts', value: '57' },
      { key: 'open_alerts', label: 'Open alerts', value: '9' },
      { key: 'last_collector_run', label: 'Last collector run', value: '2026-11-03 06:15' },
      { key: 'database_size_bytes', label: 'Database size', value: '4.0 MB' },
    ]);
  });

  it('maps an empty payload to the empty state and shows no grid of zeros', () => {
    const fake = new FakeOverview();
    fake.answer = emptyOverviewFixture();
    const store = setup(fake);

    expect(store.empty()).toBe(true);
    expect(store.cards()).toEqual([]);
  });

  it('keeps null fields null and shows an em dash instead of 0', () => {
    const fake = new FakeOverview();
    fake.answer = { ...overviewFixture(), last_collector_run: null, database_size_bytes: null };
    const store = setup(fake);

    expect(store.data()!.last_collector_run).toBeNull();
    expect(store.data()!.database_size_bytes).toBeNull();
    expect(store.cards().find((card) => card.key === 'last_collector_run')!.value).toBe('—');
    expect(store.cards().find((card) => card.key === 'database_size_bytes')!.value).toBe('—');
    expect(store.empty()).toBe(false);
  });

  it('sets the error signal with the status when the call fails', () => {
    const fake = new FakeOverview();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const store = setup(fake);

    expect(store.error()).toEqual({ status: 503, message: 'Service Unavailable' });
    expect(store.data()).toBeNull();
    expect(store.empty()).toBe(false);
    expect(store.loading()).toBe(false);
  });

  it('reloads on demand and clears a previous error', () => {
    const fake = new FakeOverview();
    fake.failure = new HttpErrorResponse({ status: 500, statusText: 'Internal Server Error' });
    const store = setup(fake);
    expect(store.error()?.status).toBe(500);

    fake.failure = null;
    store.reload();
    TestBed.tick();

    expect(fake.calls).toBe(2);
    expect(store.error()).toBeNull();
    expect(store.data()).toEqual(overviewFixture());
  });
});
