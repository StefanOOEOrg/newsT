import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { dash, share, signedPercent } from '../../api/format';
import { Failure, toFailure } from '../../api/http-failure';
import { AlertRow, HorizonView, PerformanceView } from '../../api/models';
import { AlertsService } from '../../api/alerts.service';

/** The API caps `per_page` at 200; the walk asks for the largest page. */
export const WALK_PER_PAGE = 200;

/** How many pages the walk follows at most, so a wrong `total` cannot loop forever. */
export const MAX_PAGES = 10;

/**
 * Signal store of `/performance` - *Was it right?*
 *
 * There is no `/api/performance` endpoint in #56, so this store derives the hit rate from the
 * alerts themselves (`/api/alerts` carries `return_7d` and `correct_7d`): it walks the pages up to
 * `MAX_PAGES` and aggregates. An alert nobody judged yet (`correct_7d === null`) is *not* a miss -
 * it is left out of the denominator, which is why a fresh database shows the em dash, not `0 %`.
 */
@Injectable({ providedIn: 'root' })
export class PerformanceStore {
  private readonly api = inject(AlertsService);

  readonly items = signal<AlertRow[]>([]);
  readonly loading = signal(false);
  readonly error = signal<Failure | null>(null);

  private readonly request = signal(0);

  /** The alerts with a verdict for the 7-day horizon. */
  readonly judged = computed(() => this.items().filter((row) => row.correct_7d !== null));
  readonly evaluated = computed(() => this.judged().length);
  readonly hits = computed(() => this.judged().filter((row) => row.correct_7d === true).length);
  readonly misses = computed(() => this.evaluated() - this.hits());
  /** `null` when nothing was judged yet - the screen prints the em dash then. */
  readonly hitRate = computed(() => {
    const evaluated = this.evaluated();
    return evaluated === 0 ? null : this.hits() / evaluated;
  });
  readonly hitRateLabel = computed(() => share(this.hitRate()));
  readonly averageReturn = computed(() => average(this.items().map((row) => row.return_7d)));
  readonly averageReturnLabel = computed(() => signedPercent(this.averageReturn()));

  /** One row per alert type: how many were judged, how many were right, the rate and the return. */
  readonly rows = computed<PerformanceView[]>(() => {
    const groups = new Map<string, AlertRow[]>();
    for (const row of this.items()) {
      const key = dash(row.alert_type);
      const bucket = groups.get(key) ?? [];
      bucket.push(row);
      groups.set(key, bucket);
    }
    return [...groups.entries()].map(([alertType, rows]) => {
      const judged = rows.filter((row) => row.correct_7d !== null);
      const hits = judged.filter((row) => row.correct_7d === true).length;
      const rate = judged.length === 0 ? null : hits / judged.length;
      return {
        alertType,
        evaluated: dash(judged.length),
        hits: dash(hits),
        misses: dash(judged.length - hits),
        rate: share(rate),
        averageReturn: signedPercent(average(rows.map((row) => row.return_7d))),
      };
    });
  });

  /** The horizon the API reports; #56 exposes the 7-day performance only. */
  readonly horizons = computed<HorizonView[]>(() =>
    this.items().length === 0
      ? []
      : [
          {
            horizon: '7d',
            evaluated: dash(this.evaluated()),
            hits: dash(this.hits()),
            misses: dash(this.misses()),
            rate: this.hitRateLabel(),
          },
        ],
  );

  readonly empty = computed(
    () => !this.loading() && this.error() === null && this.items().length === 0,
  );

  constructor() {
    effect(() => {
      this.request();
      untracked(() => this.load());
    });
  }

  /** Walk the alert pages and aggregate; the effect calls this on creation and on reload. */
  load(): void {
    this.loading.set(true);
    this.walk(1, []);
  }

  reload(): void {
    this.request.update((count) => count + 1);
  }

  /** Fetch one page and continue until `total` rows were read, the walk cap is reached or a page is empty. */
  private walk(page: number, collected: AlertRow[]): void {
    this.api.list({ page, per_page: WALK_PER_PAGE, severity: null }).subscribe({
      next: (answer) => {
        const all = [...collected, ...answer.items];
        const more = answer.items.length > 0 && all.length < answer.total && page < MAX_PAGES;
        if (more) {
          this.walk(page + 1, all);
          return;
        }
        this.items.set(all);
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
}

/** Mean of the known values; `null` when there is none. */
function average(values: readonly (number | null)[]): number | null {
  const known = values.filter((value): value is number => value !== null);
  if (known.length === 0) {
    return null;
  }
  return known.reduce((sum, value) => sum + value, 0) / known.length;
}
