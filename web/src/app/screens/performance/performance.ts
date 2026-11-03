import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Placeholder for `/performance` - *Was it right?*
 *
 * The real screen (hit rate per horizon, per alert type, from `alert_performance`) arrives with
 * #58; this component only proves the route, the shell and the layout.
 */
@Component({
  selector: 'app-performance',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="screen">
      <h1>Performance</h1>
      <p class="hint">
        Was it right? The hit rate per horizon and per alert type arrives with #58.
      </p>
    </section>
  `,
})
export class Performance {}
