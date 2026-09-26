# ADR-008: Own daily-step engine over SimPy, with the spike's numbers

- Status: Accepted
- Date: 2026-09-26

## Context

The build plan's Decisions table named "own daily-step loop with NumPy
state arrays" as the intended design for the simulation engine, explicitly
deferring confirmation to a one-session spike at the start of Stage 1: one
node, a base-stock family of policies, checked against validation cases 1
to 3. SimPy was the named alternative -- not a fallback (a different state
model entirely), but the thing this spike had to be measured against
before nine sessions of engine work were built on the chosen shape.

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

## The spike

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

All three passed comfortably inside their stated tolerance on the first
correct implementation -- no retries needed to hit the numbers, which is
itself evidence the state-array shape maps cleanly onto the policies it
has to represent. Case 3's reference is stockpyl's own published worked
example for that named instance (cited, not recomputed): stockpyl is not
a runtime or test dependency, so this validation has no dependency on it
being installable in every environment that runs the suite.

2,000 replications of case 2 (200 days each, NumPy-vectorised across
replications) and 200,000 days of case 3 (a sequential Python loop, one
state per day, on purpose -- see below) both run in well under a second
on a laptop core. Nothing here yet exercises the 200 ms / 40-node / 25-part
target from the build plan; that is a full-network profiling pass at the
end of Stage 1, not this spike.

## Consequences

- The multi-node engine (the remaining eight Stage 1 sessions) generalises
  this same loop -- state per (node, part) instead of per node, a BOM
  production step, allocation and split rules, a replication runner with
  entity-indexed common random numbers -- rather than changing its shape.
  The spike's job was to confirm the shape, not to be thrown away.
- No SimPy dependency is added to the project.
- `scipy` is added as a dev dependency (not a runtime one) for
  `scipy.stats.poisson`, used by case 2's closed-form comparator. `scipy`
  becomes a runtime dependency later, at Stage 2, for `scipy.optimize`
  (HiGHS, per ADR-002); nothing changes about that when it happens.

## Alternatives considered

- **SimPy.** Mature and well-documented for process-oriented DES, but its
  process/event model does not match state that is naturally a set of
  arrays stepped together once a day; using it would mean either
  reshaping the state to fit SimPy's process model (adding a layer that
  touches the state for no benefit at this scale) or using SimPy for
  nothing but the event heap it was never providing a benefit for in the
  first place. Ruled out by the spike's numbers landing cleanly on the
  loop-only design, not just by the argument above.
- **A narrower v0.1 scope.** The plan's own contingency: if the spike had
  failed to hit the tolerances, the fallback was to narrow v0.1's scope
  rather than change the engine's design. Not needed -- the spike passed.
