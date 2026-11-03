import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { AlertsQuery, AlertsService } from '../../api/alerts.service';
import { AlertRow, Page } from '../../api/models';
import { alertRowsFixture, pageOf } from '../../api/testing/fixtures';
import { Performance } from './performance';

/** In-memory `/api/alerts` answer of the spec. */
class FakeAlerts {
  answer: Page<AlertRow> = pageOf(alertRowsFixture());
  failure: HttpErrorResponse | null = null;

  list(query: AlertsQuery): Observable<Page<AlertRow>> {
    return this.failure
      ? throwError(() => this.failure)
      : of(structuredClone({ ...this.answer, page: query.page }));
  }
}

function render(fake: FakeAlerts): ComponentFixture<Performance> {
  TestBed.configureTestingModule({ providers: [{ provide: AlertsService, useValue: fake }] });
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
  it('renders the counters of the fixture', () => {
    const el = render(new FakeAlerts()).nativeElement as HTMLElement;

    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Performance');
    expect(
      Array.from(el.querySelectorAll('.card-value')).map((node) => node.textContent?.trim()),
    ).toEqual(['1', '1', '0', '100.0 %', '+4.1 %']);
  });

  it('renders one row per alert type and the one horizon the API reports', () => {
    const el = render(new FakeAlerts()).nativeElement as HTMLElement;

    expect(cells(el, '[data-testid="horizons"]')).toEqual([['7d', '1', '1', '0', '100.0 %']]);
    expect(cells(el, '[data-testid="types"]')).toEqual([
      ['long_signal', '1', '1', '0', '100.0 %', '+4.1 %'],
      ['short_signal', '0', '0', '0', '—', '—'],
    ]);
  });

  it('renders the empty state for an empty answer, not a zero rate', () => {
    const fake = new FakeAlerts();
    fake.answer = { items: [], total: 0, page: 1, per_page: 200 };
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('[data-testid="empty"]')?.textContent).toContain('No alerts to judge');
    expect(el.querySelector('[data-testid="types"]')).toBeNull();
    expect(el.querySelector('[data-testid="horizons"]')).toBeNull();
  });

  it('renders an error line with the status when the call fails', () => {
    const fake = new FakeAlerts();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('[data-testid="error"]')?.textContent).toContain('HTTP 503');
  });
});
