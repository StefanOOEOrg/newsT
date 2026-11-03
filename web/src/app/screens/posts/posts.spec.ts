import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { Page, PostRow } from '../../api/models';
import { PostsQuery, PostsService } from '../../api/posts.service';
import { pageOf, postRowsFixture } from '../../api/testing/fixtures';
import { Posts } from './posts';

/** In-memory `/api/posts` answer of the spec. */
class FakePosts {
  answer: Page<PostRow> = pageOf(postRowsFixture());
  failure: HttpErrorResponse | null = null;
  readonly queries: PostsQuery[] = [];

  list(query: PostsQuery): Observable<Page<PostRow>> {
    this.queries.push(query);
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function render(fake: FakePosts): ComponentFixture<Posts> {
  TestBed.configureTestingModule({ providers: [{ provide: PostsService, useValue: fake }] });
  const fixture = TestBed.createComponent(Posts);
  TestBed.tick();
  fixture.detectChanges();
  return fixture;
}

function rows(el: HTMLElement): string[][] {
  return Array.from(el.querySelectorAll('tbody tr')).map((row) =>
    Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent!.trim()),
  );
}

describe('Posts screen', () => {
  it('renders one row per item of the fixture', () => {
    const el = render(new FakePosts()).nativeElement as HTMLElement;

    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Posts');
    expect(rows(el)).toEqual([
      [
        '501',
        'AAPL',
        'rss',
        'Apple supplier reports a record quarter',
        '88',
        '2026-11-03 05:41',
        'bullish',
        '0.72',
        'earnings',
        'The supplier beat estimates and raised guidance.',
      ],
      ['500', '—', 'newsapi', '—', '—', '2026-11-03 04:20', '—', '—', '—', '—'],
    ]);
  });

  it('renders the empty state for an empty answer', () => {
    const fake = new FakePosts();
    fake.answer = { items: [], total: 0, page: 1, per_page: 25 };
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="empty"]')?.textContent).toContain('No posts yet');
  });

  it('renders an error line with the status when the call fails', () => {
    const fake = new FakePosts();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const el = render(fake).nativeElement as HTMLElement;

    expect(el.querySelector('tbody')).toBeNull();
    expect(el.querySelector('[data-testid="error"]')?.textContent).toContain('HTTP 503');
  });

  it('sends the asset and the source filter the user typed', () => {
    const fake = new FakePosts();
    const el = render(fake).nativeElement as HTMLElement;

    const inputs = el.querySelectorAll<HTMLInputElement>('.toolbar input');
    inputs[0].value = '7';
    inputs[0].dispatchEvent(new Event('change'));
    TestBed.tick();
    expect(fake.queries.at(-1)?.asset_id).toBe(7);

    inputs[1].value = 'rss';
    inputs[1].dispatchEvent(new Event('change'));
    TestBed.tick();
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 25, asset_id: 7, source: 'rss' });
  });

  it('pages forward and back with the pager', () => {
    const fake = new FakePosts();
    fake.answer = pageOf(postRowsFixture(), 120);
    const el = render(fake).nativeElement as HTMLElement;

    const [previous, next] = Array.from(el.querySelectorAll<HTMLButtonElement>('.pager button'));
    expect(previous.disabled).toBe(true);

    next.click();
    TestBed.tick();
    expect(fake.queries.at(-1)?.page).toBe(2);
  });
});
