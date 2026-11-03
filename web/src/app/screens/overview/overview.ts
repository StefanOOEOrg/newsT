import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { OverviewStore } from './overview.store';

/**
 * The overview screen `/` - *Is it running?*
 *
 * Counters, the last collector run and the database size. The component only reads the store's
 * signals; loading, errors and the empty state live there (#58).
 */
@Component({
  selector: 'app-overview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './overview.html',
})
export class Overview {
  protected readonly store = inject(OverviewStore);
}
