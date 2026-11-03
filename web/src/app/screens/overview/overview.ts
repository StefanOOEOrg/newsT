import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Placeholder for the overview screen `/` - *Is it running?*
 *
 * The real screen (counters, the last collector run, the database size) arrives with #58; this
 * component only proves the route, the shell and the layout.
 */
@Component({
  selector: 'app-overview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="screen">
      <h1>Overview</h1>
      <p class="hint">
        Is it running? The counters, the last collector run and the database size arrive with #58.
      </p>
    </section>
  `,
})
export class Overview {}
