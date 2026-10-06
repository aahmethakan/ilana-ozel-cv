# Ilana Ozel CV v0.1.0-rc.1 - release notes draft

**Status:** release-candidate draft for a controlled, single-instance
deployment. This document does not create a Git tag, archive, container image,
or public release.

## Scope

This RC provides the end-to-end local web workflow for:

- PDF CV analysis and public career-profile review;
- coach answers and explicitly resolved continuation/readiness evidence;
- job analysis and conservative, evidence-bound job matching;
- deterministic general or targeted CV generation, review decisions, and
  controlled rewrite when a configured provider is available;
- DOCX/PDF CV export, cover-letter generation/review/rewrite, and DOCX/PDF
  cover-letter export;
- session recovery, user-requested session deletion, and privacy-state cleanup.

The canonical UI is served by the FastAPI application at `/`; it uses the
assets in `backend/app/static/`. It is not the untracked `frontend/` prototype.

## Safety and privacy boundaries

- Candidate facts retain their evidence/provenance and verification state.
  Job-description text does not become a candidate fact.
- Readiness resolution supports safe omission only; it does not promote an
  unresolved item to verified evidence.
- Raw uploaded PDFs and generated drafts are not persisted in the recovery
  snapshot. Persisted data is retained only for the configured session TTL and
  can be deleted through the UI.
- Session IDs are opaque capabilities sent in JSON request bodies and retained
  in browser `sessionStorage`; they are not encoded into frontend request URLs.
- Session deletion removes the in-memory and SQLite recovery record. It is
  logical deletion, not forensic secure erasure; backup retention is an
  operator responsibility.

## Deployment boundary

Only the controlled, single-instance deployment documented in
`backend/DEPLOYMENT.md` is in scope: one loopback Uvicorn worker behind a
trusted TLS reverse proxy. Multi-instance operation, multi-worker Uvicorn,
anonymous public production, authentication/ownership guarantees, distributed
rate limiting, and forensic secure deletion are not certified by this RC.

## Dependencies

Runtime dependencies are pinned in `backend/requirements.txt`; direct test
dependencies live separately in `backend/requirements-dev.txt`. There is no
transitive lockfile. The release operator must reproduce the documented Python
3.13 environment and revalidate any resolver-selected transitive packages.

`pymupdf==1.28.2` is a release checkpoint: its distribution model must be
cleared by the organization before release or distribution. The PDF exporters
use PyMuPDF's runtime `cjk` font buffer and do not package a separate font file.

## Required external checkpoints before deployment

1. Legal owner confirms the PyMuPDF licensing/distribution path.
2. Operator sets production environment variables, an absolute database path
   outside the checkout, explicit allowed hosts, and explicit HTTPS CORS
   origins.
3. Operator adapts `deploy/nginx.conf.example` with the real host and
   certificate paths, then runs `nginx -t` in the target environment.
4. Operator verifies HTTPS `/health`, `/api/v1/ready`, `/`, and a static asset
   through the deployed reverse proxy.
5. Operator documents SQLite/WAL/SHM access controls, encryption, backup
   retention, and deletion handling for candidate data.
6. If controlled rewrite is needed, operator supplies `ILANA_OPENAI_API_KEY`
   only through the deployment environment and confirms it is absent from
   source, frontend assets, logs, and OpenAPI output.

## Known limitations

- A live provider call is optional and was not made part of the automated
  regression suite.
- Nginx syntax and certificate configuration cannot be validated on a machine
  without Nginx; the included file is an operator-adapted example.
- Export font availability is exercised through PyMuPDF in regression and the
  RC browser flow, but legal/distribution review remains external.
