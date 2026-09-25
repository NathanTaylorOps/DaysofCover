# Reference

Information-oriented, generated documentation: this directory holds output
generated from the code itself rather than hand-written prose, so it cannot
drift out of sync with what the tool actually does.

Planned sources, wired up as each becomes available:
- CLI reference generated from `--help` output for every `daysofcover`
  subcommand (Typer's help text is the source of truth).
- API reference generated from the FastAPI OpenAPI schema.
- Schema reference generated from the Pydantic v2 models in
  `src/daysofcover/models/`.

Nothing generated yet — the CLI, API and schema this will be generated from
are built in later stages (see the build plan's stage table). This
directory is scaffolding so the generation targets have a home from
Stage 0.
