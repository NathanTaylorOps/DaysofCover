# ADR-006: AND/OR flow-weighted screen over centrality

- Status: Accepted
- Date: 2026-09-25

## Context

Before running LPs or simulations on every node and lane, the tool needs a
cheap structural screen to prioritise which elements are worth a closer
look, and to draw an "everything goes through here" view of the network.
The obvious off-the-shelf choices are graph centrality measures
(betweenness, degree, PageRank) and ordinary path reachability
(articulation points, bridges).

Both are a poor fit here. Ivanov's own study of disruption impact found
node degree essentially unchanged while service fell by about 40%; a
1,369-node automotive supply network study found degree, betweenness and
PageRank collinear with each other and only weakly related to actual
disruption outcomes. More fundamentally, ordinary path reachability is
*wrong* on a bill-of-materials network: a SKU needs every one of its parts
from some qualified supplier, so a SKU is not "still reachable" just
because one of its 25 parts still has a path — losing any single part with
no backup stops that SKU regardless of how connected everything else is.

## Decision

Build a purpose-specific AND/OR cut over the BOM instead of using any
centrality measure. Element `e` is a chokepoint for a `(customer k, SKU s)`
pair if, with `e` removed, either: some part in `BOM(s)` has no remaining
supplier with a path to the plant (an AND condition — a SKU needs *all* of
its parts), or the plant has no remaining path to `k` (an OR condition
across path alternatives to the customer). The convergence fraction of `e`
is the value of the `(k, s)` pairs it cuts, divided by total value.

This is explicitly a **screen, never a score**: its only job is to decide
which elements, pairs and triples get LP and simulation runs first, and to
drive the "everything goes through here" visualization. It does not itself
rank business impact — that is what the cover/recovery simulation does.
Implemented as a small recursive function over the BOM graph (not a
NetworkX centrality call), tested against a three-node chain by hand.
Articulation points, bridges and betweenness are not computed anywhere in
the product.

## Consequences

- The first screen's headline finding is allowed to disagree between
  "structure" (this AND/OR screen, ranked by share of flow) and
  "simulation" (ranked by cover versus recovery time) — that disagreement
  is the actual insight the tool surfaces, not a bug to reconcile away.
  Example from the demo network: the Singapore transhipment hub is a
  100%-convergence structural chokepoint that barely matters in practice
  (a five-day closure is absorbed by six weeks of cover and an air
  alternative), while a single-sourced module with two weeks of cover and
  a 13-week recovery is the real exposure.
- The screen only needs the BOM, the supplier-path graph and per-pair
  value (price × volume); it needs no capacity, lead-time or hazard data,
  which is why it can run before any LP or simulation and cheaply narrow
  the set that gets the expensive treatment.
- Because this pattern holds on any realistic BOM network with shared
  parts, the demo network needs at most one time-boxed tuning session to
  produce a clean story, not repeated hand-tuning against a moving target.

## Alternatives considered

- **Betweenness / degree / PageRank centrality.** Rejected on the evidence
  above: weak and confounded relationship to actual disruption impact on
  BOM-shaped networks, and available off the shelf via NetworkX at the
  cost of building something that measurably doesn't answer the question.
- **Plain reachability (articulation points / bridges).** Rejected because
  it is provably wrong on an AND-structured BOM: a cut vertex on the
  customer-facing graph says nothing about a part with no backup supplier.
