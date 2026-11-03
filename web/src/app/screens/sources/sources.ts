import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Placeholder for `/sources` - *Which sources are healthy?*
 *
 * The real screen (per collector: calls today, failures, last run, quota remaining) arrives with
 * #58; this component only proves the route, the shell and the layout.
 */
@Component({
  selector: 'app-sources',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="screen">
      <h1>Sources</h1>
      <p class="hint">
        Which sources are healthy? Calls, failures, the last run and the quota remaining arrive with
        #58.
      </p>
    </section>
  `,
})
export class Sources {}
