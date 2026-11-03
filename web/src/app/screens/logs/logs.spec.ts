import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { LogRow, Page } from '../../api/models';
import { LogsQuery, LogsService } from '../../api/logs.service';
import { logRowsFixture, pageOf } from '../../api/testing/fixtures';
import { Logs } from './logs';
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

function render(fake: FakeLogs): ComponentFixture<Logs> {
  TestBed.configureTestingModule({ providers: [{ provide: LogsService, useValue: fake }] });
  const fixture = TestBed.createComponent(Logs);
  TestBed.tick();
  fixture.detectChanges();
  return fixture;
}

describe('Logs screen', () => {
  it('renders one row per line of the fixture with the level tone', () => {
    const el = render(new FakeLogs()).nativeElement as HTMLElement;

    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Logs');
    const rows = Array.from(el.querySelectorAll('tbody tr')).map((row) =>
      Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent!.trim()),
    );
    expect(rows).toEqual([
      [
        '77',
        '2026-11-03 06:05',
        'ERROR',
        'newstrading.collectors.rss',
        'collector',
        'feed unavailable',
        'collect',
        '142',
        'TimeoutError: 30s',
        '{"url":"https://example.test/feed"}',
      ],
      [
        '76',
        '2026-11-03 06:00',
        'INFO',
        'newstrading.cli',
        'cli',
        'collect finished',
        '—',
        '—',
        '—',
        '—',
      ],
    ]);

    const pills = Array.from(el.querySelectorAll('tbody .pill')).map((pill) =>
      (['err', 'warn', 'ok', 'muted'] as const).filter((tone) => pill.classList.contains(tone)),
    );
    expect(pills).toEqual([['err'], ['ok']]);
  });

  it('renders the empty state for an empty answer', () => {
    const fake = new FakeLogs();
    fake.answer = { items: [], total: 0, page: 1, per_page: 50 };
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="empty"]')?.textContent).toContain('No log lines');
  });

  it('renders an error line with the status when the call fails', () => {
    const fake = new FakeLogs();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="error"]')?.textContent).toContain('HTTP 503');
  });

  it('filters by the level the user picked', () => {
    const fake = new FakeLogs();
    const el = render(fake).nativeElement as HTMLElement;

    const select = el.querySelector<HTMLSelectElement>('.toolbar select')!;
    select.value = 'ERROR';
    select.dispatchEvent(new Event('change'));
    TestBed.tick();

    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 50, level: 'ERROR' });
  });

  it('offers the four page sizes, sends the picked one and restarts at page 1', () => {
    const fake = new FakeLogs();
    fake.answer = pageOf(logRowsFixture(), 120);
    const fixture = render(fake);
    const el = fixture.nativeElement as HTMLElement;

    const options = Array.from(el.querySelectorAll<HTMLOptionElement>('.pager select option'));
    expect(options.map((option) => option.value)).toEqual(['25', '50', '100', '200']);

    const select = el.querySelector<HTMLSelectElement>('.pager select')!;
    expect(select.value).toBe('50');

    TestBed.inject(LogsStore).setPage(3);
    TestBed.tick();
    fixture.detectChanges();
    expect(el.querySelector('.pager span')?.textContent).toContain('page 3 / 3');

    select.value = '100';
    select.dispatchEvent(new Event('change'));
    TestBed.tick();
    fixture.detectChanges();

    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 100, level: null });
    expect(el.querySelector('.pager span')?.textContent).toContain('page 1 / 2');
  });

  it('says so when a page beyond the last one was clamped', () => {
    const fake = new FakeLogs();
    fake.answer = pageOf(logRowsFixture(), 120);
    const fixture = render(fake);
    const el = fixture.nativeElement as HTMLElement;

    TestBed.inject(LogsStore).setPage(99);
    TestBed.tick();
    fixture.detectChanges();

    expect(el.querySelector('[data-testid="page-notice"]')?.textContent).toContain('page 3');
  });
});
