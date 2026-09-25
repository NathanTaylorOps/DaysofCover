# Security

## Scope

Days of Cover is a simulation tool. It runs locally as a Python package and command line, and as a public demo that accepts scenario and network JSON over an HTTP API. The demo has no accounts, stores no data and holds no secrets. The threats that matter are malformed or oversized input, resource exhaustion of the free demo server, and compromised dependencies. Controls for each are described in `docs/explanation/ARCHITECTURE.md` as they land.

## Reporting a vulnerability

Report privately through GitHub: open the repository's Security tab and choose "Report a vulnerability". Include what you found, how to reproduce it, and the version or commit. Expect an acknowledgement within seven days and a fix or a written decision within thirty.

Please do not open a public issue for a security problem.

## Supported versions

The latest release on PyPI and the `main` branch receive fixes. Older releases do not.
