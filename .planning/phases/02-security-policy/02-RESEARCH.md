# Phase 2: Security & Policy - Research

**Researched:** 2026-05-11
**Domain:** Python application security, subprocess sandboxing, policy enforcement, input validation
**Confidence:** HIGH

## Summary

Phase 2 hardens Reins against shell injection, network exposure, policy bypass, and malformed input. The codebase has a well-structured policy engine with tiered risk assessment, but the execution layer has critical security gaps: both shell adapters use `asyncio.create_subprocess_shell` (the async equivalent of `shell=True`), the API server binds to `0.0.0.0` by default, and there is no input validation layer at the API boundary (pydantic is declared as a dependency but never imported).

The good news: the architecture already separates policy evaluation from execution dispatch, and the orchestrator correctly gates all command execution through the policy engine. The fixes are surgical — replace shell dispatch with exec-style, flip the default bind address, add pydantic models for API payloads, and ensure TLS verification is explicit in HTTP clients.

**Primary recommendation:** Convert shell adapters to `create_subprocess_exec` with argument splitting, bind API to `127.0.0.1` by default with `--expose-network` flag, add pydantic request models for all API endpoints, and write a formal threat model document.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEC-01 | Shell execution adapter uses exec-style invocation, never `shell=True` | Shell adapter analysis shows `create_subprocess_shell` on lines 40, 160 of shell.py; worktree_manager.py lines 624, 644; hooks.py line 76. All must convert to exec-style. |
| SEC-02 | API server binds to localhost by default, requires explicit opt-in for network exposure | server.py line 60 defaults to `0.0.0.0`. Must change to `127.0.0.1` with explicit `--expose-network` flag. |
| SEC-03 | Policy engine enforces capability gates end-to-end with no execution-layer bypass vectors | Orchestrator correctly gates via `process_proposal()`. Need to audit that no code path calls `dispatcher.dispatch()` directly without policy check. |
| SEC-04 | Template/registry fetches validate TLS certificates | `urlopen()` in remote_registry.py and _http.py uses default SSL context (validates by default). httpx.AsyncClient also validates by default. Need explicit `verify=True` for defense-in-depth. |
| SEC-05 | Formal threat model documented | No existing threat model found in the repository. Must create from scratch. |
| SEC-06 | Input validation on all external boundaries | API routes do minimal string checks. No pydantic models despite dependency. CLI uses typer (has built-in validation). Config uses yaml.safe_load with manual type checks. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Shell command execution | Execution Layer (adapters) | — | Adapters own subprocess lifecycle; policy gates access |
| Network binding control | API Server | — | Server startup owns bind address configuration |
| Policy enforcement | Policy Engine | Orchestrator | Engine evaluates; orchestrator enforces gate before dispatch |
| TLS validation | HTTP clients (transport, _http, remote_registry) | — | Each HTTP client must validate certificates independently |
| Input validation | API routes + CLI commands | Config loader | External boundaries validate; internal layers trust validated input |
| Threat modeling | Documentation | — | Cross-cutting concern documented as architecture artifact |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.0 (already in deps) | API request/response validation | Type-safe validation with automatic error messages; already declared as project dependency |
| shlex | stdlib | Shell command argument splitting | Standard library for safe command tokenization |
| asyncio.create_subprocess_exec | stdlib | Exec-style subprocess invocation | No shell interpretation, immune to injection |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| ssl (stdlib) | stdlib | Explicit SSL context creation | When urlopen needs explicit TLS enforcement |
| certifi | >=2024.0 | CA certificate bundle | If system certs are insufficient (httpx bundles this already) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pydantic for API validation | marshmallow | pydantic already in deps, better Python 3.11+ integration |
| shlex.split for command parsing | manual list construction | shlex handles quoting correctly but callers should pass lists directly |
| Custom threat model format | STRIDE/DREAD formal framework | STRIDE provides systematic coverage; custom is faster but less rigorous |

## Architecture Patterns

### System Architecture Diagram

