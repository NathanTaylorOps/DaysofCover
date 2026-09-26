# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.0.1] - 2026-09-26

### Added

- Package skeleton with a `daysofcover --version` command.
- Pre-commit hooks: ruff, gitleaks and the standard file checks.
- `fast` CI workflow: lint, format, types, tests on Python 3.12 and 3.13, wheel build and smoke test, Docker image build and push to GHCR on `main`.
- `full`, `nightly` and `release` CI workflows.
- Project governance: licence, citation file, security policy, contributing guide, code of conduct, issue and pull request templates.
- ADR-001 through ADR-007, and a Diataxis-shaped docs skeleton (tutorials, how-to, reference, explanation).
- Schema v0: Pydantic models for the network, its mitigation options, a stress-test scenario and its results, all strict-mode and referentially validated.
- A seeded, deterministic example network (Moreton Marine Systems, a fictional Brisbane marine-electronics manufacturer) and the generator that produces it.
- A `daysofcover validate` command that checks a network file against the schema.
- A hello-world Svelte front end and a FastAPI `/health` endpoint, both served from a single Docker image built in CI and deployed to Render.

[Unreleased]: https://github.com/NathanTaylorOps/DaysofCover/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/NathanTaylorOps/DaysofCover/releases/tag/v0.0.1
