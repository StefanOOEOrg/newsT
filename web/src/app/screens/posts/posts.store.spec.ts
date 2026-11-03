import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { Page, PostRow } from '../../api/models';
import { PostsQuery, PostsService } from '../../api/posts.service';
import { pageOf, postRowsFixture } from '../../api/testing/fixtures';
import { PostsStore } from './posts.store';

/** In-memory `/api/posts` answer of the spec; it remembers every query it was asked. */
class FakePosts {
  answer: Page<PostRow> = pageOf(postRowsFixture());
  failure: HttpErrorResponse | null = null;
  readonly queries: PostsQuery[] = [];

  list(query: PostsQuery): Observable<Page<PostRow>> {
    this.queries.push(query);
    return this.failure ? throwError(() => this.failure) : of(structuredClone(this.answer));
  }
}

function setup(fake: FakePosts): PostsStore {
  TestBed.configureTestingModule({ providers: [{ provide: PostsService, useValue: fake }] });
  const store = TestBed.inject(PostsStore);
  TestBed.tick();
  return store;
}

describe('PostsStore', () => {
  it('maps the full payload onto its signals', () => {
    const fake = new FakePosts();
    const store = setup(fake);

    expect(fake.queries).toEqual([{ page: 1, per_page: 25, asset_id: null, source: null }]);
    expect(store.items()).toEqual(postRowsFixture());
    expect(store.total()).toBe(2);
    expect(store.loading()).toBe(false);
    expect(store.error()).toBeNull();
    expect(store.empty()).toBe(false);
    expect(store.rows().map((row) => row.title)).toEqual([
      'Apple supplier reports a record quarter',
      '—',
    ]);
    expect(store.rows()[0]).toEqual({
      id: 501,
      asset: 'AAPL',
      source: 'rss',
      title: 'Apple supplier reports a record quarter',
      url: 'https://example.test/p/501',
      score: '88',
      created: '2026-11-03 05:41',
      sentiment: 'bullish',
      sentimentScore: '0.72',
      category: 'earnings',
      summary: 'The supplier beat estimates and raised guidance.',
    });
  });

  it('maps an empty payload to the empty state', () => {
    const fake = new FakePosts();
    fake.answer = { items: [], total: 0, page: 1, per_page: 25 };
    const store = setup(fake);

    expect(store.items()).toEqual([]);
    expect(store.total()).toBe(0);
    expect(store.empty()).toBe(true);
    expect(store.rows()).toEqual([]);
  });

  it('keeps null fields null and shows an em dash instead of 0', () => {
    const fake = new FakePosts();
    const store = setup(fake);

    expect(store.items()[1].asset).toBeNull();
    expect(store.items()[1].score).toBeNull();
    expect(store.items()[1].sentiment_score).toBeNull();
    expect(store.rows()[1]).toEqual({
      id: 500,
      asset: '—',
      source: 'newsapi',
      title: '—',
      url: null,
      score: '—',
      created: '2026-11-03 04:20',
      sentiment: '—',
      sentimentScore: '—',
      category: '—',
      summary: '—',
    });
  });

  it('sets the error signal with the status when the call fails', () => {
    const fake = new FakePosts();
    fake.failure = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    const store = setup(fake);

    expect(store.error()).toEqual({ status: 503, message: 'Service Unavailable' });
    expect(store.items()).toEqual([]);
    expect(store.empty()).toBe(false);
    expect(store.loading()).toBe(false);
  });

  it('pages through the list and asks the endpoint for the next window', () => {
    const fake = new FakePosts();
    fake.answer = pageOf(postRowsFixture(), 120);
    const store = setup(fake);

    expect(store.pages()).toBe(5);
    expect(store.hasPrevious()).toBe(false);
    expect(store.hasNext()).toBe(true);

    store.next();
    TestBed.tick();

    expect(store.page()).toBe(2);
    expect(fake.queries.at(-1)).toEqual({ page: 2, per_page: 25, asset_id: null, source: null });

    store.previous();
    TestBed.tick();
    expect(store.page()).toBe(1);
    expect(fake.queries.at(-1)?.page).toBe(1);
  });

  it('sends the asset and source filters, resets to page 1 and knows an empty filter result', () => {
    const fake = new FakePosts();
    const store = setup(fake);
    expect(store.filtered()).toBe(false);

    store.setPage(3);
    TestBed.tick();

    store.setAsset('7');
    TestBed.tick();
    expect(store.assetId()).toBe(7);
    expect(store.page()).toBe(1);
    expect(store.filtered()).toBe(true);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 25, asset_id: 7, source: null });

    store.setSource('rss');
    TestBed.tick();
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 25, asset_id: 7, source: 'rss' });

    store.setAsset('');
    store.setSource('  ');
    TestBed.tick();
    expect(store.filtered()).toBe(false);
    expect(fake.queries.at(-1)).toEqual({ page: 1, per_page: 25, asset_id: null, source: null });
  });

  it('asks the endpoint exactly once per page change', () => {
    const fake = new FakePosts();
    fake.answer = pageOf(postRowsFixture(), 120);
    const store = setup(fake);
    const before = fake.queries.length;

    store.next();
    TestBed.tick();
    expect(fake.queries.length).toBe(before + 1);
    expect(fake.queries.at(-1)?.page).toBe(2);

    store.setPage(4);
    TestBed.tick();
    expect(fake.queries.length).toBe(before + 2);
    expect(fake.queries.at(-1)?.page).toBe(4);

    store.previous();
    TestBed.tick();
    expect(fake.queries.length).toBe(before + 3);
    expect(fake.queries.at(-1)?.page).toBe(3);
  });

  it('clamps a page beyond the last one to the last page and says so', () => {
    const fake = new FakePosts();
    fake.answer = pageOf(postRowsFixture(), 60);
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

    store.previous();
    TestBed.tick();
    expect(store.pageNotice()).toBeNull();
  });

  it('changes the page size, starts again at page 1 and keeps the window inside the list', () => {
    const fake = new FakePosts();
    fake.answer = pageOf(postRowsFixture(), 300);
    const store = setup(fake);

    store.setPage(3);
    TestBed.tick();

    store.setPerPage(100);
    TestBed.tick();

    expect(store.perPage()).toBe(100);
    expect(store.page()).toBe(1);
    expect(fake.queries.at(-1)).toEqual({
      page: 1,
      per_page: 100,
      asset_id: null,
      source: null,
    });
    expect(store.pages()).toBe(3);
  });
});
