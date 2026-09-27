# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Stage 1 spike: a single-node daily-step engine (continuous-review base-stock, periodic (R, S), periodic (s, S)), validated against validation cases 1 to 3.
- ADR-008: own daily-step engine over SimPy, confirmed by the spike's numbers.
- Per-shipment in-transit records (crossing allowed, independent lognormal lead times), validated against validation cases 5 and 6.
- Order-pausing disruptions on a base-stock node (a two-state Markov process), validated against validation case 4.
- A serial multi-node chain (order-up-to with a moving-average forecast), validated against validation case 11 (bullwhip).
- A linear production-capacity ramp after a restart, validated against validation case 12 (ramp bounds).
- A backlog-driven shipment-recovery lag behind a step production recovery, validated against validation case 13 (shipment lag).
- The multi-node engine's state chassis: NumPy arrays indexed by (node, part) for on-hand, on-order and backlog, sized from a real network.
- Per-lane, per-part in-transit shipments (FIFO unless allow_crossing, an independent lognormal lead time per shipment).
- BOM-driven production at a plant: feasible daily output capped by capacity and the scarcest component, batched, with a fixed-lead-time production queue.
- The first end-to-end daily-step loop, composing the state chassis, per-lane shipments and production for one plant and one SKU.
- The allocation and split rules: backlog-proportional and margin-priority splits across SKUs, FIFO-with-priority-override across customer orders, and the dual-source fixed-split-until-contingent-switch rule.
- Multiple SKUs sharing a scarce component in the daily-step loop, split by backlog proportion or, optionally, by margin priority.
- Multiple customers competing for one SKU's scarce finished goods in the daily-step loop, served by priority override then FIFO by order date.
- The plant's own periodic-review order-up-to reordering of a component, wired into the daily-step loop against the true on-hand-plus-on-order inventory position.
- MOQ and per-lane weekly capacity caps on that reorder quantity, deferring an order to zero rather than placing a partial, sub-MOQ shipment.
- A dual-sourced part's reorder split across every supplier's own lane, following the fixed split ratio or a contingent full switch to the backup, each supplier's share capped independently by its own lane.
- A replication runner with entity-indexed common random numbers: independent, reproducible RNG substreams keyed by entity id and replication index, so the same entity draws the same numbers across two different scenario runs.
- An MSER-5 warm-up truncation check, so a replication's early transient days can be discarded before averaging its output.
- `tests/strategies.py` and a property-test tier (Hypothesis): composite strategies for schema-valid networks, part-supplier lists and id sets, checking invariants (allocation never exceeds request or availability, a capped order is always zero or at least the MOQ, a supplier split always accounts for the whole order, the state chassis is always sized from its network) across generated inputs, not just hand-picked examples.
- Validation harnesses cross-checking the engine against two independent, external inventory/supply-chain libraries: `stockpyl` (case 3's (s, S) policy, against `stockpyl.ss.s_s_cost_discrete`'s own exact evaluation) and `SupplyNetPy` (a zero-lead-time (s, S) policy's service level, against classical continuous-review theory, across a genuinely different -- discrete-event, continuous-time -- simulator architecture).
- A parametric synthetic network generator (`daysofcover.data.synthetic`) and a profiling script (`scripts/profile_engine.py`) measuring the daily-step engine's per-day wall-clock time on a network sized to the plan's ~40-node/25-part target, against its 200 ms target.
- A generated `VALIDATION.md` (`scripts/generate_validation_report.py`), reproducing validation cases 1 to 6, 11, 12 and 13 with their actual numbers alongside each one's published reference and tolerance.

## [0.0.1] - 2026-09-26

### Added

- Package skeleton with a `daysofcover --version` command.
- Pre-commit hooks: ruff, gitleaks and the standard file checks.
- `fast` CI workflow: lint, format, types, tests on Python 3.12 and 3.13, wheel build and smoke test, Docker image build and push to GHCR on `main`.
- `full`, `nightly` and `release` CI workflows.
- Project governance: licence, citation file, security policy, contributing guide, code of conduct, issue and pull request templates.
- ADR-001 through ADR-007, and a Diataxis-shaped docs skeleton (tutorials, how-to, reference, explanation).
- Schema v0: Pydantic models for the network, its mitigation options, a stress-test scenario and its results, all strict-mode and referentially validated.
- A seeded, deterministic example network (Moreton Marine Systems, a fictional Brisbane marine-electronics manufacturer) and the generator that produces it.
- A `daysofcover validate` command that checks a network file against the schema.
- A hello-world Svelte front end and a FastAPI `/health` endpoint, both served from a single Docker image built in CI and deployed to Render.

[Unreleased]: https://github.com/NathanTaylorOps/DaysofCover/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/NathanTaylorOps/DaysofCover/releases/tag/v0.0.1
