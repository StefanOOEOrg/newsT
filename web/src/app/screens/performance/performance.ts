import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { PerformanceStore } from './performance.store';

/**
 * The performance screen `/performance` - *Was it right?*
 *
 * The hit rate overall, per alert type and for the one horizon the API reports (7 days). The
 * aggregation lives in the store; the component renders it (#58).
 */
@Component({
  selector: 'app-performance',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './performance.html',
})
export class Performance {
  protected readonly store = inject(PerformanceStore);
}
