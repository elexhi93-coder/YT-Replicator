# Architecture

## Goals

- Host the application on a server and operate it through a browser.
- Keep the code modular, with clear ownership of Pipeline, catalog, upload, and job behavior.
- Use one deployment and one codebase for the web interface and background work.
- Avoid introducing external workflow or queue services before they are needed.

## Technology direction

- **Language:** Python.
- **Web framework:** Django, including Django authentication, ORM, migrations, and server-rendered templates.
- **Database:** PostgreSQL.
- **Background work:** A Django management command/worker process that claims due jobs from PostgreSQL. Start without Celery or Redis; reassess only if measured throughput or reliability needs justify them.
- **Discovery/download:** yt-dlp for YouTube metadata discovery and video downloads.
- **Upload:** YouTube Data API resumable uploads with OAuth.
- **Deployment:** Web process, PostgreSQL, and worker process on a hosted server. These are logical runtime roles in one application, not separate products.

## Modular boundaries

Use focused Django apps or equivalent modules with explicit interfaces:

- **Accounts / Workspaces:** users, access, and data ownership. Start with one Workspace per installation; scope records to it so a future hosted multi-customer service can isolate data.
- **Pipelines:** configure sources, destinations, stage, schedule, priority, and per-Pipeline settings.
- **Sources / Catalog:** register YouTube channels, scan metadata, and track catalog entries. Scanning metadata must not automatically download every video.
- **Destinations:** represent authorized YouTube upload channels and their upload defaults.
- **Jobs / Worker:** durable queue state and orchestration of scan, download, upload, retry, and cleanup actions.
- **YouTube integration:** OAuth, destination inventory sync, upload, and API error translation.
- **History / Ledger:** durable mapping between each source video and its result at each destination.

Modules should communicate through focused service functions and persisted state, rather than importing UI code or calling each other's internals. Keep the first version small; do not add generic plugin frameworks or multi-platform abstractions yet.

## Security and credentials

Require authentication for the hosted application. Scope all user-visible data to its Workspace. OAuth tokens and client secrets must not be stored as plaintext or checked into source control; define encrypted-at-rest token storage and key management before deployment.

## Deployment assumption

The first deployment is a private installation for one operator or client. A future shared SaaS deployment can add self-service registration, tenant administration, billing, and subscription limits without changing the Pipeline domain model. Those SaaS features are not part of the initial release.

## Not in initial scope

- n8n or another external workflow engine.
- Redis, Celery, or a separate message broker.
- Desktop GUI, React frontend, or multiple social platforms.
- FFmpeg transformations and AI metadata rewriting, unless a confirmed YouTube requirement calls for them.
