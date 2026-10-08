# Days of Cover

**Supply-chain resilience modelling for operational decisions.**

> If a supplier, port, facility or transport route is disrupted, where does the network become constrained, how long can existing inventory support demand, and what should management investigate first?

Days of Cover is a Python-based supply-network analysis project that combines **inventory and disruption simulation**, **linear-programming models of supply coverage**, and **structural dependency screening**. It is designed to turn a complex supplier network into questions an operations leader can evaluate: continuity, exposure, constraints and mitigation trade-offs.

**Project status: active development.** The simulation and optimisation libraries, command-line analysis and automated validation are implemented in varying degrees; the hosted Svelte interface is currently a **technical preview**, not a working stress-test dashboard. The mitigation-selection optimiser and complete scenario-running web experience are not yet implemented. This README distinguishes the capabilities available now from the intended product.

[Explore the example network](src/daysofcover/data/examples/moreton_marine/README.md) · [Validation evidence](VALIDATION.md) · [Architecture decisions](docs/explanation/README.md) · [Changelog](CHANGELOG.md)

## The operating problem

Supply networks can appear resilient on an organisational chart while depending on one qualified part, one transport lane or one production constraint. Equally, a supplier that looks critical in a network diagram may have enough downstream inventory to absorb a temporary outage.

A useful decision requires more than a list of dependencies:

- **Structure:** Which customer/SKU flows lose a viable supply path if an element fails?
- **Coverage:** How much time can inventory and remaining capacity buy under a specified disruption?
- **Operations:** What happens when lead times, shipment timing, production, ordering rules and shared components interact?
- **Action:** Which assumptions or constraints should management investigate before committing working capital or changing suppliers?

Days of Cover treats these as related but **different analytical questions**. A structural screen is not a stockout forecast; an aggregate optimisation bound is not a day-by-day simulation.

## What is available today

| Capability | Implementation | How to access it |
| --- | --- | --- |
| Strict supply-network schema and validation | Implemented | Python models; `daysofcover validate` |
| Reproducible synthetic example network | Implemented | Moreton Marine fixture and generator |
| Inventory, shipments, production, allocation and disruption building blocks | Implemented with unit/property coverage | Python engine modules |
| Daily-step multi-node operational model | Implemented and exercised by tests; end-to-end external validation remains bounded | Python API |
| Aggregate LP cover, impact and buffer analysis | Implemented | Python LP modules; cover ranking via CLI |
| Weekly time-indexed cover analysis | Implemented | Python LP module |
| AND/OR supply-dependency screen | Implemented | Python module; CLI cover ranking |
| Reference comparisons and automated test workflows | Implemented | `VALIDATION.md`, `tests/`, GitHub Actions |
| Hosted interactive stress-test dashboard | **Not yet implemented** | Current web deployment is a health-check preview |
| Scenario execution API and management report | **Not yet implemented** | Planned integration work |
| Automated mitigation-menu optimiser | **Not yet implemented** | Mitigation schema exists; optimiser remains future work |

