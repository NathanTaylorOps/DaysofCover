# Changelog

Significant changes are recorded by release. The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

**Simulation and operations**
- Daily-step inventory-policy models covering continuous-review base-stock, periodic-review (R, S), and periodic-review (s, S).
- Multi-node state representation for inventory and backlog, with BOM-constrained production, capacity limits, production queues and finished-goods allocation.
- Per-lane shipment tracking with independently sampled lead times, configurable shipment crossing, weekly capacity constraints and minimum order quantities.
- Disruption propagation across affected nodes and lanes, including partial capacity reduction, in-transit holds and production interruptions.
- Recovery models for production-capacity ramp-up and shipment fulfilment lag.
- Component replenishment using inventory position, supplier allocation ratios and contingent sourcing.
- Distribution-tree routing for finished goods through modelled transport lanes and customer-facing nodes.
- Reproducible replication streams with entity-indexed random numbers and an MSER-5 warm-up truncation utility.

**Optimisation and analysis**
- Aggregate linear programmes for disruption impact, maximum feasible coverage and minimum-cost inventory buffers, solved using SciPy/HiGHS.
- Weekly time-indexed coverage analysis incorporating seasonal demand and inventory carry-forward.
- AND/OR structural-dependency screening and value-weighted exposure ranking.
- `daysofcover cover` CLI command comparing structural exposure with LP-estimated inventory cover, with optional starting-inventory input.
- A reporting utility for comparing dynamic simulation results against an aggregate LP bound.

**Validation and engineering**
- Analytical and published-reference validation cases covering inventory policies, disruption behaviour, shipment dynamics, bullwhip effects and recovery.
- Independent reference comparisons using stockpyl and SupplyNetPy.
- Property-based tests for allocation, replenishment, sourcing and network-state invariants.
- Deterministic synthetic-network generation and an engine-profiling utility.
- Generated `VALIDATION.md` documenting measured reference comparisons, tolerances and validation boundaries.
- ADR-008 documenting the choice of a daily-step NumPy engine over a process-oriented simulation framework.

### Changed

- Derived outstanding inventory directly from shipment records rather than maintaining a duplicate on-order counter.
- Integrated named scenario disruptions into the multi-node daily-step engine.
- Extended fulfilment from direct plant allocation to optional, capacity-constrained outbound distribution routing.
- Clarified validation documentation to distinguish component-level reference comparisons from end-to-end multi-node validation.
- Refined aggregate LP demand accounting to include customer-held inventory and permit positive ending stock.
- Expanded the aggregate LP to support inventory-buffer decisions and the structural and weekly analyses.
- Updated CLI terminology to distinguish LP estimates from dynamic simulation results.

### Fixed

- Corrected the aggregate LP demand-balance formulation: the previous equality could make otherwise feasible networks appear infeasible when available supply exceeded demand. The inequality permits surplus ending inventory and is exercised by multi-customer test cases.

### Known limitations

- The hosted interface currently provides a technical preview rather than a complete scenario-analysis workflow.
- Scenario execution and reporting are not yet exposed through the web API.
- Automated mitigation-menu optimisation remains future work.
- Published-reference comparisons do not yet establish independent end-to-end validation of the complete multi-node engine.

## [0.0.1] - 2026-09-26

### Added

- Initial Python package and `daysofcover --version` command.
- Strict Pydantic schemas for supply networks, scenarios, mitigation options and results.
- Reproducible Moreton Marine Systems synthetic network and generator.
- Network-validation CLI command.
- Initial Svelte technical preview and FastAPI health endpoint, packaged in Docker and configured for Render.
- Fast, full, nightly and release GitHub Actions workflows, including linting, typing, tests, build verification and container publishing.
- Project governance files, pre-commit checks, architecture decision records and documentation structure.

[Unreleased]: https://github.com/NathanTaylorOps/DaysofCover/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/NathanTaylorOps/DaysofCover/releases/tag/v0.0.1
