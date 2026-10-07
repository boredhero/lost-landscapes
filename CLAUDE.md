# Lost Landscapes development guide

Public repository: github.com/boredhero/lost-landscapes.
Live site: https://anomalies.martinospizza.dev.
See README.md for current architecture, setup, limitations, and benchmarks.

## Rules

- Push to `develop` only. Open a PR to `master`; the owner merges. Never merge yourself.
- No Co-Authored-By lines in commits.
- Keep this project independent of Lost Landscapes and the desktop at .111.
- All production services run on noah@boredhero.dyndns.org, in ~/lost-landscapes.
- Use compose.cpu.yml. No server GPU or remote desktop worker is required.
- Preserve persistent data and nginx TLS/certbot configuration.
- Processing uses native GDAL, WhiteboxTools, and PDAL. Detection passes consume precomputed rasters.
- Prefer top-level imports except to avoid circular dependencies.
- Tests exercise real native tools; CI installs GDAL and WhiteboxTools.
- Run Ruff, frontend ESLint with zero warnings, TypeScript, unit tests, and production build as appropriate.

## Current behavior

The default deployment is a terrain explorer with imported USGS LiDAR DEMs,
512px terrain tiles, cached multidirectional relief, and synchronized aerial
comparison. It does not claim to identify verified ruins. Analysis is opt-in
and uses bounded CPU workers with local PostGIS and Redis.

## CI and delivery

.github/workflows/test.yml runs on develop/master pushes and pull requests.
Lint and type checks gate native Python tests and the production frontend build.
master requires a PR and all three required checks, including for admins.
.github/workflows/deploy.yml deploys master to the CPU host after reusable CI.
A dedicated restricted SSH identity runs scripts/deploy_host.sh.
The owner controls master merges. Dependabot version-update PRs target master. Deployment has no manual trigger.
