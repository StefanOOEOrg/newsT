import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { bytes, stamp } from '../../api/format';
import { Failure, toFailure } from '../../api/http-failure';
import { Overview, OverviewCard } from '../../api/models';
import { OverviewService } from '../../api/overview.service';

/**
 * Signal store of the overview screen `/` - *Is it running?*
 *
 * State is a signal, the card row is `computed()`, and one `effect()` performs the initial load
 * (and every reload the refresh button asks for). Zoneless: the component reads only these
 * signals, so nothing can change without a re-render.
 */
@Injectable({ providedIn: 'root' })
export class OverviewStore {
  private readonly api = inject(OverviewService);

  /** The last answer; `null` until the first one arrives. */
  readonly data = signal<Overview | null>(null);
  readonly loading = signal(false);
  readonly error = signal<Failure | null>(null);

  /** Bumped by `reload()`; the effect below is the only reader. */
  private readonly request = signal(0);

  /**
   * True on a reachable but empty database: every counter is zero and no collector has run.
   *
   * The screen renders its empty state on this flag, never a card row of zeros.
   */
  readonly empty = computed(() => {
    const data = this.data();
    return (
      data !== null &&
      this.error() === null &&
      data.assets === 0 &&
      data.posts === 0 &&
      data.analyses === 0 &&
      data.alerts === 0
    );
  });

  /** The cards the screen renders; empty on an empty database and on a failure. */
  readonly cards = computed<OverviewCard[]>(() => {
    const data = this.data();
    if (data === null || this.empty()) {
      return [];
    }
    return [
      { key: 'assets', label: 'Assets', value: String(data.assets) },
      { key: 'posts', label: 'Posts', value: String(data.posts) },
      { key: 'analyses', label: 'Analyses', value: String(data.analyses) },
      { key: 'alerts', label: 'Alerts', value: String(data.alerts) },
      { key: 'open_alerts', label: 'Open alerts', value: String(data.open_alerts) },
      {
        key: 'last_collector_run',
        label: 'Last collector run',
        value: stamp(data.last_collector_run),
      },
      {
        key: 'database_size_bytes',
        label: 'Database size',
        value: bytes(data.database_size_bytes),
      },
    ];
  });

  constructor() {
    effect(() => {
      this.request();
      untracked(() => this.load());
    });
  }

  /** Load the overview now; the effect calls this on creation and on every `reload()`. */
  load(): void {
    this.loading.set(true);
    this.api.get().subscribe({
      next: (data) => {
        this.data.set(data);
        this.error.set(null);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.error.set(toFailure(error));
        this.loading.set(false);
      },
    });
  }

  /** Ask for a fresh answer; the effect survives the request so the screen keeps its data. */
  reload(): void {
    this.request.update((count) => count + 1);
  }
}
