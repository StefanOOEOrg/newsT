import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { dash, fixed, signedPercent, stamp, yesNo } from '../../api/format';
import { Failure, toFailure } from '../../api/http-failure';
import { AlertRow, AlertView } from '../../api/models';
import { AlertsQuery, AlertsService } from '../../api/alerts.service';

/** Rows the alerts table asks for per page. */
export const ALERTS_PER_PAGE = 25;

/** The severities of `alerts.severity` (comment on the column in `sql/schema.sql`). */
export const SEVERITIES = ['low', 'medium', 'high', 'critical'] as const;

/**
 * Signal store of `/alerts` - *What fired?*
 *
 * Same shape as the posts store: the query is derived from the window and the severity filter, so
 * a filter change reloads and jumps back to page 1.
 */
@Injectable({ providedIn: 'root' })
export class AlertsStore {
  private readonly api = inject(AlertsService);

  readonly items = signal<AlertRow[]>([]);
  readonly total = signal(0);
  readonly page = signal(1);
  readonly perPage = signal(ALERTS_PER_PAGE);
  readonly severity = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal<Failure | null>(null);

  private readonly request = signal(0);

  readonly query = computed<AlertsQuery>(() => ({
    page: this.page(),
    per_page: this.perPage(),
    severity: this.severity(),
  }));

  /** True when the severity filter is set; the empty state names the filter then. */
  readonly filtered = computed(() => this.severity() !== null);

  readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / this.perPage())));
  readonly hasPrevious = computed(() => this.page() > 1);
  readonly hasNext = computed(() => this.page() < this.pages());

  /** The rows as the table prints them; unjudged performance rows are the em dash. */
  readonly rows = computed<AlertView[]>(() =>
    this.items().map((row) => ({
      id: row.id,
      asset: dash(row.asset),
      alertType: dash(row.alert_type),
      severity: dash(row.severity),
      description: dash(row.description),
      confidence: fixed(row.confidence_score, 2),
      timestamp: stamp(row.timestamp),
      notified: yesNo(row.notified),
      return7d: signedPercent(row.return_7d),
      correct7d: yesNo(row.correct_7d),
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
    this.page.set(Math.min(Math.max(1, Math.trunc(page)), this.pages()));
  }

  next(): void {
    this.setPage(this.page() + 1);
  }

  previous(): void {
    this.setPage(this.page() - 1);
  }

  /** Filter by `alerts.severity`; a blank choice means every severity. */
  setSeverity(severity: string): void {
    const trimmed = severity.trim();
    this.severity.set(trimmed === '' ? null : trimmed);
    this.page.set(1);
  }
}
