# ADR-004: Separate container UI packaging from Python wheel

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

`web_static/` is not packaged into the wheel before v1.0. The Docker image builds the Svelte frontend and serves its static output
alongside the FastAPI application. The current frontend is a technical
preview; it does not execute supply-chain scenarios. The static public demo host gets the same SPA build directly, not
through the wheel. The wheel itself ships the engine, CLI and API only from
v0.1 through v0.2.

A future release may add wheel artifacts for
`web_static/**` and `data/**`, and the build fails if `web_static/index.html`
is absent — this packaging change is not yet implemented.

## Consequences

- The container can be built and deployed independently of the complete
  scenario-analysis interface.
- Two release artifacts (the wheel and the Docker image) diverge in
  contents until v1.0: the wheel is headless from v0.1 to v0.2, the image contains the current frontend preview. This is stated plainly in each
  release's README rather than treated as a defect.
- The hatch build-hook failure mode (missing `web_static/index.html`) is
  only wired in at v1.0, once there's something real to fail on; adding it
  earlier would just be a permanently-failing check with no useful signal.
- The Dockerfile and Render configuration define the current container
  deployment; the packaging design should be revisited when the scenario
  interface is ready.

## Alternatives considered

- **Bundle the wheel from Stage 0 with a build-hook stub.** Rejected: adds
  Node-toolchain requirements to every Stage 0–5 `uv build` and CI run for
  a check that has nothing real to validate until Stage 6.
- **Never bundle into the wheel; hosted image and static site only.**
  Rejected: the portfolio pitch is explicitly "one command, no toolchain,"
  and `pip install daysofcover` giving only a headless CLI forever would
  undercut the v1.0 story that the same project header promises.
