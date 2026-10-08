# ADR-007: Svelte Flow over Cytoscape.js

- Status: Accepted
- Date: 2026-09-25

## Context

The network view (tiered supplier → plant → customer graph, with region
highlighting and a culprit-highlight overlay during a scenario) needs a
graph-rendering library. Cytoscape.js was also evaluated as an alternative graph renderer. The front-end
stack is Svelte 5 with a hard SPA bundle-size budget of 300 KB gzipped JS
total (echarts/core roughly 150-200 KB, the app itself roughly 50 KB),
leaving a narrow allowance for a graph library plus a layout engine.

## Decision

Use Svelte Flow (the `@xyflow/svelte` package) with `@dagrejs/dagre` for
tiered layout, rather than Cytoscape.js.

Reasoning:

- Svelte Flow is native Svelte with no wrapper/adapter layer; Cytoscape.js
  has no official Svelte binding, so using it would mean hand-rolling and
  maintaining a Svelte wrapper around an imperative, framework-agnostic
  library.
- Svelte Flow documents keyboard and ARIA behaviour for its nodes and
  edges; the UI section's accessibility requirements (keyboard-reachable
  network view, Lighthouse accessibility ≥ 90) need that documented
  behaviour rather than something built from scratch on top of a
  canvas/SVG renderer with no accessibility contract.
- Svelte Flow supports parent/child node nesting, which maps directly onto
  the region-highlight requirement (grouping nodes by geographic region as
  parent containers) without a custom grouping layer.
- Measured bundle cost (Svelte Flow ~40 KB, dagre ~30 KB gzipped) fits
  comfortably inside the 300 KB budget alongside ECharts, as an initial size estimate; final bundle sizes must be measured against
  the built application.

## Consequences

- The planned network view uses `@xyflow/svelte` nodes/edges with a
  `dagre`-computed tiered layout (suppliers → ports/hubs → plant →
  customers) recomputed when the network or highlight state changes.
- The proposed region-highlighting design uses Svelte Flow parent nodes rather than a custom
  bounding-box overlay.
- Any future large-network view (the 100/200-node synthetic benchmark
  networks are for performance testing only, not for this view) would need
  its own layout strategy if Svelte Flow's default layout becomes
  visually unusable at that scale; this is out of scope for v1.
- Dependency versions should be controlled and bundle-size and accessibility
  requirements verified when the graph view is implemented.

## Alternatives considered

- **Cytoscape.js.** More mature and graph-algorithm-rich, but no Svelte
  binding, no documented accessibility behaviour, and a real risk of
  blowing the bundle budget on its own, and potentially higher integration and bundle-size costs.
- **Hand-rolled SVG/Canvas graph view.** Full control and smallest
  possible bundle, but reimplements layout, panning/zooming, keyboard
  navigation and accessibility from nothing, none of which is the point of
  this project.
