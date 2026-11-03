import { Routes } from '@angular/router';

/** One entry of the shell navigation: the route, its label and the question it answers. */
export interface NavItem {
  /** Route path without the leading slash; the empty string is the overview. */
  readonly path: string;
  /** Short name in the header navigation. */
  readonly label: string;
  /** The user question the screen answers (see #55) - used as the link title. */
  readonly hint: string;
}

/**
 * The six screens in the order of the questions a user asks (#55):
 * *Is it running?* -> *What did it find?* -> *What fired?* -> *Was it right?* ->
 * *Which sources are healthy?* -> *What went wrong?*
 *
 * Single source of truth for the header navigation and for the route table below.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { path: '', label: 'Overview', hint: 'Is it running?' },
  { path: 'posts', label: 'Posts', hint: 'What did it find?' },
  { path: 'alerts', label: 'Alerts', hint: 'What fired?' },
  { path: 'performance', label: 'Performance', hint: 'Was it right?' },
  { path: 'sources', label: 'Sources', hint: 'Which sources are healthy?' },
  { path: 'logs', label: 'Logs', hint: 'What went wrong?' },
];

/**
 * Application routes: the six screens, each with its own signal store, plus a 404 component.
 *
 * The routes and the navigation are the ones of the shell (#57); #58 filled the components with
 * the stores, the services and the tables.
 */
export const routes: Routes = [
  {
    path: '',
    title: 'Overview · newstrading',
    loadComponent: () => import('./screens/overview/overview').then((m) => m.Overview),
  },
  {
    path: 'posts',
    title: 'Posts · newstrading',
    loadComponent: () => import('./screens/posts/posts').then((m) => m.Posts),
  },
  {
    path: 'alerts',
    title: 'Alerts · newstrading',
    loadComponent: () => import('./screens/alerts/alerts').then((m) => m.Alerts),
  },
  {
    path: 'performance',
    title: 'Performance · newstrading',
    loadComponent: () => import('./screens/performance/performance').then((m) => m.Performance),
  },
  {
    path: 'sources',
    title: 'Sources · newstrading',
    loadComponent: () => import('./screens/sources/sources').then((m) => m.Sources),
  },
  {
    path: 'logs',
    title: 'Logs · newstrading',
    loadComponent: () => import('./screens/logs/logs').then((m) => m.Logs),
  },
  {
    path: '**',
    title: 'Not found · newstrading',
    loadComponent: () => import('./not-found/not-found').then((m) => m.NotFound),
  },
];
