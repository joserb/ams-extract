# ams-extract

CLI tool to extract data from RBMware / AMS Machinery Manager `.rbm` databases
into modern formats (Parquet + JSON), without depending on the legacy Windows XP
VM or the original AMS software.

See [docs/PLAN.md](docs/PLAN.md) for the project plan and roadmap.

## Status

Phase 0 — Bootstrap. Skeleton only; subcommands print stubs.

## Quick start

```bash
uv sync
uv run rbm --help
uv run rbm-dev --help
```

## Quality gates

```bash
uv run pytest
uv run ruff check .
uv run pyright src/
```

## License

MIT — see [LICENSE](LICENSE).
