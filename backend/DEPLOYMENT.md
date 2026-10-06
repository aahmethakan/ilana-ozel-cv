# Controlled single-instance deployment

This document is the tested deployment contract for the accepted RC. It is not
a general public-production or horizontally scaled deployment guide.

## Tested environment and clean installation

The accepted RC was tested with Python **3.13.15** (major/minor contract:
Python 3.13) and pip 26.2.1 on Windows. Do not assume compatibility with
other Python versions without a separate validation run.

From `backend/`, create an isolated environment and install the exact direct
runtime dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For development or regression testing, install the test-only direct
dependencies as well:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q -W default -p no:cacheprovider
```

`requirements.txt` contains runtime dependencies only. `requirements-dev.txt`
includes it and adds the direct test tools. Pip resolves transitive packages;
this repository does not claim a transitive lockfile.

## Required production configuration

Set values in the process environment or an ignored `.env` file. Never commit
credentials. The runtime process account must have read/write access to the
database directory, while other accounts should not.

```powershell
$env:ILANA_ENVIRONMENT = "production"
$env:ILANA_SESSION_DB_PATH = "C:\ProgramData\ilana-ozel-cv\sessions.sqlite3"
$env:ILANA_ALLOWED_HOSTS = '["cv.example.test"]'
$env:ILANA_CORS_ALLOWED_ORIGINS = '["https://cv.example.test"]'
$env:ILANA_COPYRIGHT_HOLDER = "[deployment copyright holder]"
$env:ILANA_SOURCE_CODE_URL = "https://source.example.test/ilana-ozel-cv/tree/v0.1.0-rc.1"
```

`ILANA_SESSION_DB_PATH` must be an absolute path outside the repository. The
application creates the parent directory if needed, but deployment should
pre-create it with restricted permissions. In production, wildcard allowed
hosts and wildcard CORS origins are rejected at startup.

Supported limits are: session TTL 1–168 hours (default 24), PDF upload size
1–50 MiB (default 10 MiB), PDF pages 1–500 (default 50), and expensive-route
concurrency 1–8 (default 2). Configure only values within these ranges.

`ILANA_OPENAI_API_KEY` is optional and environment-provided. Without it,
controlled rewrite is unavailable; the rest of the application starts
normally. Do not put an OpenAI key in this document, frontend assets, OpenAPI,
or repository files.

`ILANA_COPYRIGHT_HOLDER` and `ILANA_SOURCE_CODE_URL` are required in
production. The source URL must be an absolute HTTP(S) URL without credentials
or a fragment, and must point to the exact corresponding source for the
deployed version. The footer exposes the configured source URL, application
version, this project's AGPLv3 license, and the third-party notice index.

## Open-source and external-service notice

The project is distributed under GNU AGPL version 3; see `../LICENSE`,
`../NOTICE`, and `../THIRD_PARTY_NOTICES.md`. The source-link requirement is
for application source code and build/run materials only. It must never expose
uploaded CVs, extracted career data, session SQLite databases, job text,
generated documents, environment files, API keys, or operational logs.

Controlled rewrite is the only optional feature that can call an external
OpenAI service, and only when `ILANA_OPENAI_API_KEY` is configured. When the
key is absent, controlled rewrite is unavailable; no API key is exposed to the
browser or stored in the public release materials. This statement does not
make a broader claim about external-service data handling.

## Canonical single-worker start command

Run exactly one process and one Uvicorn worker from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Bind only to loopback. Put a trusted reverse proxy in front of it for any
controlled network deployment. The canonical static UI is served by `/`; its
assets are under `/static`. `/health` is liveness. `/api/v1/ready` verifies
SQLite readiness without creating application data.

TLS terminates at the reverse proxy. HSTS belongs only on the HTTPS proxy
layer, never the loopback application. See `../deploy/nginx.conf.example` for
the HTTP-context fragment: HTTPS redirect, a 12 MiB transport cap, constrained
forwarded headers, and separate general/upload/rewrite rate limits. Ensure
proxy access logs do not record request bodies, sensitive headers, or query
strings.

## Persistence, privacy, and operations

SQLite holds canonical session recovery state for the configured TTL. Protect
the database, its WAL/SHM files, backups, and underlying disk with operational
permissions and encryption appropriate to the deployment. Session deletion is
logical deletion, not forensic secure erase. Raw uploaded PDFs and generated
drafts are not persisted. Restart recovery restores the persisted canonical
state; active generated drafts and review decisions are regenerated as needed.

Backups can retain deleted data according to their own retention policies.
Document and apply those policies before handling real candidate data.

## PyMuPDF AGPL path

This project selects the GNU AGPLv3 path for `pymupdf==1.28.2`; no Artifex
commercial license is planned. Before release, the owner must confirm that the
configured source URL, notices, and exact deployed source satisfy the intended
distribution and network-service process. Do not remove upstream PyMuPDF/MuPDF
notices from any redistributed artifact.

This RC uses `pymupdf==1.28.2`. Its installed package metadata describes it
as dual-licensed under GNU AGPL 3.0 or an Artifex commercial license. This is
not a legal conclusion: **LEGAL REVIEW REQUIRED — confirm PyMuPDF
licensing/distribution compatibility for the intended deployment model before
release or distribution.**

## Explicitly unsupported deployment modes

This release is limited to a controlled, single-instance deployment. It does
not certify unrestricted anonymous public production, authentication or
multi-user ownership guarantees, multi-worker Uvicorn, multiple app
instances, shared/distributed session persistence, distributed rate limiting,
or forensic secure deletion.
