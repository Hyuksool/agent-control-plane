# Threat Model

## Assets

- customer source code and task instructions;
- provider credentials held by an external bridge;
- workspace integrity;
- cost budget;
- organization model/command policy;
- routing outcome history and audit traces.

## Trust boundaries

| Boundary | Trusted | Untrusted or conditionally trusted |
|---|---|---|
| Configuration | reviewed local TOML | downloaded or model-generated config |
| Adapter | approved executable and wrapper | model/provider response |
| Workspace | explicitly selected root | paths proposed by a model |
| Validation | fixed structured argv | model claims of success |
| Telemetry | allowlisted hashes/metrics | prompt, source, raw output, credentials |

## Priority threats and controls

### 1. Shell or command injection

Controls: no shell, structured argv, executable and Python-module allowlists, shell-marker rejection, inline-Python denial, mutating-Git denial, explicit timeout, bounded combined output, and POSIX process-group termination.

Residual risk: an allowlisted executable may itself expose dangerous options. Review executable-specific policy or isolate it externally.

### 2. Workspace escape

Controls: canonical root/cwd checks and path-token resolution before execution; deterministic adapter rejects `..` writes.

Residual risk: symlink races and bridge-internal filesystem access require a container/microVM or OS sandbox.

### 3. Secret exfiltration

Controls: config has no credential fields; bridge environment is allowlisted; traces/outcomes exclude bodies; network tools are not validator executables.

Residual risk: a bridge can access its own environment or network. Give each bridge least-privilege credentials and independent egress controls.

### 4. Cost runaway and retry loops

Controls: estimated-cost preflight, actual token-cost check, per-step attempts, run wall time, adapter timeout, validator timeout, output cap, exclusion after failure, stronger-model floor.

Residual risk: inaccurate provider usage data. Production bridges should reconcile usage against provider invoices.

### 5. False success

Controls: configured validation exit code is authoritative; protected validator/test paths are
hashed before the run and checked after every adapter attempt, including failed attempts; integrity
change causes policy denial without retry; ordinary validation failure triggers exclusion/escalation.

Residual risk: weak or irrelevant tests. Benchmark tasks must contain hidden acceptance tests where appropriate.

### 6. Policy bypass by configuration

Controls: config validation and fail-closed defaults.

Residual risk: the configuration itself is a privileged artifact. Require code review, signed commits, and protected branches for production policy changes.

### 7. Telemetry leakage

Controls: strict trace field allowlist, 256-character string cap, mode-0600 files, HMAC request/team identifiers, aggregate-only SQLite schema, response and command-output hashes.

Residual risk: compromise of the per-installation HMAC key permits offline checking of predictable identifiers. Keep the key mode-0600 outside shared artifacts and define rotation/retention policy before production use.

### 8. Poisoned team learning

Controls: learning affects score only after capability/risk/policy gates; quality floors remain authoritative; data is aggregate and model-scoped.

Residual risk: repeated adversarial outcomes can bias routing. Add minimum sample sizes, decay, anomaly review, and signed outcome provenance before production online adaptation.

## Mandatory production additions

- container/microVM isolation and read-only mounts outside the target workspace;
- per-bridge egress policy;
- provider usage reconciliation;
- signed configuration and protected review path;
- retention/deletion policy for traces and aggregate outcomes;
- adversarial prompt, symlink, race, and dependency-confusion tests;
- incident response and credential rotation procedures.
