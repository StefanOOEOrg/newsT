import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Placeholder for `/logs` - *What went wrong?*
 *
 * The real screen (paged `system_logs`, newest first, filter by level) arrives with #58; this
 * component only proves the route, the shell and the layout.
 */
@Component({
  selector: 'app-logs',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="screen">
      <h1>Logs</h1>
      <p class="hint">
        What went wrong? The paged system logs with the level filter arrive with #58.
      </p>
    </section>
  `,
})
export class Logs {}
