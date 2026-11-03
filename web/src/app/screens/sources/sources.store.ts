import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { dash, stamp, yesNo } from '../../api/format';
import { Failure, toFailure } from '../../api/http-failure';
import { SourceRow, SourceView, SourcesSummary } from '../../api/models';
import { SourcesService } from '../../api/sources.service';

/**
 * Signal store of `/sources` - *Which sources are healthy?*
 *
 * The endpoint answers every collector in one list (it is not paged), so the store has no window
 * and no filter: one signal for the rows, three counters derived from it.
 */
@Injectable({ providedIn: 'root' })
export class SourcesStore {
  private readonly api = inject(SourcesService);

  readonly items = signal<SourceRow[]>([]);
  readonly loading = signal(false);
  readonly error = signal<Failure | null>(null);

  private readonly request = signal(0);

  /** The rows as the table prints them; "no limit" and "never ran" are the em dash. */
  readonly rows = computed<SourceView[]>(() =>
    this.items().map((row) => ({
      collector: row.collector,
      lastRun: stamp(row.last_run),
      calls: dash(row.calls_today),
      failures: dash(row.failures_today),
      totalErrors: dash(row.total_errors),
      quotaLimit: dash(row.quota_limit),
      quotaRemaining: dash(row.quota_remaining),
      enabled: yesNo(row.enabled),
    })),
  );

  /** How many collectors there are, how many failed today, how many are switched off. */
  readonly summary = computed<SourcesSummary>(() => ({
    collectors: dash(this.items().length),
    failing: dash(this.items().filter((row) => row.failures_today > 0).length),
    disabled: dash(this.items().filter((row) => !row.enabled).length),
  }));

  readonly empty = computed(
    () => !this.loading() && this.error() === null && this.items().length === 0,
  );

  constructor() {
    effect(() => {
      this.request();
      untracked(() => this.load());
    });
  }

  load(): void {
    this.loading.set(true);
    this.api.list().subscribe({
      next: (answer) => {
        this.items.set(answer.items);
        this.error.set(null);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.error.set(toFailure(error));
        this.items.set([]);
        this.loading.set(false);
      },
    });
  }

  reload(): void {
    this.request.update((count) => count + 1);
  }
}
