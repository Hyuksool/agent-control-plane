# Contributing

1. Create a focused branch and keep changes small.
2. Do not copy source from external coding-agent or router projects.
3. Add a failing test for every behavioral or security change.
4. Preserve the hard invariants in `docs/architecture.md` and `SECURITY.md`.
5. Run the complete verification set before requesting review:

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/ruff check src tests
.venv/bin/python -m pytest -q
.venv/bin/python -m agent_control_plane.cli demo --workspace /tmp/acp-demo
.venv/bin/python -m agent_control_plane.cli benchmark
```

Provider bridges must document their executable, environment, network, credential, filesystem, timeout, output, usage-reporting, and license boundaries. A successful bridge response is never a substitute for deterministic validation.
