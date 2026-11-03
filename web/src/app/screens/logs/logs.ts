import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { LOG_LEVELS, LogsStore } from './logs.store';

/**
 * The logs screen `/logs` - *What went wrong?*
 *
 * `system_logs`, newest first, one level pill per line, the level filter and the pager. The store
 * owns the window, the filter and the request (#58).
 */
@Component({
  selector: 'app-logs',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './logs.html',
})
export class Logs {
  protected readonly store = inject(LogsStore);
  /** The levels Python logging writes into `system_logs.level`. */
  protected readonly levels = LOG_LEVELS;
}
