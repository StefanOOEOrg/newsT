import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { dash, fixed, stamp } from '../../api/format';
import { Failure, toFailure } from '../../api/http-failure';
import { PostRow, PostView } from '../../api/models';
import { PostsQuery, PostsService } from '../../api/posts.service';
import { clampPage, pageNoticeFor } from '../paging';

/** Rows the posts table asks for per page. */
export const POSTS_PER_PAGE = 25;

/**
 * Signal store of `/posts` - *What did it find?*
 *
 * Window (`page`, `per_page`) and filters (`asset_id`, `source`) are signals; the `query` computed
 * derives the request from them, so the effect reloads exactly when one of them changes. A new
 * filter always starts at page 1.
 */
@Injectable({ providedIn: 'root' })
export class PostsStore {
  private readonly api = inject(PostsService);

  readonly items = signal<PostRow[]>([]);
  readonly total = signal(0);
  readonly page = signal(1);
  readonly perPage = signal(POSTS_PER_PAGE);
  readonly assetId = signal<number | null>(null);
  readonly source = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal<Failure | null>(null);

  /** The sentence of the last clamped jump, `null` for a normal move; the pager prints it. */
  readonly pageNotice = signal<string | null>(null);

  /** Bumped by `reload()` and read by the effect only. */
  private readonly request = signal(0);

  /** The window and the filters of the next call. */
  readonly query = computed<PostsQuery>(() => ({
    page: this.page(),
    per_page: this.perPage(),
    asset_id: this.assetId(),
    source: this.source(),
  }));

  /** True when a filter is set, so an empty answer can say *why* it is empty. */
  readonly filtered = computed(() => this.assetId() !== null || this.source() !== null);

  /** Number of pages at the current page size; at least 1, so `1 / 1` is shown for an empty list. */
  readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / this.perPage())));
  readonly hasPrevious = computed(() => this.page() > 1);
  readonly hasNext = computed(() => this.page() < this.pages());

  /** The rows as the table prints them; a `null` column becomes the em dash. */
  readonly rows = computed<PostView[]>(() =>
    this.items().map((row) => ({
      id: row.id,
      asset: dash(row.asset),
      source: row.source,
      title: dash(row.title),
      url: row.url,
      score: dash(row.score),
      created: stamp(row.created_at),
      sentiment: dash(row.sentiment),
      sentimentScore: fixed(row.sentiment_score, 2),
      category: dash(row.category),
      summary: dash(row.summary),
    })),
  );

  /** True when the answer was a real, empty page - never while loading and never on a failure. */
  readonly empty = computed(
    () => !this.loading() && this.error() === null && this.items().length === 0,
  );

  constructor() {
    effect(() => {
      this.query();
      this.request();
      untracked(() => this.load());
    });
  }

  /** Load the current window; the effect calls this on creation and on every change. */
  load(): void {
    this.loading.set(true);
    this.api.list(this.query()).subscribe({
      next: (answer) => {
        this.items.set(answer.items);
        this.total.set(answer.total);
        this.error.set(null);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.error.set(toFailure(error));
        this.items.set([]);
        this.total.set(0);
        this.loading.set(false);
      },
    });
  }

  /** Ask for a fresh answer of the current window. */
  reload(): void {
    this.request.update((count) => count + 1);
  }

  /** Jump to `page`, clamped to the pages the answer reported; a jump past the end says so. */
  setPage(page: number): void {
    const target = clampPage(page, this.pages());
    this.pageNotice.set(pageNoticeFor(target));
    this.page.set(target.page);
  }

  /** Pick one of `PAGE_SIZES`; the list starts again at page 1, so the window stays valid. */
  setPerPage(size: number): void {
    this.perPage.set(size);
    this.pageNotice.set(null);
    this.page.set(1);
  }

  next(): void {
    this.setPage(this.page() + 1);
  }

  previous(): void {
    this.setPage(this.page() - 1);
  }

  /** Filter by `social_posts.asset_id`; a blank field means every asset. */
  setAsset(term: string): void {
    this.assetId.set(assetIdOf(term));
    this.pageNotice.set(null);
    this.page.set(1);
  }

  /** Filter by `social_posts.source`; a blank field means every source. */
  setSource(term: string): void {
    const trimmed = term.trim();
    this.source.set(trimmed === '' ? null : trimmed);
    this.pageNotice.set(null);
    this.page.set(1);
  }
}

/** Parse the asset filter field: a positive integer, otherwise "no filter". */
function assetIdOf(term: string): number | null {
  const trimmed = term.trim();
  if (trimmed === '') {
    return null;
  }
  const value = Number(trimmed);
  return Number.isInteger(value) && value > 0 ? value : null;
}
