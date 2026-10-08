# ADR-008: Daily-step NumPy engine over SimPy

- Status: Accepted
- Date: 2026-09-26

## Context

The architecture assessment identified "own daily-step loop with NumPy
state arrays" as the intended design for the simulation engine, subject to confirmation by a focused reference-validation exercise: one
node, a base-stock family of policies, checked against validation cases 1
to 3. SimPy was the named alternative -- not a fallback (a different state
model entirely), but the thing this spike had to be measured against
before extending the engine to a multi-node network.

The real engine's state is naturally a set of arrays indexed by (node,
part): on-hand, on-order, backlog, plus per-shipment in-transit records.
Time advances in daily steps for demand, shipments and production, with
weekly order review; a small event heap only carries disruption starts and
ends, shipment arrivals and reroute activations. SimPy models a system as
a set of independent generator-based processes synchronised through an
event queue, which is a good fit for entities that each have their own
control flow (customers, machines, trucks) and a poor fit for state that
is naturally columnar and stepped in lockstep once a day, at the 40-node,
25-part, 200 ms-per-replication scale this project targets.

## Decision

Build the engine as a plain Python/NumPy loop stepping one day at a time,
not a set of SimPy processes.

## Validation evidence

`src/daysofcover/engine/single_node.py` implements three single-node
policy simulators on exactly this shape (continuous-review base-stock,
periodic-review (R, S), periodic-review (s, S), each a loop over
`n_days` mutating NumPy-backed state) and validates them against
cases 1 to 3:

| Case | Reference | Tolerance | Result |
| --- | --- | --- | --- |
| 1. Single node, constant demand, deterministic lead time, base-stock | Analytical steady-state inventory and fill rate | exact | on-hand 10.0 == 10.0, fill rate 1.0 == 1.0 |
| 2. Periodic-review base-stock (R, S), Poisson demand | Fill rate = 1 - [E(D_{R+L} - S)+ - E(D_L - S)+] / E(D_R) | 2% over 2,000 replications | simulated 0.9198 vs formula 0.9195 (diff 0.03%) |
| 3. (s, S) with discrete demand | stockpyl's exact discrete (s, S) evaluation (Zheng and Federgruen), named instance s=4, S=10, h=1, p=4, K=5, Poisson mean 6, published cost 8.034112 | 2% | simulated 8.0303 (diff 0.047%) |

All three reference cases passed within their stated tolerances. These
results support the implementation's numerical correctness for the tested
inventory policies, but do not constitute a comparative SimPy benchmark. Case 3's reference is stockpyl's own published worked
example for that named instance (cited, not recomputed): stockpyl is not
a runtime or test dependency, so this validation has no dependency on it
being installable in every environment that runs the suite.

2,000 replications of case 2 (200 days each, NumPy-vectorised across
replications) and 200,000 days of case 3 (a sequential Python loop, one
state per day, on purpose -- see below) both run in well under a second
on a laptop core. These single-node tests do not establish performance against the separate
40-node, 25-part network objective; representative full-network profiling
is required.

## Consequences

- The multi-node engine generalises this daily-step loop -- state per (node, part) instead of per node, a BOM
  production step, allocation and split rules, a replication runner with
  entity-indexed common random numbers -- rather than changing its shape.
  The reference cases establish a reusable numerical foundation.
- No SimPy dependency is added to the project.
- SciPy supports both statistical reference calculations and the LP
  optimisation layer described in ADR-002.

## Alternatives considered

- **SimPy.** Mature and well-documented for process-oriented DES, but its
  process/event model does not match state that is naturally a set of
  arrays stepped together once a day; using it would mean either
  reshaping the state to fit SimPy's process model (adding a layer that
  touches the state for no benefit at this scale) or using SimPy for
  nothing but the event heap it was never providing a benefit for in the
  first place. The selected daily-step implementation met its reference-validation
  criteria without requiring a process-oriented framework.
- **Reduced initial scope.** Narrowing the supported inventory policies
  remained an option if the reference checks failed; the tested policies
  met their acceptance tolerances.
