import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { DASH, dash } from '../../api/format';
import { Failure, toFailure } from '../../api/http-failure';
import { HorizonView, PerformanceAnswer, PerformanceView } from '../../api/models';
import { PerformanceService } from '../../api/performance.service';

/**
 * Signal store of `/performance` - *Was it right?*
 *
 * The screen shows what `/api/performance` computes (#69): the three correctness horizons (1d, 3d,
 * 7d) and the rows per alert type for the 7d horizon. Nothing is aggregated over alert rows here -
 * the database counts once, the store only maps. A `hit_rate` of `null` means "no alert in this
 * horizon" and stays `null` up to the template, which prints the em dash; a real `0` prints as
 * `0 %`.
 */
@Injectable({ providedIn: 'root' })
export class PerformanceStore {
  private readonly api = inject(PerformanceService);

  /** The last answer of `/api/performance`; `null` before the first call and after a failure. */
  readonly answer = signal<PerformanceAnswer | null>(null);
  readonly loading = signal(false);
  readonly error = signal<Failure | null>(null);

  private readonly request = signal(0);

  /** The horizons in the order the API returns them: `1d`, `3d`, `7d`. */
  readonly horizons = computed<HorizonView[]>(() =>
    (this.answer()?.horizons ?? []).map((row) => ({
      horizon: dash(row.horizon),
      alerts: dash(row.alerts),
      correct: dash(row.correct),
      misses: dash(row.alerts - row.correct),
      rate: percent(row.hit_rate),
    })),
  );

  /** The per-alert-type rows of the 7d horizon, in the order the API returns them. */
  readonly rows = computed<PerformanceView[]>(() =>
    (this.answer()?.by_type ?? []).map((row) => ({
      alertType: dash(row.alert_type),
      horizon: dash(row.horizon),
      alerts: dash(row.alerts),
      correct: dash(row.correct),
      misses: dash(row.alerts - row.correct),
      rate: percent(row.hit_rate),
    })),
  );

  /** True when the API has nothing to judge: no alert in any horizon and no per-type row. */
  readonly empty = computed(() => {
    const answer = this.answer();
    return (
      !this.loading() &&
      this.error() === null &&
      answer !== null &&
      answer.by_type.length === 0 &&
      answer.horizons.every((row) => row.alerts === 0)
    );
  });

  constructor() {
    effect(() => {
      this.request();
      untracked(() => this.load());
    });
  }

  /** Ask `/api/performance` once; the effect calls this on creation and on reload. */
  load(): void {
    this.loading.set(true);
    this.api.get().subscribe({
      next: (answer) => {
        this.answer.set(answer);
        this.error.set(null);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.error.set(toFailure(error));
        this.answer.set(null);
        this.loading.set(false);
      },
    });
  }

  reload(): void {
    this.request.update((count) => count + 1);
  }
}

/**
 * The `hit_rate` of one horizon or type as the tables print it.
 *
 * `null` (nothing judged) is the em dash, never `0 %`; a real `0.0` is `0 %`; a whole percentage
 * drops the useless decimal (`100 %`), everything else keeps one (`62.5 %`).
 */
function percent(value: number | null): string {
  if (value === null) {
    return DASH;
  }
  const points = Math.round(value * 1000) / 10;
  return `${Number.isInteger(points) ? points : points.toFixed(1)} %`;
}
