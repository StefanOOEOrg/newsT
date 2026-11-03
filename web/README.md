# web - the newstrading dashboard

Angular 22 SPA, the same artifact set as `flux-workbench/web`: standalone components, zoneless
change detection, signal stores, `@angular/build`, Vitest 5 with jsdom, ESLint 10 + angular-eslint,
Prettier, TypeScript 6.

The build goes to `web/dist` and is served by `newstrading dashboard` (#56) together with the API
under `/api`. `web/dist` and `web/node_modules` are not committed.

## Commands

Node 22 or newer (`.nvmrc` pins 22; the committed lockfile was built with npm 11.19.0).

```bash
npm ci                 # install exactly the lockfile
npx ng build           # production build -> web/dist
npm start              # dev server on :4200, /api proxied to 127.0.0.1:8088
npx ng test --watch=false
npx ng lint
npx prettier --check .
```

## Layout

```
src/main.ts            bootstrapApplication, zoneless
src/app/app.config.ts  provideZonelessChangeDetection, router, HttpClient, dev-only providers
src/app/app.routes.ts  the six screens (lazy) + the 404 route, and the navigation entries
src/app/app.*          the shell: header (logo, wordmark, nav), router-outlet, footer with version
src/app/screens/       one placeholder component per screen - replaced in #58
src/app/not-found/     the 404 screen
src/styles.css         the design tokens as :root variables, base controls
public/logo.svg        logo lockup (mark + wordmark)
public/logo-mono.svg   the same lockup, monochrome
public/mark.svg        the mark alone, used in the shell header
public/favicon.svg     the mark as favicon
docs/screenshot-shell.png  the shell at 1440x900, for the pull request of #57
```

Component styles use only the tokens from `src/styles.css`; no stylesheet carries a colour of its
own, and there is one accent colour (`--accent: #7c5cff`).
