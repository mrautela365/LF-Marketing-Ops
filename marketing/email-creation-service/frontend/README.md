# services/frontend

Angular front end for the email-creation-skill service, structured as a
Turborepo/workspaces monorepo matching the conventions of
[lfx-self-serve](https://github.com/linuxfoundation/lfx-self-serve).

**This is a structural skeleton pass, not a full app port.** It proves the
monorepo shape, the build pipeline, and the dev-server-to-backend wiring work
end to end with one minimal page. See "Deviations from lfx-self-serve" below
for what was intentionally left out.

```
services/frontend/
  package.json          # root workspace manifest (workspaces: apps/*, packages/*)
  turbo.json             # turbo pipeline: build / lint / check-types / start / test
  tsconfig.json           # base TS config
  apps/
    email-creation-ui/    # Angular 20 app (Tailwind, standalone components)
  packages/
    shared/                # @email-creation/shared - TS types shared with the app
```

## Install

```
cd services/frontend
npm install
```

> Yarn was NOT substituted silently — see "Deviations" below for why npm is
> used instead of yarn.

## Run (dev)

The Go backend (`services/backend`) must be running on `http://localhost:8000`
first, since the Angular dev server proxies `/api/*` to it.

```
npm run start
```

This runs `turbo run start`, which runs `ng serve` for
`apps/email-creation-ui`. Angular's dev server picks up
`apps/email-creation-ui/proxy.conf.json` (wired into the `serve` target's
`options.proxyConfig` in `angular.json`), so requests to `/api/status` and
`/api/audience-builder/lists/search` from the app are forwarded to
`http://localhost:8000` without CORS issues.

Open the app at the URL `ng serve` prints (default `http://localhost:4200`).
It will:

- Call `GET /api/status` on load and show whether HubSpot / AI mode are
  configured.
- Let you type a query and call
  `GET /api/audience-builder/lists/search?q=<query>`, rendering the returned
  list names and sizes.

## Build

```
npm run build
```

Runs `turbo run build`, which builds `packages/shared` (via `tsc`) first,
then `apps/email-creation-ui` (via `ng build`), respecting the
`dependsOn: ["^build"]` dependency declared in `turbo.json`. Output lands in
`apps/email-creation-ui/dist/email-creation-ui`.

Type-check only (no emit): `npm run check-types` (`turbo run check-types`).

## Workspace linking

`apps/email-creation-ui` depends on `@email-creation/shared` via the
workspace protocol (`"@email-creation/shared": "*"` in its `package.json`).
`npm install` at the root symlinks
`node_modules/@email-creation/shared -> packages/shared`, and
`src/app/status.service.ts` / `src/app/lists.service.ts` import
`StatusResponse` / `ListsSearchResponse` / `AudienceListInfo` from it — this
is exercised by the build, not just scaffolded.

## Deviations from lfx-self-serve

This pass deliberately narrows scope. Anything below is either an
environment limitation or an explicit "skip for the skeleton" call — not an
oversight.

- **npm instead of yarn.** lfx-self-serve pins `packageManager: "yarn@4.9.2"`
  via Corepack. In this environment, `corepack enable` failed with an `EPERM`
  writing shims into `C:\Program Files\nodejs` (no admin rights), and
  `yarn@4.9.2` isn't installable as a plain npm package (Yarn Berry isn't
  published under the legacy `yarn` npm name). Per the task's documented
  fallback, this repo uses npm workspaces instead — the `workspaces` field in
  `package.json` and the folder layout are otherwise identical to what yarn
  workspaces would expect, so switching back to yarn later (once Corepack can
  run with the right permissions) should just mean re-running
  `corepack prepare yarn@4.9.2 --activate`, deleting `package-lock.json` /
  `node_modules`, and running `yarn install`.
- **No SSR / no Express server / no PM2.** lfx-self-serve's app ships with
  `@angular/ssr`, an Express server (`src/server`), OpenTelemetry
  instrumentation, and PM2 process management (`ecosystem.config.js`,
  `start:server`, `start:prod` scripts). The email-creation-ui app was
  scaffolded with `--ssr=false` and has none of that — it's a pure
  client-side SPA served by `ng serve` / static `dist/` output. This was an
  explicit scope call in the task, not a limitation.
- **No routing module.** Scaffolded with `--routing=false` since there is
  only one page in this skeleton pass.
- **No ESLint / Prettier configuration.** lfx-self-serve uses
  `@angular-eslint`, `typescript-eslint`, and Prettier with a
  `lint-staged` + Husky pre-commit pipeline. This skeleton's `lint` script is
  a placeholder that runs `tsc --noEmit` (there is no linter installed) — real
  linting was left out to keep this pass minimal. Adding
  `ng add @angular-eslint/schematics` and a shared `eslint.config.js` /
  `.prettierrc` would be the natural next step.
- **No `@lfx-one/shared`-equivalent design tokens.** `tailwind.config.js`
  here is a minimal `content` + `theme.extend` config; it does not import
  brand color/typography tokens the way lfx-self-serve's config pulls
  `lfxColors` / `lfxFontSizes` from its shared package, since none of that
  exists in this codebase yet.
- **No tests beyond the generated smoke spec.** `apps/email-creation-ui/src/app/app.spec.ts`
  was updated only enough to keep working with the new template/services
  (providing `HttpClient`/`HttpClientTesting` and checking the new title
  text). No new unit tests were added for `StatusService` / `ListsService`.
- **Single Angular app, single shared package.** lfx-self-serve has many
  more `packages/*` (constants, interfaces, enums, utils, etc.) — this
  skeleton has exactly one shared package with exactly the two response
  types the app actually calls, to prove the workspace-linking mechanism
  without over-building.

## Verification performed

- `npm install` at `services/frontend/` (npm workspaces, no yarn available —
  see Deviations).
- `npx turbo run build` — builds `@email-creation/shared` then
  `email-creation-ui`; both succeeded, `ng build` produced
  `apps/email-creation-ui/dist/email-creation-ui` (~211 kB initial bundle
  including the Tailwind-compiled `styles.css`).
- `npx turbo run check-types` — `tsc --noEmit` clean for both the shared
  package and the app (this includes type-checking the
  `@email-creation/shared` import into `status.service.ts` /
  `lists.service.ts`).

Not performed (out of scope per task instructions): starting the Go backend,
or manually browser-testing the running dev server.
