import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { PerformanceAnswer } from '../../api/models';
import { PerformanceService } from '../../api/performance.service';
import { PerformanceStore } from './performance.store';

/**
 * In-memory `/api/performance` answer of the spec: the three horizons the endpoint computes and
 * two per-type rows for the 7d horizon. The 3d horizon has no alert yet, so its `hit_rate` is
 * `null`; the 7d horizon was judged and every alert missed, so its `hit_rate` is a real `0`.
 */
function answerFixture(): PerformanceAnswer {
  return {
    horizons: [
      { horizon: '1d', alerts: 40, correct: 25, hit_rate: 0.625 },
      { horizon: '3d', alerts: 0, correct: 0, hit_rate: null },
      { horizon: '7d', alerts: 40, correct: 0, hit_rate: 0.0 },
    ],
    by_type: [
      { alert_type: 'price_spike', horizon: '7d', alerts: 30, correct: 9, hit_rate: 0.3 },
      { alert_type: 'volume_spike', horizon: '7d', alerts: 10, correct: 0, hit_rate: 0.0 },
    ],
  };
}

/** Answers `GET /api/performance` from memory - the only source of the performance screen. */
class FakePerformance {
  answer: PerformanceAnswer = answerFixture();
  failure: HttpErrorResponse | null = null;
  readonly calls: number[] = [];

  get(): Observable<PerformanceAnswer> {
    this.calls.push(this.calls.length + 1);
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function setup(fake: FakePerformance): PerformanceStore {
  TestBed.configureTestingModule({ providers: [{ provide: PerformanceService, useValue: fake }] });
  const store = TestBed.inject(PerformanceStore);
  TestBed.tick();
  return store;
}

describe('PerformanceStore', () => {
  it('reads the three horizons from one /api/performance answer', () => {
    const fake = new FakePerformance();
    const store = setup(fake);

    expect(fake.calls).toHaveLength(1);
    expect(store.horizons()).toEqual([
      { horizon: '1d', alerts: '40', correct: '25', rate: '62.5 %' },
      { horizon: '3d', alerts: '0', correct: '0', rate: '—' },
      { horizon: '7d', alerts: '40', correct: '0', rate: '0 %' },
    ]);
  });

  it('renders a null hit rate as the em dash and a zero rate as 0 %', () => {
    const store = setup(new FakePerformance());

    expect(store.horizons()[1].rate).toBe('—');
    expect(store.horizons()[2].rate).toBe('0 %');
  });

  it('maps the by_type rows in the order the API returns them', () => {
    const store = setup(new FakePerformance());

    expect(store.rows()).toEqual([
      {
        alertType: 'price_spike',
        horizon: '7d',
        alerts: '30',
        correct: '9',
        rate: '30 %',
      },
      {
        alertType: 'volume_spike',
        horizon: '7d',
        alerts: '10',
        correct: '0',
        rate: '0 %',
      },
    ]);
  });

  it('keeps the empty state for an answer without a single alert', () => {
    const fake = new FakePerformance();
    fake.answer = {
      horizons: [
        { horizon: '1d', alerts: 0, correct: 0, hit_rate: null },
        { horizon: '3d', alerts: 0, correct: 0, hit_rate: null },
        { horizon: '7d', alerts: 0, correct: 0, hit_rate: null },
      ],
      by_type: [],
    };
    const store = setup(fake);

    expect(store.empty()).toBe(true);
    expect(store.rows()).toEqual([]);
    expect(store.horizons().map((row) => row.rate)).toEqual(['—', '—', '—']);
  });

  it('leaves no numbers and sets the error when the call fails', () => {
    const fake = new FakePerformance();
    fake.failure = new HttpErrorResponse({ status: 500, statusText: 'Server Error' });
    const store = setup(fake);

    expect(store.error()).toEqual({ status: 500, message: 'Server Error' });
    expect(store.horizons()).toEqual([]);
    expect(store.rows()).toEqual([]);
    expect(store.empty()).toBe(false);
    expect(store.loading()).toBe(false);
  });

  it('clears the numbers of an earlier answer when a refresh fails', () => {
    const fake = new FakePerformance();
    const store = setup(fake);

    expect(store.horizons()).toHaveLength(3);

    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    store.reload();
    TestBed.tick();

    expect(store.horizons()).toEqual([]);
    expect(store.error()).toEqual({ status: 503, message: 'Service Unavailable' });
  });

  it('issues a second call on refresh', () => {
    const fake = new FakePerformance();
    const store = setup(fake);

    expect(fake.calls).toHaveLength(1);

    store.reload();
    TestBed.tick();

    expect(fake.calls).toHaveLength(2);
  });
});
