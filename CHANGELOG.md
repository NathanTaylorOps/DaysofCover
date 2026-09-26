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
