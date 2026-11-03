import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { SourcesStore } from './sources.store';

/**
 * The sources screen `/sources` - *Which sources are healthy?*
 *
 * Per collector: calls today, failures, the last run and the quota remaining, with three counters
 * above the table. The store owns the state (#58).
 */
@Component({
  selector: 'app-sources',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sources.html',
})
export class Sources {
  protected readonly store = inject(SourcesStore);
}
