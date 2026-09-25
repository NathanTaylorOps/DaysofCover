# ADR-005: Recovery as a three-point input with ramp recovery, never an output

- Status: Accepted
- Date: 2026-09-25

## Context

Time-to-recover (TTR) is the other half of the Simchi-Levi TTS/TTR method
alongside time-to-survive. An earlier draft of this plan treated a
17-week "time to full shipments" figure as an input default. That number is
actually a *consequence* of production recovery plus the time it takes to
work off backlog at a given utilisation — it is an engine output, not
something that can also be fed in as an input without double counting.

## Decision

Recovery is always a user-supplied estimate, per node and per lane, entered
as a three-point estimate `(min, likely, max)` in days and fitted with a
PERT distribution (Beta, λ = 4) to derive P50 and P80 (triangular is offered
as a simpler option). This is exactly what the Simchi-Levi method
prescribes: recovery time is an input the user provides based on their own
knowledge of a supplier or route, not something the tool infers.

Recovery is modelled as a ramp, not a step: capacity returns linearly over
`ramp_days` after the hazard ends, with a default shape drawn from the
Renesas 2021 fire record (restart at 29 days, full output 69 days later).
The engine tracks backlog explicitly, so the *shipment* recovery lag behind
*production* recovery — the 17-week-shaped number from the earlier draft —
falls out of the simulation as a validation assertion (case 13: at 90%
plant utilisation the engine should reproduce a shipment-recovery lag of
about three weeks behind production recovery), never as a parameter anyone
sets.

`hazard_duration` (how long the cyclone, strike or closure itself lasts,
drawn from the hazard group) and a node's own `recovery_days` are kept as
separate quantities in the schema: total downtime = hazard duration +
recovery, and the two are elicited, modelled and validated independently.

## Consequences

- The LP layer uses the node's P80 recovery plus the hazard group's P80
  duration when scoring a group-driven scenario; the simulation layer uses
  the full ramp and backlog dynamics.
- Nothing in the schema or the CLI accepts a "time to full shipments" or
  "time back to normal" field as an input — those are always computed and
  reported, with the observed-recovery rule (docs/explanation/METHODOLOGY.md)
  saying exactly how.
- Validation case 12 (ramp bounds) and case 13 (shipment lag) exist
  specifically to keep this consequence honest: the ramp must sit between a
  step-at-restart and step-at-restart-plus-ramp for lost sales, and the
  lag must come out in the right ballpark without being asserted directly.

## Alternatives considered

- **Accept both a recovery estimate and a "time to full shipments" figure
  as separate inputs.** Rejected: the two are not independent (the second
  is a function of the first plus utilisation and backlog dynamics), so
  accepting both invites inconsistent inputs and double-counts the same
  underlying delay.
- **Step recovery (capacity returns to 100% instantly at recovery time).**
  Simpler, but materially wrong for the physical processes being modelled
  (a restarted fab or reopened port does not instantly run at full
  throughput) and would fail case 12 by construction.
