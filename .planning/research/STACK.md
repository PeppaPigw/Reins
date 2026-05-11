# Technology Stack

**Project:** Reins - Event-Sourced Agent Control Kernel
**Researched:** 2026-05-11
**Overall Confidence:** HIGH

## Recommended Stack

### Package Management & Build

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| uv | >=0.6 | Package manager, venv, lockfile, build, publish | De-facto standard in 2026. 10-100x faster than pip. Single binary replaces pip, pip-tools, virtualenv, twine. Handles `uv build` and `uv publish` natively. | HIGH |
| hatchling | >=1.25 | Build backend | Keep hatchling as build backend. uv's own build backend (`uv-build`) is now stable but only supports pure Python and has fewer features. Hatchling is the PyPA-blessed default that uv itself uses. Mature, standards-compliant, supports dynamic versioning. | HIGH |

**Migration from current state:** Add `uv.lock` via `uv lock`. Replace all `pip install` workflows with `uv sync`. Keep `hatchling` as build-backend (no change needed in pyproject.toml build-system).

### Core Runtime

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Python | >=3.12 | Runtime | 3.12 brings TaskGroup improvements, better error messages, and `asyncio.Runner`. 3.11 minimum is too conservative for a 2026 framework targeting production teams. 3.12 is the sweet spot (widely deployed, LTS-adjacent). | HIGH |
| asyncio (stdlib) | - | Async runtime | Native, zero-dependency, well-understood. No need for trio/anyio when the entire codebase is already asyncio-native. TaskGroups (3.11+) provide structured concurrency. | HIGH |
| pydantic | >=2.11 | Data validation, serialization | Rust-powered core (17x faster than v1). v2.11+ adds major performance improvements. Already deeply integrated in Reins kernel. Pin to >=2.11 for latest optimizations. | HIGH |

### CLI Framework

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| typer | >=0.12 | CLI application framework | Already in use. Built on Click, type-hint driven, excellent DX. No reason to switch. Pin to >=0.12 for latest features. | HIGH |
| rich | >=13.9 | Terminal output, progress bars, tables | Already in use. Best-in-class terminal rendering. Replaces `tabulate` for table output. | HIGH |

**Drop:** `tabulate` - Rich handles tables natively with better formatting. One less dependency.

### HTTP & Networking

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| aiohttp | >=3.10 | HTTP API server | Keep for the server side. Mature, battle-tested async server with WebSocket support. Reins API server is already built on it. | HIGH |
| httpx | >=0.28 | HTTP client (MCP transport) | Already used for MCP transport. Modern async client with HTTP/2, connection pooling, and requests-compatible API. Better client ergonomics than aiohttp client. | HIGH |

**Rationale for keeping both:** aiohttp excels as a server (WebSocket support, mature middleware). httpx excels as a client (cleaner API, HTTP/2, sync+async). This split is the 2026 consensus pattern.

### Async I/O & Event Sourcing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| aiofiles | >=24.1 | Async file I/O | Required for non-blocking journal writes. Lightweight, focused. | HIGH |
| structlog | >=25.1 | Structured logging | Latest is 25.5.0. Already integrated. Best structured logging library for Python. Pairs with OpenTelemetry for observability. | HIGH |
| ulid-py | >=2.0 | Unique sortable IDs | Time-ordered, globally unique. Perfect for event sourcing (natural ordering). | MEDIUM |

### Observability & Profiling

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| structlog | >=25.1 | Structured logging (already listed) | Core observability layer | HIGH |
| opentelemetry-api | >=1.27 | Tracing standard | Optional extra. Industry standard for distributed tracing. Pairs with structlog for comprehensive observability. | MEDIUM |
| pyinstrument | >=5.0 | Performance profiling | Statistical profiler with async-aware call stacks. Low overhead, beautiful output. Use for development profiling. | HIGH |
| yappi | >=1.6 | Deterministic async profiling | C-extension profiler with native asyncio/coroutine awareness. Use for precise per-coroutine timing in benchmarks. | MEDIUM |

