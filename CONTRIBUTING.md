# Contributing

Use fictional data in code, fixtures, screenshots, and issues. Keep changes small and explain the user-visible behavior and metric definitions. This project is an educational demonstration; it does not represent a real organization's data or endorsements.

1. Use Python 3.11+ and Node 24+. Run `npm ci --ignore-scripts`.
2. Write a boundary or calculation test that fails for the bug or feature, then implement it.
3. Run `python3 -m unittest discover -s tests -v`, `npm run typecheck`, `npm run build`, and `npm test`.
4. Install Chromium with `npx playwright install chromium` and run `npm run test:browser`. On Linux use `npx playwright install --with-deps chromium`.
5. Review desktop/mobile screenshots and update documentation for changed definitions, APIs, or limits.

Commit compiled `impact_ledger/static/app.js` and `model.js` with their TypeScript changes so Python package installs work without Node. `site/` is reproducible build output and is ignored. Do not commit databases, virtual environments, dependencies, local secrets, generated exports, or private data.

The initial implementation was developed with AI assistance and reviewed through automated boundary, calculation, integration, and browser checks. Changes still need human judgment; test success is not an audit or evidence of real-world adoption.
