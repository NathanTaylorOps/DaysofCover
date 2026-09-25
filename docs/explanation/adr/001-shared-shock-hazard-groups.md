# ADR-001: Shared-shock hazard groups over independent node failures

- Status: Accepted
- Date: 2026-09-25

## Context

The engine needs a model for how disruptions arrive. The simplest option is
to give every node and lane its own independent failure probability. Real
supply chain disruptions are not independent: a typhoon, a port closure or
a regional lockdown hits several suppliers, ports and lanes at once because
they share a location or a cause. A model that treats failures as
independent will understate the chance of simultaneous outages and produce
resilience numbers that are optimistic in exactly the scenarios that matter
most (two or three things going wrong together).

## Decision

Model disruption arrivals as shared-shock hazard groups: a `HazardGroup` is
a shared-shock source with its own monthly rate profile (a piecewise-constant
non-homogeneous Poisson process), a severity distribution (Beta, fraction of
capacity lost) and a hazard duration distribution (lognormal, days). Each
node or lane can belong to one or more hazard groups with a per-member hit
probability. When a group event fires, every member is hit independently
with its own probability, sharing the group's severity and duration draw.
Elements also carry an idiosyncratic hazard (e.g. a single supplier's own
fire) on top of their group memberships.

This is a Marshall-Olkin style construction: it gives positive correlation
between failures without needing a copula, which is the structure used in
Gao, Simchi-Levi, Teo and Yan (Operations Research 67(3), 2019) and is the
best-supported correlation model in the supply chain disruption literature.
No supply chain paper found in the research pass uses copulas for
disruption arrivals.

`region` (geographic, one per node or lane, drives layout and lead-time
parameters) is kept as a separate field from `hazard_group` (a sampling
construct, many per element). Conflating the two would force every node in
a region to share exactly one shock source, which is wrong when, for
example, a port closure and a supplier fire in the same region are
uncorrelated events.

## Consequences

- The sampler draws one event per hazard group per period, then rolls each
  member's hit probability, rather than one independent roll per element.
- Rate inputs are shipped as template defaults with a source and a notes
  field; the methodology page documents how to derive a rate from a
  company's own incident log, but the tool does not run that estimator
  itself.
- Worst-case analysis (ADR-009) enumerates pairs across groups and triples
  within a group, because within-group co-occurrence is far more likely
  than an arbitrary pair of elements failing together.
- The scenario schema carries named disruptions as an override on top of
  the sampler, so a specific story (e.g. "Cyclone Alfred closes Port of
  Brisbane for 9 days") can be authored directly without going through the
  hazard-group machinery.

## Alternatives considered

- **Independent per-element failure probability.** Simpler to implement and
  reason about, but cannot produce the correlated multi-failure scenarios
  that are the actual point of a stress test.
- **Copula-based joint distribution over all elements.** Expressive, but no
  surveyed supply chain disruption paper uses this, it requires specifying
  a full correlation structure with no obvious source data, and it does not
  map cleanly onto "which shared cause produced this event," which the
  attribution rule needs.