### Testing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| pytest | >=8.3 | Test runner | Industry standard. Extensible, excellent plugin ecosystem. | HIGH |
| pytest-asyncio | >=0.26 | Async test support | Latest stable is 0.26.x (v1.3.0 also released as stable). Use `asyncio_mode = "auto"` to avoid marker boilerplate. | HIGH |
| hypothesis | >=6.115 | Property-based testing | Latest is ~6.150+. Essential for testing event sourcing invariants (commutativity, idempotency, reducer correctness). Generates edge cases humans miss. | HIGH |
| pytest-cov | >=6.0 | Coverage measurement | Latest released Mar 2026. Integrates coverage.py with pytest. Target >90% coverage. | HIGH |
| pytest-xdist | >=3.5 | Parallel test execution | Run tests across CPU cores. Critical for large test suites. | HIGH |
| respx | >=0.22 | HTTP mocking for httpx | Mock httpx requests in tests without hitting network. | MEDIUM |
| aioresponses | >=0.7 | HTTP mocking for aiohttp | Mock aiohttp client requests. | MEDIUM |

### Code Quality

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| ruff | >=0.8 | Linting + formatting | Latest is 0.15.x. Replaces black, isort, flake8, pyupgrade in one tool. 10-100x faster. Already in use. Astral ecosystem alignment with uv. | HIGH |
| mypy | >=1.13 | Static type checking | Production-ready, comprehensive. Keep as primary type checker. | HIGH |
| ty | (watch) | Future type checker | Astral's Rust-based type checker. Now in beta (May 2026), targeting 1.0 in 2026. 10-20x faster than mypy. Adopt when stable, but not yet for production CI. | LOW |

**Type checker strategy:** Use mypy now. Monitor ty for 1.0 stable release. Plan migration path when ty reaches production readiness (likely late 2026).

### Documentation

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| mkdocs-material | >=9.6 | Documentation site | De-facto standard for Python project docs. Beautiful output, search, dark mode, code annotations. Used by FastAPI, Pydantic, uv, httpx. MkDocs 2.0 announced Feb 2026. | HIGH |
| mkdocstrings[python] | >=0.27 | API docs from docstrings | Auto-generates API reference from Python docstrings. Integrates with mkdocs-material. | HIGH |
| mike | >=2.1 | Doc versioning | Multi-version documentation deployment. Essential for a framework with versioned API. | MEDIUM |

### CI/CD & Release

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| GitHub Actions | - | CI/CD platform | Standard for open-source Python. Free for public repos. | HIGH |
| PyPI Trusted Publishers | - | Tokenless publishing | OIDC-based publishing. No API tokens to manage. Secure by default. The 2026 standard for PyPI publishing. | HIGH |
| pypa/gh-action-pypi-publish | >=1.12 | PyPI upload action | Official PyPA action. Works with Trusted Publishers. | HIGH |
| python-semantic-release | >=9.0 | Automated versioning | Conventional commits to semver. Auto-generates changelogs. | MEDIUM |

### Configuration & Serialization

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| PyYAML | >=6.0.2 | YAML parsing | Already in use. Stable, universal. | HIGH |
| tomli | (stdlib) | TOML parsing | Built into Python 3.11+ as `tomllib`. Use for reading pyproject.toml and config. No extra dependency needed. | HIGH |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Package manager | uv | poetry | Poetry is slower, heavier, and losing mindshare to uv in 2026. uv handles everything poetry does, faster. |
| Package manager | uv | pip + pip-tools | Legacy approach. No lockfile by default, no venv management, no build/publish. |
| Build backend | hatchling | uv-build | uv-build is stable but limited to pure Python, fewer configuration options. Hatchling is more mature. |
| Build backend | hatchling | setuptools | Legacy. More boilerplate, less standards-compliant by default. |
| Async runtime | asyncio | trio | Trio has better structured concurrency design but smaller ecosystem. Reins is already asyncio-native. Migration cost too high for marginal benefit. |
| Async runtime | asyncio | anyio | Abstraction layer over asyncio/trio. Adds indirection without benefit when you're committed to asyncio. |
| HTTP server | aiohttp | FastAPI/Uvicorn | FastAPI is REST-focused. Reins API is a control plane, not a REST API. aiohttp gives more control over WebSocket and streaming. |
| HTTP server | aiohttp | Starlette | Same reasoning as FastAPI. Reins doesn't need ASGI middleware ecosystem. |
| CLI | typer | click | Typer wraps Click with type hints. More ergonomic, same power. Already in use. |
| Type checker | mypy | pyright | Pyright is faster but has Microsoft-specific behaviors. mypy is the community standard. |
| Type checker | mypy | ty | Beta. Not production-ready for CI enforcement yet. Watch for 1.0. |
| Docs | mkdocs-material | sphinx | Sphinx is powerful but complex. mkdocs-material has better DX, faster builds, and is the modern Python standard. |
| Logging | structlog | loguru | Loguru is simpler but less structured. structlog's processor pipeline is ideal for event-sourced systems needing structured audit trails. |
| Profiler | pyinstrument | cProfile | cProfile is stdlib but produces hard-to-read output and doesn't understand async well. |

