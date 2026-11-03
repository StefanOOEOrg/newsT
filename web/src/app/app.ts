import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { NAV_ITEMS } from './app.routes';
import { APP_VERSION } from './version';

/**
 * Shell of the dashboard (#57): a header with the logo, the wordmark and the six screen links, the
 * routed screen below it, and a footer with the version.
 *
 * Layout: three explicit grid rows - header 56 px, content `minmax(0, 1fr)`, footer 36 px. The page
 * itself never scrolls; the content area scrolls when a screen is longer than the window.
 * Zoneless: everything the template reads is a plain field or a signal, nothing mutates silently.
 */
@Component({
  selector: 'app-root',
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  /** The six screens, in the order of the questions a user asks (#55). */
  protected readonly nav = NAV_ITEMS;
  /** Version in the footer, from `VERSION` at the repository root. */
  protected readonly version = APP_VERSION;
}
