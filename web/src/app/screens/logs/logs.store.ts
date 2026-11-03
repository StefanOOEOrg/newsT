import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { dash, levelTone, metadataText, stamp } from '../../api/format';
import { Failure, toFailure } from '../../api/http-failure';
import { LogRow, LogView } from '../../api/models';
import { LogsQuery, LogsService } from '../../api/logs.service';
import { clampPage, pageNoticeFor } from '../paging';

/** Rows the log table asks for per page. */
export const LOGS_PER_PAGE = 50;

/** The levels a Python logging setup writes into `system_logs.level`. */
export const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const;

/**
 * Signal store of `/logs` - *What went wrong?*
 *
 * Window and level filter are signals, the query is derived from them, the effect loads.
 */
@Injectable({ providedIn: 'root' })
export class LogsStore {
  private readonly api = inject(LogsService);

  readonly items = signal<LogRow[]>([]);
  readonly total = signal(0);
  readonly page = signal(1);
  readonly perPage = signal(LOGS_PER_PAGE);
  readonly level = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal<Failure | null>(null);

  /** The sentence of the last clamped jump, `null` for a normal move; the pager prints it. */
  readonly pageNotice = signal<string | null>(null);

  private readonly request = signal(0);

  readonly query = computed<LogsQuery>(() => ({
    page: this.page(),
    per_page: this.perPage(),
    level: this.level(),
  }));

  /** True when the level filter is set; the empty state names the filter then. */
  readonly filtered = computed(() => this.level() !== null);

  readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / this.perPage())));
  readonly hasPrevious = computed(() => this.page() > 1);
  readonly hasNext = computed(() => this.page() < this.pages());

  /** The rows as the table prints them; the level pill carries the colour tone of the level. */
  readonly rows = computed<LogView[]>(() =>
    this.items().map((row) => ({
      id: row.id,
      timestamp: stamp(row.timestamp),
      level: row.level,
      tone: levelTone(row.level),
      logger: dash(row.logger),
      service: dash(row.service),
      message: dash(row.message),
      function: dash(row.function),
      line: dash(row.line_number),
      exception: dash(row.exception),
      metadata: metadataText(row.metadata),
    })),
  );

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

  reload(): void {
    this.request.update((count) => count + 1);
  }

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

  /** Filter by `system_logs.level`; a blank choice means every level. */
  setLevel(level: string): void {
    const trimmed = level.trim();
    this.level.set(trimmed === '' ? null : trimmed);
    this.pageNotice.set(null);
    this.page.set(1);
  }
}
