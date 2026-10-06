# Ilana Ozel CV v0.1.0-rc.2 - release notes draft

**Status:** release-candidate draft for the reviewed Render Free deployment
option. This document does not create a Git tag, archive, container image, or
public release.

## Delta from v0.1.0-rc.1

- Adds an explicit Render Free deployment contract with repository root,
  Python runtime pin, build command, single-worker start command, and required
  production environment variable names.
- Adds an explicit `ephemeral` session-persistence mode for platforms without
  durable local storage. In this mode session state remains memory-only and
  SQLite is neither created nor used.
- Shows a truthful UI notice in ephemeral mode so users know that a restart,
  redeploy, or inactivity spin-down may require another CV upload.
- Keeps durable SQLite-backed recovery as the default mode and keeps existing
  production host, CORS, source-link, provenance, and readiness boundaries.

## Render Free boundary

Render Free is limited to a controlled single instance. The configured service
must use Python 3.13.15, `pip install -r requirements.txt`, and
`python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` from
the `backend` root directory. The assigned Render hostname must be supplied
for `ILANA_ALLOWED_HOSTS` and `ILANA_CORS_ALLOWED_ORIGINS`; placeholders are
not deployable values. `ILANA_OPENAI_API_KEY` remains optional.

Raw uploaded PDFs and generated documents remain non-persistent. This RC does
not certify multi-instance, multi-worker, unrestricted public-production, or
durable-recovery operation on Render Free.
