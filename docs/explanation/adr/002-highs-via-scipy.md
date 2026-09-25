# ADR-002: HiGHS via scipy.optimize over OR-Tools

- Status: Accepted
- Date: 2026-09-25

## Context

The cover, impact and buffer LPs (per element, per scenario) and the fixes
MILP need an LP/MILP solver. Candidates considered: Google OR-Tools (CBC or
its own solvers), a direct HiGHS binding (`highspy`), and HiGHS through
`scipy.optimize.linprog` / `scipy.optimize.milp`, which SciPy has shipped
its own HiGHS interface for since SciPy 1.9.

## Decision

Use HiGHS through `scipy.optimize.linprog` and `scipy.optimize.milp`, with
`time_limit` and `mip_rel_gap` passed through on the MILP calls. No
`highspy` or OR-Tools dependency in v1.

Reasoning:

- SciPy is already a hard dependency for the rest of the numerical stack
  (NumPy arrays, distributions for hazard sampling and PERT recovery
  fitting), so this adds no new dependency.
- HiGHS is open source, actively maintained, and fast enough at this
  scale: the cover LP set (~110 elements on the demo network) is designed
  to solve in seconds, and the fixes MILP is sized (≤100 scenarios, ≤20
  binaries, ≤80k variables) to finish under 10 seconds on one laptop core.
- `scipy.optimize` has no persistent solver object between calls, so each
  solve is a full re-solve from prebuilt sparse matrices. This is
  acceptable at the sizes in scope and is stated as a limitation rather
  than hidden.

## Consequences

- LP and MILP construction code builds sparse matrices once per element or
  scenario set and re-solves from scratch; there is no warm-start reuse
  across the ~110 per-element LPs.
- `mypy` treats `scipy.optimize` as unstubbed (SciPy ships no type stubs);
  `scipy-stubs` is added as a dev dependency to keep strict typing on the
  `analytics/` and `optimise/` modules that call into it.
- If a future stage needs solves at a scale where re-solve-from-scratch
  becomes the bottleneck, a `highspy` binding for persistent models is the
  documented escape hatch, not a solver swap.

## Alternatives considered

- **`highspy` (direct HiGHS Python binding).** Would allow persistent
  models and incremental re-solves, but adds a dependency with less
  SciPy-ecosystem integration for a benefit that is not needed at this
  problem size.
- **OR-Tools.** Broader solver portfolio and a mature MILP interface, but a
  much heavier dependency (bundled native solvers, larger wheel) for
  capability this project does not need, and it would be the only
  non-SciPy numerical dependency in the stack.
