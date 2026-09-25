# ADR-003: Stateless API, client-held results

- Status: Accepted
- Date: 2026-09-25

## Context

The hosted API runs simulation jobs (a scenario against a network, possibly
hundreds of replications) and needs to return results to the browser. The
free-tier Render instance has ephemeral disk and can restart between
requests. A "Compare" feature needs a baseline result and one or more
mitigated-variant results to still be available even if other visitors'
jobs have run on the same server in between.

## Decision

The server holds no durable results. A completed job's result JSON is
handed to the client, which is responsible for holding whatever it wants to
keep (a baseline, a mitigated variant, anything it wants to compare later).
The server may keep a small bounded LRU cache of recent results purely as a
polling convenience (so a client that reconnects mid-job can resume
polling), but nothing about correctness depends on that cache surviving a
restart.

## Consequences

- Every result payload is self-contained: engine version, seed, scenario
  content hash, and the full set of series and summaries needed to render
  every screen, so the client never needs to ask the server "and what was
  in run X" for a run it already has the JSON for.
- Compare, and any other multi-result view, is built entirely from results
  the client is already holding, not from a server-side session or
  database.
- No user accounts, no server-side history, and no database are needed for
  v1, which matches the security section's threat model (a public API with
  no persisted personal data).
- The result payload size budget (≤500 KB gzipped) is a direct consequence:
  it has to be cheap enough for the client to hold several of these at
  once in memory or `localStorage`-equivalent state.

## Alternatives considered

- **Server-side result store (database or persistent volume).** Would let
  the client ask for a result by ID later without re-sending it, but adds a
  database dependency, a retention policy, and a place personal data could
  end up if a user pastes something sensitive into a scenario — all for a
  free-tier demo that doesn't need durability across visitors.
- **Session cookies tying a browser to server-side state.** Rejected for
  the same reason, plus it would need CORS/cookie handling across the SPA's
  static-host origin and the API's origin, which the security section
  otherwise avoids entirely (no cookies, strict CORS to one origin).
