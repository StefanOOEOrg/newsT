import { provideHttpClient } from '@angular/common/http';
import {
  ApplicationConfig,
  EnvironmentProviders,
  isDevMode,
  provideBrowserGlobalErrorListeners,
  provideCheckNoChangesConfig,
  provideZonelessChangeDetection,
} from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';

import { routes } from './app.routes';

/**
 * Dev-only providers (#47 in flux-workbench, same reasoning here).
 *
 * The app is zoneless: state that changes without a signal update simply does not re-render.
 * `provideCheckNoChangesConfig` makes Angular run an exhaustive `checkNoChanges` periodically and
 * THROW instead of showing a stale UI. It is a development aid only and stays out of production.
 */
export const DEV_ONLY_PROVIDERS: EnvironmentProviders[] = isDevMode()
  ? [provideCheckNoChangesConfig({ exhaustive: true, interval: 1000 })]
  : [];

export const appConfig: ApplicationConfig = {
  providers: [
    provideZonelessChangeDetection(),
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(),
    ...DEV_ONLY_PROVIDERS,
  ],
};
