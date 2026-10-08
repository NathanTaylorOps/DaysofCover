# Bounded scenario release readiness

Passing CI does not by itself establish production readiness.

## Supported scope

- Deterministic bounded single-plant scenario comparison via FastAPI and Svelte.
- Bundled illustrative scenario and synthetic structural exposure examples.
- Python simulation, LP and structural analysis with documented validation boundaries.

## Not supported as a finished hosted product

- General multi-node scenario execution or automated mitigation optimisation.
- Authenticated multi-user operation, persistent scenarios or asynchronous workloads.
- Guaranteed financial or operational outcomes.

## Release acceptance checklist

- [ ] Fast and full CI pass on the exact release commit.
- [ ] Browser, API and numerical regression tests pass on that commit.
- [ ] Measure Python coverage and establish a defensible nonzero threshold.
- [ ] Review dependencies, security findings and third-party licenses.
- [ ] Run the exact release container image; verify `/health`, static assets and example scenario.
- [ ] Verify hosted startup, response latency, resource use and restart behaviour.
- [ ] Check request limits, unsupported media types and invalid-input responses.
- [ ] Reconcile README, changelog, example assumptions and validation evidence.
- [ ] Record a release version, immutable image digest and rollback procedure.
- [ ] Document known limitations and operational ownership.

## Evidence required

Record the release commit, CI URLs, container digest, deployed URL, measured coverage, smoke-test results and unresolved issues before marking checks complete.

**Release decision: pending acceptance evidence.**
