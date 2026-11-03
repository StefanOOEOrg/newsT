import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { App } from './app';
import { NAV_ITEMS, routes } from './app.routes';
import { APP_VERSION } from './version';

/**
 * Smoke tests of the shell (#57): the six lazy routes exist and render, the unknown route reaches
 * the 404 component, and the header/footer carry the logo, the wordmark, the six links and the
 * version.
 */
describe('App shell', () => {
  function configure(): void {
    TestBed.configureTestingModule({ providers: [provideRouter(routes)] });
  }

  function shell(): HTMLElement {
    configure();
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('has six lazy routes plus a wildcard', () => {
    expect(routes.filter((route) => route.path !== '**')).toHaveLength(6);
    for (const route of routes) {
      expect(route.loadComponent, route.path).toBeTypeOf('function');
    }
  });

  it('renders the logo, the wordmark and the six screen links', () => {
    const el = shell();

    const mark = el.querySelector('img.mark');
    expect(mark).not.toBeNull();
    expect(mark!.getAttribute('src')).toBe('mark.svg');
    expect(mark!.getAttribute('alt')).toBe('');
    expect(el.querySelector('.wordmark')!.textContent!.trim()).toBe('newstrading');

    const links = Array.from(el.querySelectorAll('nav.nav a'));
    expect(links.map((link) => link.textContent!.trim())).toEqual(NAV_ITEMS.map((i) => i.label));
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/',
      '/posts',
      '/alerts',
      '/performance',
      '/sources',
      '/logs',
    ]);
    expect(links.map((link) => link.getAttribute('title'))).toEqual(NAV_ITEMS.map((i) => i.hint));
  });

  it('never scrolls the page itself and pins the three rows', () => {
    const el = shell();

    const host = getComputedStyle(el);
    expect(host.display).toBe('grid');
    expect(host.overflow).toBe('hidden');
    // jsdom resolves `100vh` to px (= window.innerHeight), so compare against that.
    expect(host.height).toBe(`${window.innerHeight}px`);

    expect(getComputedStyle(el.querySelector('header.topbar')!).gridRow).toBe('1');
    expect(getComputedStyle(el.querySelector('main.content')!).gridRow).toBe('2');
    expect(getComputedStyle(el.querySelector('footer.footer')!).gridRow).toBe('3');
  });

  it('shows the version in the footer', () => {
    expect(shell().querySelector('[data-testid="version"]')!.textContent!.trim()).toBe(
      `v${APP_VERSION}`,
    );
  });

  for (const item of NAV_ITEMS) {
    it(`renders the ${item.label} screen at /${item.path}`, async () => {
      configure();
      const harness = await RouterTestingHarness.create(`/${item.path}`);
      harness.detectChanges();

      const heading = harness.routeNativeElement?.querySelector('h1');
      expect(heading?.textContent?.trim()).toBe(item.label);
    });
  }

  it('renders the 404 component for an unknown route', async () => {
    configure();
    const harness = await RouterTestingHarness.create('/does-not-exist');
    harness.detectChanges();

    const screen = harness.routeNativeElement;
    expect(screen?.querySelector('[data-testid="not-found"]')).not.toBeNull();
    expect(screen?.querySelector('h1')?.textContent).toContain('Page not found');
    expect(screen?.querySelector('a')?.getAttribute('href')).toBe('/');
  });
});
