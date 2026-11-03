import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

/**
 * Every unknown route renders this component instead of a blank page: the shell, the navigation
 * and the footer stay, and the way back to the overview is one click away.
 */
@Component({
  selector: 'app-not-found',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <section class="screen" data-testid="not-found">
      <h1>Page not found</h1>
      <p class="hint">There is no screen at this address.</p>
      <p><a routerLink="/">Back to the overview</a></p>
    </section>
  `,
})
export class NotFound {}
