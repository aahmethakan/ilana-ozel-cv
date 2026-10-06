# Controlled-release go/no-go checklist

Use this checklist for the proposed **v0.1.0-rc.1** release candidate. Check
each item with recorded operator evidence. A missing required item is a no-go
for deployment, not permission to weaken the application's safety boundaries.

## Repository and build gate

- [ ] Release owner selected only the required tracked changes and the
      release-relevant untracked application/test/deployment files.
- [ ] The untracked `frontend/` prototype is excluded; the shipped UI is
      `backend/app/static/`.
- [ ] No personal CV, raw upload, SQLite database/WAL/SHM, generated export,
      `.env`, virtual environment, log, cache, or local runtime artifact is
      included in the release selection.
- [ ] `git diff --check` exits successfully for the selected change set.
- [ ] A clean Python 3.13 environment installs `-r requirements.txt` and
      imports `app.main:app` successfully.
- [ ] If tests are part of the release gate, install
      `-r requirements-dev.txt` and run the exact regression commands in
      `backend/DEPLOYMENT.md`.

## Required production configuration

- [ ] `ILANA_ENVIRONMENT=production` is set.
- [ ] `ILANA_SESSION_DB_PATH` is an absolute path outside the checkout, with
      restricted directory permissions for the application account.
- [ ] `ILANA_ALLOWED_HOSTS` contains only the deployed host names.
- [ ] `ILANA_CORS_ALLOWED_ORIGINS` contains only the deployed HTTPS origins.
- [ ] One loopback Uvicorn process is started with `--workers 1` as documented.
- [ ] The database, WAL/SHM files, backups, and host disk protections follow
      the organization's candidate-data retention policy.
- [ ] `ILANA_OPENAI_API_KEY`, if used, comes only from the deployment secret
      store/environment and is unavailable to browser clients.

## Reverse-proxy and TLS gate

- [ ] `deploy/nginx.conf.example` has been adapted with the real hostname and
      certificate paths; placeholders are not deployed.
- [ ] `nginx -t` passes on the target host before reload.
- [ ] HTTP redirects to HTTPS, certificate validation succeeds, and HSTS is
      emitted only on the HTTPS virtual host.
- [ ] The proxy reaches only the loopback Uvicorn upstream and forwards
      constrained client-address headers as documented.
- [ ] Upload and rewrite rate limits plus transport upload size are validated
      in the target Nginx configuration.
- [ ] Proxy logs are configured not to retain request bodies, sensitive
      headers, or query strings.

## Functional and privacy smoke gate

- [ ] Through the deployed HTTPS proxy, `/health`, `/api/v1/ready`, `/`, and
      `/static/app.js` return expected results.
- [ ] A permitted non-production smoke CV exercises analysis, career review,
      job analysis, generation, review decision, CV exports, cover-letter
      exports, session recovery, and session deletion.
- [ ] The deletion check confirms browser `sessionStorage`, in-memory state,
      SQLite recovery state, persisted quality/readiness state, job/coach
      state, and generated/review/cover-letter state do not recover after
      deletion and refresh.
- [ ] The smoke check confirms a job description is not promoted into a
      verified candidate fact and unresolved evidence is not promoted by a
      readiness action.

## Legal and operational sign-off

- [ ] Legal owner has approved the PyMuPDF licensing/distribution approach,
      including the runtime font buffer used by PDF export.
- [ ] Privacy/security owner has approved data retention, backup retention,
      logical deletion, and incident handling for candidate data.
- [ ] Operations owner accepts the controlled single-instance boundary and has
      a monitored restart/recovery procedure.
- [ ] Release owner records the chosen version/tag externally. This repository
      audit does not create a tag, archive, or release artifact.
