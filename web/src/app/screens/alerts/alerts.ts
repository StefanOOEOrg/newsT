import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { AlertsStore, SEVERITIES } from './alerts.store';

/**
 * The alerts screen `/alerts` - *What fired?*
 *
 * One row per alert with its 7-day return and the correctness flag, the severity filter and the
 * pager. The store owns the window, the filter and the request (#58).
 */
@Component({
  selector: 'app-alerts',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './alerts.html',
})
export class Alerts {
  protected readonly store = inject(AlertsStore);
  /** The values of `alerts.severity`, as the column comment documents them. */
  protected readonly severities = SEVERITIES;
}
