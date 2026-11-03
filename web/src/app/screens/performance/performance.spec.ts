import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { PerformanceAnswer } from '../../api/models';
import { PerformanceService } from '../../api/performance.service';
import { Performance } from './performance';

/** The three horizons and two per-type rows `GET /api/performance` answers with in the spec. */
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

/** In-memory `/api/performance` answer of the spec. */
class FakePerformance {
  answer: PerformanceAnswer = answerFixture();
  failure: HttpErrorResponse | null = null;

  get(): Observable<PerformanceAnswer> {
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function render(fake: FakePerformance): ComponentFixture<Performance> {
  TestBed.configureTestingModule({ providers: [{ provide: PerformanceService, useValue: fake }] });
  const fixture = TestBed.createComponent(Performance);
  TestBed.tick();
  fixture.detectChanges();
  return fixture;
}

function cells(el: HTMLElement, selector: string): string[][] {
  return Array.from(el.querySelectorAll(`${selector} tbody tr`)).map((row) =>
    Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent!.trim()),
  );
}

describe('Performance screen', () => {
  it('renders one row per horizon the API returns', () => {
    const el = render(new FakePerformance()).nativeElement as HTMLElement;

    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Performance');
    expect(cells(el, '[data-testid="horizons"]')).toEqual([
      ['1d', '40', '25', '62.5 %'],
      ['3d', '0', '0', '—'],
      ['7d', '40', '0', '0 %'],
    ]);
  });

  it('renders the by_type rows the API returns', () => {
    const el = render(new FakePerformance()).nativeElement as HTMLElement;

    expect(cells(el, '[data-testid="types"]')).toEqual([
      ['price_spike', '7d', '30', '9', '30 %'],
      ['volume_spike', '7d', '10', '0', '0 %'],
    ]);
  });

  it('renders the empty sentence for an empty by_type table, not a zero row', () => {
    const fake = new FakePerformance();
    fake.answer = { ...answerFixture(), by_type: [] };
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('[data-testid="types"]')).toBeNull();
    expect(el.querySelector('[data-testid="types-empty"]')?.textContent).toContain(
      'No alert type has a 7-day verdict',
    );
  });

  it('renders the empty state for an answer without a single alert', () => {
    const fake = new FakePerformance();
    fake.answer = {
      horizons: [
        { horizon: '1d', alerts: 0, correct: 0, hit_rate: null },
        { horizon: '3d', alerts: 0, correct: 0, hit_rate: null },
        { horizon: '7d', alerts: 0, correct: 0, hit_rate: null },
      ],
      by_type: [],
    };
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('[data-testid="empty"]')?.textContent).toContain('No alerts to judge');
    expect(el.querySelector('[data-testid="horizons"]')).toBeNull();
    expect(el.querySelector('[data-testid="types"]')).toBeNull();
  });

  it('renders an error line with the status when the call fails', () => {
    const fake = new FakePerformance();
    fake.failure = new HttpErrorResponse({ status: 500, statusText: 'Server Error' });
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('[data-testid="error"]')?.textContent).toContain('HTTP 500');
    expect(el.querySelector('[data-testid="horizons"]')).toBeNull();
  });
});
