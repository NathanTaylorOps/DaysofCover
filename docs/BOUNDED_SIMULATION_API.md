# Bounded simulation API (illustrative preview)

The synchronous deterministic endpoint `POST /api/simulation/bounded` accepts a
JSON object with `network` (the strict Network schema) and `config`
(BoundedScenarioInput). The response is `ScenarioComparison`, with daily
baseline/disrupted demand, same-day fulfilled units, cumulative unserved demand
(backlog), total fulfilment and service fraction.

## Supported demonstration

- `GET /api/example/simulation/request` returns a complete supported request.
- `POST /api/example/simulation` runs that fixed request and labels its output
  as synthetic. No request body is needed.
- Send the GET response body to `POST /api/simulation/bounded` to reproduce
  the comparison using the caller-supplied-network endpoint.

The demo is **illustrative, not empirical**. It is separate from the Moreton
Marine structural-screen dataset, whose multi-component SKUs cannot be
processed by this bounded runner.

## Limits and interpretation

- Exactly one selected plant, one SKU and one BOM component per run.
- Maximum horizon: 90 days; disruption duration is limited to 90 days.
  Component inventory, finished stock, daily demand and weekly capacity are
  each capped at 1 billion units to bound arithmetic and prevent overflow.
  Demand is constant each day, with caller-supplied
  initial component inventory, finished stock and production capacity.
- No replenishment, supplier/lane simulation, distribution, stochastic demand,
  financial-loss calculation or full-network resilience estimate.
- A day’s `fulfilled_units` counts only that day's demand served on that day.
  Unserved demand accumulates in `backlog_units` and is **not automatically
  fulfilled later**. The service fraction is total same-day fulfilled divided
  by total requested units; zero demand is defined as service fraction 1.
- The two runs share inputs and differ only by the configured plant disruption.
  The seed is preserved in the contract; this runner is deterministic.
- This endpoint is synchronous and intended for small bounded demonstrations,
  not as a general-purpose multi-tenant simulation service. No guaranteed
  latency/SLA is established. Production hosting must impose reverse-proxy
  request-body size limits, rate limits and timeouts before public arbitrary
  network submissions are enabled. The network schema bounds graph size.
  The bounded POST endpoint enforces a **256 KiB request-body limit** and
  returns HTTP **413** for oversized submissions, including streamed bodies.
  This application-level cap does not replace proxy-level limits or rate
  limiting; no explicit CPU-time budget or concurrency queue is enforced.

The response contract is preserved for frontend integration. The demo
`synthetic=true` and `dataset` fields are explicit so its results cannot
be mistaken for a calibrated forecast.
