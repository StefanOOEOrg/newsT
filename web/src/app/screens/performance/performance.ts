import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { PerformanceStore } from './performance.store';

/**
 * The performance screen `/performance` - *Was it right?*
 *
 * The hit rate per horizon (1d, 3d, 7d) and per alert type, exactly as `/api/performance`
 * aggregates it; the store maps the answer, the component renders it (#72).
 */
@Component({
  selector: 'app-performance',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './performance.html',
})
export class Performance {
  protected readonly store = inject(PerformanceStore);
}
