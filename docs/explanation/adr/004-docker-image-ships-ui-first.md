# ADR-004: Docker image ships UI and precomputed results from Stage 0; wheel bundling deferred to v1.0

- Status: Accepted
- Date: 2026-09-25

## Context

The project ships three things that could each carry the Svelte front end:
the PyPI wheel (`pip install daysofcover`), a Docker image (what Render
pulls), and a static host for the public demo SPA. Building the front end
into the wheel from day one means every wheel build in Stage 0 through
Stage 5, while the UI does not exist yet, would need a UI build step, a
Node toolchain in the packaging pipeline, and hatch build hooks that fail
if `web_static/` is missing — none of which has anything to test against
until the SPA exists (Stage 6 onward).

## Decision

`web_static/` is not packaged into the wheel before v1.0. From Stage 0, the
Docker image is built in CI with whatever front end exists at that point
(a hello-world placeholder page initially, the real SPA from Stage 6
onward) plus precomputed demo results, and that is what Render pulls and
serves. The static public demo host gets the same SPA build directly, not
through the wheel. The wheel itself ships the engine, CLI and API only from
v0.1 through v0.2.

At v1.0, once the SPA is stable, `hatch build` gains artifacts for
`web_static/**` and `data/**`, and the build fails if `web_static/index.html`
is absent — at that point `pip install daysofcover` or
`uvx daysofcover demo` gives the complete tool with no Node toolchain
required by the end user.

## Consequences

- Stage 0's Docker/CI setup can be built and tested against a trivial
  placeholder page, decoupled from when the real SPA is ready.
- Two release artifacts (the wheel and the Docker image) diverge in
  contents until v1.0: the wheel is headless from v0.1 to v0.2, the image
  always carries whatever UI exists. This is stated plainly in each
  release's README rather than treated as a defect.
- The hatch build-hook failure mode (missing `web_static/index.html`) is
  only wired in at v1.0, once there's something real to fail on; adding it
  earlier would just be a permanently-failing check with no useful signal.
- `render.yaml` and the Dockerfile are Stage 0 deliverables that do not
  change shape when the SPA lands later; they always copy whatever is
  under `web_static/` at build time.

## Alternatives considered

- **Bundle the wheel from Stage 0 with a build-hook stub.** Rejected: adds
  Node-toolchain requirements to every Stage 0–5 `uv build` and CI run for
  a check that has nothing real to validate until Stage 6.
- **Never bundle into the wheel; hosted image and static site only.**
  Rejected: the portfolio pitch is explicitly "one command, no toolchain,"
  and `pip install daysofcover` giving only a headless CLI forever would
  undercut the v1.0 story that the same project header promises.