“Implemented” describes the code currently present; it does not imply that every component has been connected into a finished decision workflow. See [validation scope](#validation-and-model-boundaries).

## Example: Moreton Marine Systems

The included **Moreton Marine Systems** dataset is a fictional Brisbane-based manufacturer of commercial marine electronics. It is synthetic and reproducibly generated; it is not customer data or a claim about a real company's operations.

| Network dimension | Example |
| --- | ---: |
| Nodes | 33 |
| Transport lanes | 33 |
| Parts | 25 |
| Finished-product SKUs | 6 |
| Hazard groups | 6 |
| Modelled annual revenue | AUD 27.016 million |

The example includes suppliers, materials, production and customer demand. Its purpose is to let a reviewer inspect how a network's structure and inventory assumptions change disruption exposure. The revenue figure is **synthetic input data**, not a measured commercial result.

[Inspect the dataset and assumptions](src/daysofcover/data/examples/moreton_marine/README.md)

## Try the working command-line tools

Requires **Python 3.12+** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/NathanTaylorOps/DaysofCover.git
cd DaysofCover
uv sync --locked

# Validate the included example network
uv run daysofcover validate

# Inspect structural exposure and LP-based cover ranking
uv run daysofcover cover --help

# Run the test suite
uv run pytest
```

The `cover` command accepts a `--state` JSON file containing starting inventory. **Without starting inventory, it assumes zero on-hand stock**, so cover figures can be zero or unbounded and are not a meaningful operational assessment. See `uv run daysofcover cover --help` for the state-file format. Do not interpret a default-state ranking as a business recommendation.

The Python modules expose additional modelling functions not yet assembled into a public end-to-end CLI or web workflow.

### Hosted preview

The repository includes a Dockerised Svelte frontend served by FastAPI and a `/health` endpoint. The currently deployed interface is a **deployment/health preview only**. It cannot yet run the stress-test workflow described in the product vision.

The Render deployment is configured through [`render.yaml`](render.yaml); availability of any particular hosted instance should be checked before publishing a live-demo link.

## How the analysis works

1. **Represent the network.** Pydantic models define nodes, lanes, parts, products, customers, demand and relevant operating constraints.
2. **Screen structural dependencies.** An AND/OR model asks whether a viable path remains for every required part and finished product. It does not model available stock or time.
3. **Estimate coverage using optimisation.** Aggregate and weekly LP formulations assess supply feasibility and inventory runway under stated assumptions. These are analytical models, not realised performance.
4. **Represent operational dynamics.** Daily-step simulation components track inventory, shipments, production, replenishment, disruption states and allocation rules.
5. **Validate and compare.** Unit tests, property tests and reference cases check specified behaviours and numerical bounds; further end-to-end comparison remains important as integration proceeds.

The LP and simulation layers answer different questions and may disagree for legitimate reasons, including lead times, ramp-up, lot sizes and replenishment behaviour. A difference should be investigated and explained, not hidden behind one composite score.

### Technology and architecture

| Layer | Main tools | Purpose |
| --- | --- | --- |
| Models and validation | Python, Pydantic | Explicit, strictly validated network and scenario inputs |
| Dynamic engine | Python, NumPy | Inventory, shipment and production state transitions |
| Optimisation | SciPy / HiGHS | Coverage, impact, inventory buffers and weekly feasibility |
| Command line | Typer | Network validation and exposure ranking |
| Web service | FastAPI | Current health endpoint and static frontend hosting |
| Frontend | Svelte 5, TypeScript, Vite | Currently a technical preview |
| Quality and deployment | pytest, Hypothesis, Ruff, mypy, Docker, GitHub Actions | Automated checks and reproducible packaging |

Design choices are recorded in [eight architecture decision records](docs/explanation/README.md), including the rationale for a custom daily-step engine, shared-shock hazard groups, linear programming and a stateless API design.

## Validation and model boundaries

The [generated validation report](VALIDATION.md) documents numerical reference cases, their assumptions and tolerances. It covers selected inventory policies, disruption processes, shipment pipelines, bullwhip behaviour and recovery patterns.

**Important distinction:** several published-reference comparisons validate standalone, single-purpose implementations rather than the entire multi-node daily-step engine. The multi-node implementation also has unit and property tests, but that is not equivalent to an independent, end-to-end analytical benchmark. The validation report states this limitation explicitly.

Other important boundaries:

- Inputs are estimates or synthetic examples; output quality depends on network, inventory, demand and recovery assumptions.
- Structural dependency exposure is not the same as time-to-stockout or financial loss.
- Aggregate LPs simplify the timing and operating friction represented in dynamic simulation.
- A modelled revenue or margin exposure is not a realised financial outcome.
- The full scenario orchestration, user-facing reporting and automated mitigation selection are still in development.
- The application is decision support, not a substitute for supplier due diligence, procurement judgement or a production planning system.

## Development direction

The next meaningful milestone is **one verified end-to-end management scenario**, not a larger catalogue of disconnected features:

1. Connect a bounded scenario-execution API to the existing analytical components.
2. Present a baseline and a selected disruption in the Svelte interface.
3. Clearly label structural results, LP estimates and simulation outputs.
4. Provide understandable assumptions, solver/error states and reproducible results.
5. Add frontend/API integration tests and a worked Moreton Marine decision case study.
6. Only then expand to mitigation comparisons and optimisation where supported by validated implementation.

Progress and implementation details belong in the [changelog](CHANGELOG.md); completed features will be reflected here only when verified.

## Repository guide

- [`src/daysofcover/engine/`](src/daysofcover/engine/) — operational simulation components
- [`src/daysofcover/lp/`](src/daysofcover/lp/) — optimisation and structural screening
- [`src/daysofcover/models/`](src/daysofcover/models/) — validated network and scenario schemas
- [`src/daysofcover/data/examples/moreton_marine/`](src/daysofcover/data/examples/moreton_marine/) — reproducible synthetic example
- [`src/daysofcover/cli.py`](src/daysofcover/cli.py) — command-line interface
- [`src/daysofcover/api/main.py`](src/daysofcover/api/main.py) — web service
- [`web/`](web/) — Svelte frontend
- [`tests/`](tests/) — unit, property and validation tests
- [`docs/explanation/adr/`](docs/explanation/adr/) — architectural decisions

## Why this project belongs in an operations portfolio

The objective is to make supply continuity and working-capital exposure more transparent: understand which constraints matter, distinguish structural vulnerability from actual inventory runway, and communicate the trade-offs behind an operational decision.

The technical work is valuable only when its assumptions, limitations and results can be understood by the people responsible for procurement, production, service levels and capital allocation.

## Licence

MIT — see [LICENSE](LICENSE).
