# emailcreationskill backend

Lives at `marketing/email-creation-service/backend`. `marketing/emailcreationskill/`
holds the legacy Python service and is where `.env` lives.

Go service, structured hexagonally (ports & adapters) after
[lfx-v2-campaign-service](https://github.com/linuxfoundation/lfx-v2-campaign-service):

```
design/            API contract (Goa DSL) — run `make apigen` after editing
gen/                generated Goa transport/service code, DO NOT EDIT
cmd/emailcreationskill/   entry point + router wiring
internal/domain/     ports (interfaces) + models
internal/service/    use-case orchestration (business logic)
internal/dispatch/   adapters — concrete implementations of the ports (HubSpot, etc.)
internal/infrastructure/  config, DI/bootstrap plumbing
```

**Transport split:** plain request/response endpoints are modeled in
`design/` and served via Goa's generated HTTP transport (see `/api/status`
for the reference implementation). SSE/long-lived-stream endpoints don't
fit Goa's generated transport and are mounted directly on the chi router
instead (see `server.go`). Most existing routes (the audience-builder API)
are still chi-mounted pending a later migration pass into `design/`.

## Run

Requires `.env` in `../../emailcreationskill/.env` (relative to this
directory) with at least `HUBSPOT_ACCESS_TOKEN` set — `config.Load` checks
each ancestor directory and its `emailcreationskill` sibling, so this works
regardless of which directory you invoke `go run` from.

```bash
export PATH="/c/Program Files/Go/bin:$PATH"   # if go isn't already on PATH
make run          # or: go run ./cmd/emailcreationskill
```

Server listens on `:8000` by default (override with `PORT`).

## Regenerate Goa code after editing design/design.go

```bash
export PATH="/c/Program Files/Go/bin:$PATH:$(pwd)/../../emailcreationskill/.gobin"
make apigen
```

(`.gobin` holds the pinned `goa` CLI binary, installed via
`go install goa.design/goa/v3/cmd/goa@v3.20.1`.)

## Verify

```bash
make build vet test
```
