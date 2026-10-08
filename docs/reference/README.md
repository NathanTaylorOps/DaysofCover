# Reference

Information-oriented, generated documentation: this directory holds output
generated from the code itself rather than hand-written prose, so it cannot
drift out of sync with what the tool actually does.

Reference sources to consolidate as the public interfaces mature:
- CLI reference generated from `--help` output for every `daysofcover`
  subcommand (Typer's help text is the source of truth).
- API reference generated from the FastAPI OpenAPI schema.
- Schema reference generated from the Pydantic v2 models in
  `src/daysofcover/models/`.

The CLI and Pydantic schemas are implemented; the hosted API currently
exposes health information but not scenario execution. Generated reference
pages have not yet been added. Until then, use `daysofcover --help`,
`daysofcover cover --help`, and the Python model definitions as the
current interface references.
