# Security Policy

## Supported status

This repository is pre-production. The offline control-flow and security tests are maintained; no bundled vendor bridge is designated production-safe.

## Reporting

Do not open a public issue containing credentials, private source code, customer task bodies, or exploit details. Use GitHub private vulnerability reporting after the repository remote is created, or contact the repository owner through an already established private channel.

Include:

- affected commit and module;
- minimal reproduction without real secrets or customer code;
- expected versus observed policy decision;
- whether workspace escape, credential exposure, remote execution, cost runaway, or trace leakage is possible.

## Security invariants

A change must not weaken these without an explicit reviewed design change:

- no `shell=True`, `os.system`, `eval`, or `exec`;
- structured argv and workspace boundary checks;
- fail-closed executable and environment allowlists;
- bounded attempts, cost, output, process timeout, and run wall time;
- failed attempts included in total cost;
- no prompt, source, raw process output, credential, or raw team ID in trace/outcome storage;
- offline tests do not require provider credentials or network access.