## What NOT to Use

| Technology | Why Avoid |
|------------|-----------|
| poetry | Losing to uv. Slower resolver, heavier install, proprietary lock format. |
| setuptools (as primary) | Legacy. Requires setup.py/setup.cfg boilerplate. |
| black + isort + flake8 | Three tools where ruff does all three, 100x faster. |
| tox | Replaced by uv's environment management + nox for complex matrices. |
| sphinx | Over-engineered for this use case. RST syntax is hostile to contributors. |
| trio/anyio | Migration cost from asyncio is prohibitive. No ecosystem benefit for this project. |
| loguru | Insufficient structure for event-sourced audit trails. |
| celery | Overkill. Reins has its own task/execution system. |
| SQLAlchemy/databases | Reins uses file-based event journals. No RDBMS needed. |

## Dependency Groups (pyproject.toml structure)

```toml
[project]
name = "reins"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.11",
    "aiofiles>=24.1",
    "aiohttp>=3.10",
    "structlog>=25.1",
    "ulid-py>=2.0",
    "PyYAML>=6.0.2",
    "typer>=0.12",
    "rich>=13.9",
    "httpx>=0.28",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.26",
    "pytest-cov>=6.0",
    "pytest-xdist>=3.5",
    "hypothesis>=6.115",
    "respx>=0.22",
    "aioresponses>=0.7",
    "ruff>=0.8",
    "mypy>=1.13",
    "pyinstrument>=5.0",
]
docs = [
    "mkdocs-material>=9.6",
    "mkdocstrings[python]>=0.27",
    "mike>=2.1",
]
observability = [
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

## Installation

```bash
# Development setup (recommended)
uv sync --all-extras

# Production install
uv pip install reins

# Or from PyPI
pip install reins

# With observability extras
pip install reins[observability]

# Docs development
uv sync --extra docs
```

## Version Pinning Strategy

- **Runtime deps:** Use `>=` minimum with tested floor. Let uv.lock pin exact versions.
- **Dev deps:** Same strategy. Lock file ensures reproducibility.
- **CI:** Always use `uv.lock` for deterministic builds.
- **Users:** Get latest compatible versions via standard pip resolution.

## Sources

- [uv documentation](https://docs.astral.sh/uv/)
- [uv build backend](https://docs.astral.sh/uv/concepts/build-backend/)
- [Python Dependency Management in 2026](https://cuttlesoft.com/blog/2026/01/27/python-dependency-management-in-2026/)
- [The State of Python Packaging in 2026](https://learn.repoforge.io/posts/the-state-of-python-packaging-in-2026/)
- [Pydantic v2.13 Release](https://pydantic.dev/articles/pydantic-v2-13-release)
- [pytest-asyncio releases](https://github.com/pytest-dev/pytest-asyncio/releases)
- [Hypothesis documentation](https://hypothesis.readthedocs.io/en/latest/)
- [ty announcement (Astral)](https://astral.sh/blog/ty)
- [ty now in beta (InfoWorld)](https://www.infoworld.com/article/4108979/python-type-checker-ty-now-in-beta.html)
- [Ruff 0.15 + 2026 Style Guide](https://www.pyblog.in/programming/ruff-0-15-2026-style-guide-modern-python-formatting-explained/)
- [MkDocs 2.0 announcement](https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish)
- [structlog 25.5.0 on PyPI](https://www.pypi.org/project/structlog/25.5.0/)
- [pytest-cov on PyPI](https://pypi.org/project/pytest-cov/)
- [pyinstrument on GitHub](https://github.com/joerick/pyinstrument)
- [yappi coroutine profiling](https://github.com/sumerc/yappi/blob/master/doc/coroutine-profiling.md)
