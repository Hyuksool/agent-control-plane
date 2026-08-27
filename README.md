# Coding Agent Control Plane

A clean-room, policy-driven control plane for coding agents and LLM providers.

It decomposes work into typed steps, routes each step to an eligible model, lets a pre-approved local agent bridge operate in an explicit workspace, runs deterministic validation, escalates after failure, and records the cost of every attempt—including failed attempts—without persisting prompt or source bodies.

## Verified status

The repository currently proves the control-plane behavior offline:

- deterministic cheap-model failure → stronger-model escalation;
- structured `argv` validation with no shell;
- preflight and actual-usage budget stops;
- retry and wall-time caps;
- protected-validator/test integrity checks after every agent attempt;
- aggregate team outcome learning;
- allowlisted JSONL telemetry containing hashes and metrics only;
- a stdin/stdout JSON bridge for external coding agents;
- a deterministic baseline benchmark.

It does **not** yet establish real-provider quality, savings, customer adoption, or production-grade OS sandboxing. The included benchmark is explicitly offline and deterministic.

## Why this repository exists

Existing projects already solve major parts of the problem:

- [LiteLLM](https://github.com/BerriAI/litellm) and [Claude Code Router](https://github.com/musistudio/claude-code-router): provider routing, fallback, and usage visibility;
- [RouteLLM](https://github.com/lm-sys/RouteLLM): quality/cost routing;
- [Aider](https://github.com/Aider-AI/aider): architect/editor workflows and code validation;
- [OpenHands](https://github.com/OpenHands/OpenHands) and [SWE-agent](https://github.com/SWE-agent/SWE-agent): repository-level agent execution.

This repository does not copy their code. Its designed contribution is a vendor-neutral governance layer across those categories:

1. fail-closed organization policy before execution;
2. validation-result-driven model escalation;
3. total cost accounting that includes failures and retries;
4. hard cost, attempt, output, timeout, and wall-time limits;
5. team-specific routing input based on aggregate outcomes only;
6. privacy-safe traces that exclude prompt, source, raw output, credentials, and raw team identifiers.

See [`THIRD_PARTY.md`](THIRD_PARTY.md) for the clean-room boundary.

## Architecture

```text
task from stdin/file
        │
        ▼
typed decomposer ──► policy router ──► pre-approved provider bridge
                           │                       │
                           │                       ▼
                           │                 workspace edit
                           │                       │
                           ▼                       ▼
                    budget/risk gate ◄── build · test · lint validator
                           │                       │
                           └──── failure → stronger eligible model

all attempts → cost ledger → aggregate outcomes + body-free JSONL traces
```

The bridge receives request JSON through `stdin` and returns result JSON through `stdout`. It is never invoked through a shell. A bridge can wrap Aider, OpenHands, another coding agent, or an internal provider service, but that wrapper must be reviewed separately.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# Proves validation failure, escalation, and failed-attempt cost accounting.
.venv/bin/python -m agent_control_plane.cli demo \
  --workspace /tmp/agent-control-plane-demo

# Compares policy routing with an always-strong baseline on identical offline cases.
.venv/bin/python -m agent_control_plane.cli benchmark

# Protocol smoke using the included no-LLM bridge. Task body comes from stdin.
printf '%s\n' 'Inspect this repository and report the planned change.' | \
  .venv/bin/python -m agent_control_plane.cli run \
  --config examples/config.toml \
  --workspace . \
  --team-id local-example
```

The example bridge proves the protocol only; it does not call an LLM or edit source code.

## Configuration

`examples/config.toml` defines:

- model capabilities, risk ceiling, quality prior, latency, and token prices;
- the reviewed bridge command and executable allowlist;
- validation commands as structured argv;
- protected validator/test paths and allowed Python modules;
- run budgets and retry/wall-time caps;
- execution timeout and output limits.

Credentials are not fields in this configuration. Provider credentials, if needed, belong in the reviewed bridge's secret mechanism. The control plane passes only a small allowlist of environment variables.

## Security boundary

`SafeExecutor` is a policy-enforced subprocess runner, **not** a container, VM, or kernel sandbox. For untrusted coding agents, place the bridge inside a container, microVM, or another independently reviewed isolation boundary and mount only the intended workspace.

Default controls reject:

- unknown executables;
- shell syntax and inline Python;
- unapproved `python -m` modules;
- network targets;
- workspace path escape;
- mutating Git subcommands;
- unknown environment keys;
- excessive timeout or output.

On POSIX systems, timeout or output-limit enforcement terminates the spawned process group,
not only the parent process. Configured `protected_paths` are hashed before the run and checked
after every adapter attempt, including failed attempts; modification stops the run without retry.

See [`docs/threat-model.md`](docs/threat-model.md).

## Verification

```bash
.venv/bin/python -m compileall -q src tests examples
.venv/bin/ruff check src tests examples
.venv/bin/mypy src
.venv/bin/bandit -r src -ll
.venv/bin/python -m pytest -q
.venv/bin/python -m agent_control_plane.cli demo --workspace /tmp/acp-demo
.venv/bin/python -m agent_control_plane.cli benchmark
```

## Repository layout

```text
src/agent_control_plane/
  adapters/          # deterministic and reviewed local stdio bridges
  config.py          # strict TOML loading
  decomposition.py   # typed plan/edit/review steps
  router.py          # capability/risk/policy/cost/history routing
  policy.py          # fail-closed command and path rules
  executor.py        # no-shell bounded subprocess execution
  validation.py      # build/test/lint exit-code gate
  orchestrator.py    # bounded retry and escalation loop
  cost.py            # all-attempt cost ledger
  learning.py        # hashed aggregate team outcomes
  trace.py           # allowlisted body-free JSONL events
  benchmark.py       # deterministic comparative evidence
  cli.py             # demo, benchmark, and configured run commands
```

## License

MIT. This license covers only code in this repository; external agents and providers retain their own licenses and terms.
