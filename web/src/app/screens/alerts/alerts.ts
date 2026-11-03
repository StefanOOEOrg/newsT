import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Placeholder for `/alerts` - *What fired?*
 *
 * The real screen (paged alerts with the 7-day return and the correctness flag, severity filter)
 * arrives with #58; this component only proves the route, the shell and the layout.
 */
@Component({
  selector: 'app-alerts',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="screen">
      <h1>Alerts</h1>
      <p class="hint">
        What fired? Paged alerts with the 7-day return and the severity filter arrive with #58.
      </p>
    </section>
  `,
})
export class Alerts {}