```
External Input (CLI args, API payloads, config files)
        │
        ▼
┌─────────────────────────────────────────────────┐
│  INPUT VALIDATION BOUNDARY                       │
│  (pydantic models, typer validators, yaml.safe) │
└─────────────────────────────────────────────────┘
        │ validated data
        ▼
┌─────────────────────────────────────────────────┐
│  ORCHESTRATOR (RunOrchestrator.process_proposal) │
│  - Materializes CommandEnvelope                  │
│  - Validates required args                       │
│  - Calls policy engine                           │
└─────────────────────────────────────────────────┘
        │ PolicyDecision
        ▼
┌─────────────────────────────────────────────────┐
│  POLICY ENGINE                                   │
│  - Risk tier lookup                              │
│  - Rule evaluation                               │
│  - Constraint checking                           │
│  - Grant matching                                │
│  - Audit recording                               │
└─────────────────────────────────────────────────┘
        │ allow/deny/ask
        ▼
┌─────────────────────────────────────────────────┐
│  EXECUTION DISPATCHER                            │
│  - Only reachable after policy "allow"           │
│  - Routes to adapter by capability               │
│  - Manages handle lifecycle                      │
└─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────┐
│  ADAPTERS (sandboxed execution)                  │
│  - Shell: exec-style, no shell interpretation    │
│  - FS: path containment checks                   │
│  - Git: exec-style subprocess                    │
│  - MCP: TLS-validated HTTP transport             │
└─────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
src/reins/
├── api/
│   ├── models.py          # NEW: pydantic request/response models
│   ├── server.py          # MODIFY: localhost default + --expose-network
│   └── ...
├── execution/
│   └── adapters/
│       └── shell.py       # MODIFY: create_subprocess_exec
├── policy/
│   └── ...               # EXISTING: already well-structured
├── config/
│   └── ...               # EXISTING: yaml.safe_load already used
└── security/
    └── threat_model.md    # NEW: formal threat model document
```

### Pattern 1: Exec-Style Subprocess Invocation
**What:** Replace `create_subprocess_shell(cmd_string)` with `create_subprocess_exec(*cmd_list)`
**When to use:** Every subprocess invocation where the command is constructed from user/agent input
**Example:**
```python
# Source: Python stdlib docs — asyncio subprocess
# BEFORE (vulnerable):
process = await asyncio.create_subprocess_shell(
    cmd,  # string like "git status --short"
    cwd=cwd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)

# AFTER (safe):
import shlex

cmd_list = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
process = await asyncio.create_subprocess_exec(
    *cmd_list,
    cwd=cwd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

### Pattern 2: Pydantic API Request Validation
**What:** Define pydantic models for all API request bodies with strict validation
**When to use:** Every API endpoint that accepts JSON input
**Example:**
```python
# Source: pydantic v2 docs
from pydantic import BaseModel, Field, field_validator

class CreateRunRequest(BaseModel):
    objective: str = Field(..., min_length=1, max_length=10000)
    issuer: str = Field(default="user", pattern=r"^(user|scheduler|webhook|remote_agent)$")
    constraints: list[str] = Field(default_factory=list, max_length=50)
    requested_capabilities: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("requested_capabilities", mode="before")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        from reins.policy.capabilities import CAPABILITY_RISK_TIERS
        invalid = [cap for cap in v if cap not in CAPABILITY_RISK_TIERS]
        if invalid:
            raise ValueError(f"Unknown capabilities: {invalid}")
        return v
