import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Placeholder for `/posts` - *What did it find?*
 *
 * The real screen (paged posts joined with their analysis, filters by asset and source) arrives
 * with #58; this component only proves the route, the shell and the layout.
 */
@Component({
  selector: 'app-posts',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="screen">
      <h1>Posts</h1>
      <p class="hint">
        What did it find? Paged posts with their analysis and the filters arrive with #58.
      </p>
    </section>
  `,
})
export class Posts {}
