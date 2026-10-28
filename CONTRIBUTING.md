# Contributing

Use fictional data in code, fixtures, screenshots, and issues. Keep changes small and explain the user-visible behavior and metric definitions. This project is an educational demonstration; it does not represent a real organization's data or endorsements.

1. Use Python 3.11+ and Node 24+. Run `npm ci --ignore-scripts`.
2. Write a boundary or calculation test that fails for the bug or feature, then implement it.
3. Run `python3 -m unittest discover -s tests -v`, `npm run typecheck`, `npm run build`, and `npm test`.
4. Install Chromium with `npx playwright install chromium` and run `npm run test:browser`. On Linux use `npx playwright install --with-deps chromium`. Then run `python3 scripts/build_site.py --verify-only` against the exact browser-tested directory before any upload.
5. Review the screenshots in the git-ignored `test-results/screenshots/`. To refresh the committed images in `docs/screenshots/`, run `IMPACT_LEDGER_UPDATE_SCREENSHOTS=1 npm run test:browser`. Update documentation for changed definitions, APIs, or limits.

Commit compiled `impact_ledger/static/app.js` and `model.js` with their TypeScript changes so Python package installs work without Node. `site/` is reproducible build output and is ignored. Do not commit databases, virtual environments, dependencies, local secrets, generated exports, or private data.

The builder accepts `--output-directory PATH` (existing parent required) for isolated checks. It permits only the seven documented generated regular files, rejects selected/file symlinks, source overlap and unknown entries before writes, and replaces allowed names without writing through hard links. Rebuilds can repair missing/changed regular files; move unknown entries yourself. Verification reads/compares the actual selected output without repairing it and uses a separate temporary seed database. Do not weaken this boundary with recursive deletion or a force flag. Tests run the real builder in temporary Unicode/spaced source roots; use synthetic markers only.

Keep frontend testing and Pages publication in the same CI workflow: browser checks → exact payload verifier → main-only artifact upload; deploy depends on both the Python matrix and frontend job. PR/non-main tests must skip upload/deploy, and Pages/id-token writes belong only to the gated deploy job. Ref-scoped concurrency prevents a non-main dispatch from cancelling main. `ubuntu-24.04` is explicit because runner `-latest` labels migrate; the [official runner catalog](https://github.com/actions/runner-images) lists the supported image. Screenshot uploads have seven-day retention. Installed-wheel checks must include exact generated/installed asset and seed parity outside the source directory.

The initial implementation was developed with AI assistance and reviewed through automated boundary, calculation, integration, and browser checks. Changes still need human judgment; test success is not an audit or evidence of real-world adoption.