```

### Pattern 3: Localhost-Default Server Binding
**What:** Bind to 127.0.0.1 by default, require explicit flag for network exposure
**When to use:** API server startup
**Example:**
```python
# server.py
parser.add_argument(
    "--host",
    default=os.getenv("REINS_HOST", "127.0.0.1"),  # Changed from 0.0.0.0
)
parser.add_argument(
    "--expose-network",
    action="store_true",
    default=False,
    help="Bind to 0.0.0.0 instead of localhost (SECURITY: exposes API to network)",
)
# In main():
host = "0.0.0.0" if args.expose_network else args.host
```

### Anti-Patterns to Avoid
- **Shell string interpolation:** Never construct shell commands by string concatenation or f-strings with user input. Always use argument lists.
- **Blanket `verify=False`:** Never disable TLS verification, even in development. Use proper CA bundles.
- **Catch-all exception handlers that swallow errors:** API routes should return structured error responses, not generic 500s that hide validation failures.
- **Direct dispatcher access:** No code should call `ExecutionDispatcher.dispatch()` without going through the orchestrator's policy gate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request body validation | Manual dict.get() with type checks | pydantic BaseModel | Handles nested validation, type coercion, error messages automatically |
| Shell argument splitting | Custom string splitting | shlex.split() | Handles quoting, escaping, edge cases correctly |
| TLS certificate validation | Custom SSL context | httpx defaults / ssl.create_default_context() | System CA bundle management is complex and error-prone |
| Threat modeling framework | Ad-hoc security notes | STRIDE methodology | Systematic coverage of Spoofing, Tampering, Repudiation, Information Disclosure, DoS, Elevation of Privilege |
| API error responses | Ad-hoc error dicts | Structured error model with code/message/details | Consistent error format enables client-side handling |

**Key insight:** Security code must be boring and standard. Custom security implementations are where vulnerabilities hide. Use well-tested stdlib and library solutions for every security boundary.

## Common Pitfalls

### Pitfall 1: shlex.split on Windows
**What goes wrong:** `shlex.split()` uses POSIX rules by default, which may not handle Windows paths correctly.
**Why it happens:** Different quoting conventions between POSIX and Windows shells.
**How to avoid:** Since Reins targets Python 3.11+ and the shell adapters are for agent sandboxing (not user shell emulation), always use `shlex.split(cmd, posix=True)`. The adapters should accept command lists directly (preferred) or strings (legacy compatibility).
**Warning signs:** Tests passing on macOS/Linux but failing on Windows with path-related errors.

### Pitfall 2: TOCTOU in Path Containment
**What goes wrong:** The filesystem adapter checks path containment with `resolve()` then operates on the path, but a symlink could be created between check and use.
**Why it happens:** Time-of-check-to-time-of-use race condition.
**How to avoid:** The existing `_is_contained` check in `fs.py` is adequate for the threat model (agent sandboxing, not adversarial multi-user). Document this as an accepted risk in the threat model.
**Warning signs:** Symlinks appearing in workspace directories.

### Pitfall 3: Policy Bypass via Direct Dispatcher Access
**What goes wrong:** If any code path calls `dispatcher.dispatch()` without going through `RunOrchestrator.process_proposal()`, the policy engine is bypassed.
**Why it happens:** Developer convenience — "I know this is safe, I'll skip the policy check."
**How to avoid:** Make `ExecutionDispatcher` private to the orchestrator module, or add a runtime assertion that dispatch is only called from the orchestrator. Add a test that greps for direct dispatcher usage outside the orchestrator.
**Warning signs:** New code importing `ExecutionDispatcher` directly.

### Pitfall 4: urlopen Without Explicit SSL Context
**What goes wrong:** `urlopen()` uses the default SSL context which validates certificates, but this behavior is not explicit and could be accidentally overridden.
**Why it happens:** Python's `urlopen` validates by default since Python 3.4, but the code doesn't make this explicit.
**How to avoid:** Pass `context=ssl.create_default_context()` explicitly to `urlopen()` calls. This makes the security property visible and grep-able.
**Warning signs:** Any `urlopen` call without a `context` parameter.

### Pitfall 5: Hook Executor Shell Injection
**What goes wrong:** `config/hooks.py` uses `subprocess.run(command, shell=True)` where `command` comes from `.reins/config.yaml`. If a malicious config is loaded, arbitrary commands execute.
**Why it happens:** Hooks are designed to run arbitrary user-configured commands.
**How to avoid:** This is an accepted design choice (hooks ARE user-configured shell commands), but document it in the threat model. The mitigation is that config files are local and trusted. Add a warning in docs that hook commands should not interpolate untrusted data.
**Warning signs:** Hook commands that include variable interpolation from external sources.

## Code Examples

### Safe Shell Adapter (exec-style)
```python
# Replacement for SandboxedShellAdapter.exec()
async def exec(self, handle: Handle, command: dict) -> Observation:
    session = self._sessions[handle.handle_id]
    cmd = command["cmd"]
    cwd = command.get("cwd", session["cwd"])
    env = self._build_sandboxed_env(session["env"], command.get("env", {}))

    # Accept both string and list forms
    if isinstance(cmd, str):
        import shlex
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = list(cmd)

    process = await asyncio.create_subprocess_exec(
        *cmd_list,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    session["cwd"] = str(Path(cwd).resolve())
    session["history"].append({"cmd": cmd, "exit_code": process.returncode})
    return Observation(
        stdout=stdout.decode(),
        stderr=stderr.decode(),
        exit_code=int(process.returncode or 0),
        effect_descriptor={"cmd": cmd, "cwd": session["cwd"], "sandboxed": True},
    )
```

### Pydantic API Models
```python
# src/reins/api/models.py
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CreateRunRequest(BaseModel):
    """POST /runs request body."""
    objective: str = Field(..., min_length=1, max_length=10000)
    issuer: str = Field(default="user")
    constraints: list[str] = Field(default_factory=list, max_length=50)
    requested_capabilities: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("issuer")
    @classmethod
    def validate_issuer(cls, v: str) -> str:
        allowed = {"user", "scheduler", "webhook", "remote_agent"}
        if v not in allowed:
            raise ValueError(f"issuer must be one of {allowed}")
        return v


class SubmitCommandRequest(BaseModel):
    """POST /runs/{id}/commands request body."""
    kind: str = Field(..., min_length=1, max_length=200)
    args: dict = Field(default_factory=dict)
    source: str = Field(default="model")
    rationale_ref: str | None = None
    idempotency_key: str | None = None
    evaluate: bool = False

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        allowed = {"model", "human", "hook", "skill"}
        if v not in allowed:
            raise ValueError(f"source must be one of {allowed}")
        return v


class ApprovalRequest(BaseModel):
    """POST /runs/{id}/approve request body."""
    request_id: str = Field(..., min_length=1)
    granted_by: str = Field(default="human", min_length=1, max_length=200)


class RejectionRequest(BaseModel):
    """POST /runs/{id}/reject request body."""
    request_id: str = Field(..., min_length=1)
    reason: str = Field(default="rejected by human", max_length=2000)
    rejected_by: str = Field(default="human", min_length=1, max_length=200)


class ErrorResponse(BaseModel):
    """Structured error response."""
    error: str
    code: str | None = None
    details: dict | None = None
```

### Explicit TLS Validation
```python
# For urlopen calls in remote_registry.py and _http.py
import ssl

def _create_tls_context() -> ssl.SSLContext:
    """Create a strict TLS context that validates certificates."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx

# Usage:
with urlopen(url, context=_create_tls_context()) as response:
    payload = response.read()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| subprocess.run(shell=True) | subprocess.run with list args | Always best practice | Eliminates shell injection entirely |
| Manual dict validation | pydantic v2 BaseModel | pydantic 2.0 (2023) | Type-safe, auto-documented, fast validation |
| Bind 0.0.0.0 for dev convenience | Localhost-first, explicit network opt-in | Security-by-default trend | Prevents accidental network exposure |
| Ad-hoc security notes | STRIDE threat modeling | Industry standard | Systematic coverage, auditable |

**Deprecated/outdated:**
- `yaml.load()` without Loader: Always use `yaml.safe_load()` — already correct in this codebase
- `subprocess.Popen(shell=True)`: Use exec-style with argument lists
- Implicit TLS (relying on defaults): Make TLS verification explicit and visible

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Hook executor shell=True is acceptable because hooks are user-configured local commands | Common Pitfalls | If hooks can be injected remotely, this becomes a vulnerability |
| A2 | TOCTOU in fs adapter path containment is acceptable risk for agent sandboxing | Common Pitfalls | If adversarial actors can create symlinks during execution, path escape is possible |
| A3 | pydantic v2 is the right choice for API validation (it's already in deps) | Standard Stack | If project intentionally avoided pydantic for a reason, this adds unwanted coupling |

## Open Questions

1. **Hook executor design decision**
   - What we know: `config/hooks.py` uses `shell=True` by design for user-configured hooks
   - What's unclear: Should SEC-01 apply to hooks, or are they explicitly exempt as user-configured commands?
   - Recommendation: Document as accepted risk in threat model. Hooks are analogous to git hooks — they run user-specified commands intentionally.

2. **Worktree manager shell commands**
   - What we know: `worktree_manager.py` uses `create_subprocess_shell` for post-create and verify commands
   - What's unclear: These commands come from worktree config (user-specified). Same exemption as hooks?
   - Recommendation: Same treatment as hooks — document as accepted risk. The commands are from local config files.

3. **httpx dependency for MCP transport**
   - What we know: httpx is not in the declared dependencies in pyproject.toml but is imported in transport.py
   - What's unclear: Is httpx installed transitively or is this a missing dependency?
   - Recommendation: Add httpx to dependencies explicitly, with `verify=True` made explicit in client creation.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All code | Yes | 3.13.3 | — |
| pytest | Test validation | Yes | Available via anaconda | — |
| pydantic | API validation (SEC-06) | Declared in deps | >=2.0 | — |
| shlex (stdlib) | Shell arg splitting (SEC-01) | Yes | stdlib | — |
| ssl (stdlib) | TLS context (SEC-04) | Yes | stdlib | — |

**Missing dependencies with no fallback:** None

**Missing dependencies with fallback:** None

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 8.0 + pytest-asyncio >= 0.23 |
| Config file | pyproject.toml (no pytest.ini) |
| Quick run command | `python -m pytest tests/unit/ -x -q` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 | Shell adapters use exec-style, no shell=True | unit | `python -m pytest tests/unit/test_shell_security.py -x` | No — Wave 0 |
| SEC-02 | API binds localhost by default, network requires flag | unit + integration | `python -m pytest tests/unit/test_server_binding.py -x` | No — Wave 0 |
| SEC-03 | No policy bypass vectors in execution paths | integration | `python -m pytest tests/integration/test_policy_enforcement.py -x` | Partial (test_policy_engine.py exists) |
| SEC-04 | TLS certificates validated on all HTTP fetches | unit | `python -m pytest tests/unit/test_tls_validation.py -x` | No — Wave 0 |
| SEC-05 | Threat model document exists and covers required topics | smoke | `test -f docs/security/threat-model.md` | No — Wave 0 |
| SEC-06 | Malformed input produces structured errors | unit + integration | `python -m pytest tests/unit/test_input_validation.py -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/unit/ -x -q --timeout=30`
- **Per wave merge:** `python -m pytest tests/ -x --timeout=60`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_shell_security.py` — covers SEC-01 (exec-style enforcement)
- [ ] `tests/unit/test_server_binding.py` — covers SEC-02 (localhost default)
- [ ] `tests/integration/test_policy_enforcement.py` — covers SEC-03 (extend existing)
- [ ] `tests/unit/test_tls_validation.py` — covers SEC-04
- [ ] `tests/unit/test_input_validation.py` — covers SEC-06 (pydantic model validation)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A (local tool, no user auth in v1) |
| V3 Session Management | No | N/A (stateless API, run-based sessions) |
| V4 Access Control | Yes | Policy engine with capability-based access control |
| V5 Input Validation | Yes | pydantic models at API boundary, typer at CLI, yaml.safe_load for config |
| V6 Cryptography | No | No custom crypto (TLS handled by stdlib/httpx) |
| V7 Error Handling | Yes | Structured error responses, no stack traces to clients |
| V13 API Security | Yes | Localhost-default binding, input validation, rate limiting (future) |
| V14 Configuration | Yes | Safe defaults, explicit opt-in for dangerous settings |

### Known Threat Patterns for Python Agent Kernel

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Shell injection via subprocess | Tampering | `create_subprocess_exec` with argument lists |
| Network exposure of local API | Information Disclosure | Bind 127.0.0.1 by default |
| Policy bypass via direct dispatch | Elevation of Privilege | Architectural enforcement — dispatcher only reachable through orchestrator |
| YAML deserialization attacks | Tampering | `yaml.safe_load()` (already used) |
| Path traversal in filesystem adapter | Tampering | `resolve()` + containment check (already implemented) |
| TLS downgrade / MITM on registry fetches | Spoofing | Explicit SSL context with cert validation |
| Malformed API payloads causing crashes | Denial of Service | pydantic validation with structured error responses |
| Agent exfiltration via network shell | Information Disclosure | Sandboxed adapter strips network env vars; policy gates network access at T2 |

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `src/reins/execution/adapters/shell.py` — confirmed `create_subprocess_shell` usage on lines 40, 160
- Codebase analysis: `src/reins/api/server.py` — confirmed `0.0.0.0` default on line 60
- Codebase analysis: `src/reins/kernel/orchestrator.py` — confirmed policy gate in `process_proposal()`
- Codebase analysis: `src/reins/platform/remote_registry.py` — confirmed `urlopen` without explicit SSL context
- Codebase analysis: `src/reins/config/hooks.py` — confirmed `shell=True` on line 76
- Python stdlib docs: `asyncio.create_subprocess_exec` vs `create_subprocess_shell` [VERIFIED: codebase grep]

### Secondary (MEDIUM confidence)
- Python security best practices for subprocess handling [ASSUMED — based on well-established Python security guidance]
- pydantic v2 validation patterns [ASSUMED — based on training knowledge of pydantic v2 API]

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all recommendations use stdlib or already-declared dependencies
- Architecture: HIGH — based on direct codebase analysis of all relevant files
- Pitfalls: HIGH — identified from actual code patterns, not hypothetical scenarios

**Research date:** 2026-05-11
**Valid until:** 2026-06-11 (stable domain — Python security patterns don't change rapidly)
