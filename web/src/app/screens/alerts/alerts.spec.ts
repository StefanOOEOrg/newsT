import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { AlertsQuery, AlertsService } from '../../api/alerts.service';
import { AlertRow, Page } from '../../api/models';
import { alertRowsFixture, pageOf } from '../../api/testing/fixtures';
import { Alerts } from './alerts';
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

function render(fake: FakeAlerts): ComponentFixture<Alerts> {
  TestBed.configureTestingModule({ providers: [{ provide: AlertsService, useValue: fake }] });
  const fixture = TestBed.createComponent(Alerts);
  TestBed.tick();
  fixture.detectChanges();
  return fixture;
}

function rows(el: HTMLElement): string[][] {
  return Array.from(el.querySelectorAll('tbody tr')).map((row) =>
    Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent!.trim()),
  );
}

describe('Alerts screen', () => {
  it('renders one row per item of the fixture', () => {
    const el = render(new FakeAlerts()).nativeElement as HTMLElement;

    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Alerts');
    expect(rows(el)).toEqual([
      [
        '91',
        'AAPL',
        'long_signal',
        'high',
        'Strong bullish signal on AAPL',
        '0.87',
        '2026-11-02 18:02',
        'yes',
        '+4.1 %',
        'yes',
      ],
      [
        '90',
        '—',
        'short_signal',
        'low',
        'Mild bearish signal',
        '—',
        '2026-11-01 09:30',
        '—',
        '—',
        '—',
      ],
    ]);
  });

  it('renders the empty state for an empty answer', () => {
    const fake = new FakeAlerts();
    fake.answer = { items: [], total: 0, page: 1, per_page: 25 };
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="empty"]')?.textContent).toContain('No alerts yet');
  });

  it('renders an error line with the status when the call fails', () => {
    const fake = new FakeAlerts();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="error"]')?.textContent).toContain('HTTP 503');
  });

  it('filters by the severity the user picked', () => {
    const fake = new FakeAlerts();
    const el = render(fake).nativeElement as HTMLElement;

    const select = el.querySelector<HTMLSelectElement>('.toolbar select')!;
    select.value = 'high';
    select.dispatchEvent(new Event('change'));
    TestBed.tick();

    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 25, severity: 'high' });
  });

  it('offers the four page sizes, sends the picked one and restarts at page 1', () => {
    const fake = new FakeAlerts();
    fake.answer = pageOf(alertRowsFixture(), 120);
    const fixture = render(fake);
    const el = fixture.nativeElement as HTMLElement;

    const options = Array.from(el.querySelectorAll<HTMLOptionElement>('.pager select option'));
    expect(options.map((option) => option.value)).toEqual(['25', '50', '100', '200']);

    const select = el.querySelector<HTMLSelectElement>('.pager select')!;
    expect(select.value).toBe('25');

    TestBed.inject(AlertsStore).setPage(3);
    TestBed.tick();
    fixture.detectChanges();
    expect(el.querySelector('.pager span')?.textContent).toContain('page 3 / 5');

    select.value = '50';
    select.dispatchEvent(new Event('change'));
    TestBed.tick();
    fixture.detectChanges();

    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 50, severity: null });
    expect(el.querySelector('.pager span')?.textContent).toContain('page 1 / 3');
  });

  it('says so when a page beyond the last one was clamped', () => {
    const fake = new FakeAlerts();
    fake.answer = pageOf(alertRowsFixture(), 60);
    const fixture = render(fake);
    const el = fixture.nativeElement as HTMLElement;

    TestBed.inject(AlertsStore).setPage(42);
    TestBed.tick();
    fixture.detectChanges();

    expect(el.querySelector('[data-testid="page-notice"]')?.textContent).toContain('page 3');
  });
});
