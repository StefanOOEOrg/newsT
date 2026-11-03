import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { Page, SourceRow } from '../../api/models';
import { SourcesService } from '../../api/sources.service';
import { pageOf, sourceRowsFixture } from '../../api/testing/fixtures';
import { Sources } from './sources';

/** In-memory `/api/sources` answer of the spec. */
class FakeSources {
  answer: Page<SourceRow> = pageOf(sourceRowsFixture());
  failure: HttpErrorResponse | null = null;

  list(): Observable<Page<SourceRow>> {
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function render(fake: FakeSources): ComponentFixture<Sources> {
  TestBed.configureTestingModule({ providers: [{ provide: SourcesService, useValue: fake }] });
  const fixture = TestBed.createComponent(Sources);
  TestBed.tick();
  fixture.detectChanges();
  return fixture;
}

describe('Sources screen', () => {
  it('renders one row per collector of the fixture', () => {
    const el = render(new FakeSources()).nativeElement as HTMLElement;

    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Sources');
    const rows = Array.from(el.querySelectorAll('tbody tr')).map((row) =>
      Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent!.trim()),
    );
    expect(rows).toEqual([
      ['rss', '2026-11-03 06:15', '120', '2', '3', '—', '—', 'yes'],
      ['newsapi', '—', '0', '0', '0', '100', '100', 'no'],
    ]);
    expect(
      Array.from(el.querySelectorAll('.card-value')).map((node) => node.textContent?.trim()),
    ).toEqual(['2', '1', '1']);
  });

  it('renders the empty state when no collector is configured', () => {
    const fake = new FakeSources();
    fake.answer = { items: [], total: 0, page: 1, per_page: 50 };
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="empty"]')?.textContent).toContain(
      'No collector is configured',
    );
  });

  it('renders an error line with the status when the call fails', () => {
    const fake = new FakeSources();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="error"]')?.textContent).toContain('HTTP 503');
  });
});
