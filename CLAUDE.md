# DENT — AI Vehicle Damage Detection Platform

## Quick Commands

```bash
dotnet build src/DENT.API/DENT.API.csproj     # Build API
dotnet test tests/DENT.Tests/                   # Run tests
cd clients/web && npm run dev                   # Frontend dev server
```

## Stack

- **API**: .NET 9, MediatR (CQRS), EF Core + PostgreSQL, JWT auth (httpOnly cookies)
- **Frontend**: Next.js 16 (App Router), TypeScript, Tailwind
- **ML**: Python FastAPI, PyTorch forensic modules (ELA, FFT, CNN, CLIP, DINOv2)
- **Storage**: MinIO (S3-compatible), images at `/storage/dent-images/`

## Architecture

```
Next.js (:3200) ──→ .NET API (:3201) ──→ PostgreSQL (internal)
                         ├──→ ML Service (:3202)
                         └──→ MinIO (:3203)
```

API rewrites in `clients/web/next.config.ts`: `/api/*` → API, `/storage/*` → MinIO.

## Deploy

CI pushes to main → GitHub Actions → SSH → `docker compose up -d --build --no-deps web api ml-service`
Container names: `dent-web`, `dent-api`, `dent-ml`, `dent-minio`, `dent-postgres`

## Gotchas

- ML service takes ~5 min to start (model loading). Health check has `start_period: 300s`
- Frontend proxies `/api/` via Next.js rewrites — host nginx also routes `/api/` directly to :3201
- Auth cookies: `dent_auth` (JWT, httpOnly), `dent_refresh` (httpOnly, path=/api/auth), `dent_has_auth` (JS-readable)
- DB migrations run automatically on API startup (`MigrateAsync`)
- Tests use InMemory DB — 3 DecisionEngine tests fail due to Croatian diacritics (pre-existing)
- `docker-compose.server.yml` is the production compose file (not `docker-compose.yml`)

## Code Conventions

- Croatian UI text (error messages, labels). Code/comments in English
- MediatR for all CRUD: Commands in `Application/Commands/`, Queries in `Application/Queries/`
- DTOs in `Shared/DTOs/`, entities in `Domain/Entities/`
- API controllers are thin — delegate to MediatR handlers

## Compaction

When compacting, preserve: container names, port numbers, file paths being edited, and any SSH commands run on 94.72.107.11.
