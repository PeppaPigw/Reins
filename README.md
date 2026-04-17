# Reins

> Basic rules with enough freedom. Running where the reins lead.

**Reins** is an event-sourced agent control kernel that provides safe, auditable execution boundaries for AI agents. It combines policy enforcement, capability-based security, and workflow orchestration to enable reliable multi-agent systems.

## Features

### Core Architecture

- **Event Sourcing**: Complete audit trail of all agent actions through immutable event journal
- **CQRS Pattern**: Separation of command submission and state queries for consistency
- **Policy Engine**: Capability-based access control with risk classification (T0-T3)
- **Approval System**: Human-in-the-loop approval for high-risk operations
- **Execution Boundaries**: Sandboxed adapters for filesystem, shell, git, and MCP operations

### Skill System

- **SKILL.md Discovery**: Automatic discovery and parsing of skill manifests
- **Trust Tiers**: Three-tier trust model (TRUSTED/REVIEWED/UNTRUSTED)
- **Capability Encapsulation**: Fine-grained permission system for skill execution
- **Semantic Resolution**: Relevance-based skill matching with cost estimation

### Workflow Engine

- **DAG-based Graphs**: Directed acyclic graph representation of multi-node workflows
- **State Machine**: Node lifecycle management (PENDING/RUNNING/COMPLETED/FAILED/BLOCKED)
- **Decision Points**: Interactive decision-making and user question handling
- **Dependency Tracking**: Automatic dependency resolution and execution ordering

### Multi-Agent Orchestration

- **Subagent Manager**: Spawn and coordinate multiple agent instances
- **Context Compilation**: Intelligent context assembly with token budget management
- **Timeline Tracking**: Reconstruct execution history for debugging and handoff
- **Grant Inheritance**: Secure permission delegation to subagents

### MCP Integration

- **JSON-RPC Transport**: Standard MCP protocol implementation
- **Server Lifecycle**: Connection management and capability negotiation
- **Tool/Resource/Prompt**: Full MCP primitive support
- **Audit Trail**: All MCP invocations recorded in event journal

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/reins.git
cd reins

# Install dependencies
pip install -e ".[dev]"
```

## Quick Start

### Basic Usage

```python
from reins.api.registry import RunRegistry
from reins.kernel.orchestrator import Orchestrator

# Initialize registry
registry = RunRegistry(journal_path="./journal")

# Submit a command
run_id = await registry.submit_command(
    capability="fs:read",
    args={"path": "/path/to/file.txt"},
    requested_by="user"
)

# Get execution state
state = await registry.get_state(run_id)
print(state.status)  # "completed", "pending_approval", "failed"
```

### Policy Configuration

```python
from reins.policy.engine import PolicyEngine
from reins.policy.capabilities import CapabilityClassifier

# Initialize policy engine
classifier = CapabilityClassifier()
policy = PolicyEngine(classifier)

# Check if capability requires approval
effect = policy.classify("shell:exec", {"command": "rm -rf /"})
print(effect.risk_tier)  # T3 (high risk)
print(effect.requires_approval)  # True
```

### Skill System

```python
from reins.skill.discovery import SkillDiscovery
from reins.skill.resolver import SkillResolver
from reins.skill.catalog import SkillRegistry

# Discover skills
discovery = SkillDiscovery(search_paths=[Path("./skills")])
manifests = discovery.discover_all()

# Resolve skills by query
registry = SkillRegistry(Path("./skills.jsonl"))
resolver = SkillResolver(registry, enforce_trust_model=True)
results = await resolver.resolve("file operations", top_k=5)

for skill in results:
    print(f"{skill.skill_id}: {skill.relevance:.2f} (trust: {skill.trust_classification})")
```

### Workflow Execution

```python
from reins.workflow.graph import TaskGraphBuilder, NodeType
from reins.workflow.state import NodeStateTracker

# Build workflow graph
builder = TaskGraphBuilder()
builder.create_graph("data-pipeline")
builder.add_node("data-pipeline", "fetch", NodeType.TASK, "Fetch Data")
builder.add_node("data-pipeline", "process", NodeType.TASK, "Process Data")
builder.add_node("data-pipeline", "store", NodeType.TASK, "Store Results")
builder.add_edge("data-pipeline", "fetch", "process")
builder.add_edge("data-pipeline", "process", "store")

# Track execution state
tracker = NodeStateTracker()
tracker.initialize_node("fetch")
tracker.start_node("fetch")
# ... execute node ...
tracker.complete_node("fetch", {"records": 1000})

# Check if next node is ready
if tracker.is_ready("process", ["fetch"]):
    tracker.start_node("process")
```

## Architecture

### Event Flow

```
User Command
    ↓
RunRegistry.submit_command()
    ↓
Orchestrator.handle_command()
    ↓
PolicyEngine.classify() → [requires_approval?]
    ↓                              ↓
[auto-grant]              ApprovalLedger.request()
    ↓                              ↓
ExecutionDispatcher         [wait for approval]
    ↓                              ↓
Adapter.exec()            ApprovalLedger.approve()
    ↓                              ↓
EventJournal.append()     ExecutionDispatcher
    ↓                              ↓
State Updated              Adapter.exec()
```

### Component Overview

| Component     | Purpose                                          |
| ------------- | ------------------------------------------------ |
| **Kernel**    | Event sourcing, orchestration, state reduction   |
| **Policy**    | Capability classification, approval management   |
| **Execution** | Sandboxed adapters for external operations       |
| **Skill**     | Discovery, trust enforcement, capability control |
| **Workflow**  | DAG-based task graphs, state tracking            |
| **Subagent**  | Multi-agent coordination and grant inheritance   |
| **Context**   | Token-aware context compilation                  |
| **Timeline**  | Execution history reconstruction                 |
| **Memory**    | Checkpoint/restore for state persistence         |
| **API**       | HTTP interface for command submission            |

## Key Concepts

### Capability Taxonomy

Capabilities are classified into risk tiers:

- **T0 (Read-only)**: `fs:read`, `git:status`, `mcp:resource:read`
- **T1 (Low-risk write)**: `fs:write` (within workspace), `git:commit`
- **T2 (Medium-risk)**: `shell:exec` (sandboxed), `mcp:tool:invoke`
- **T3 (High-risk)**: `shell:exec` (network), `fs:delete`, `git:push`

### Trust Tiers

Skills are assigned trust levels:

- **TRUSTED (0-1)**: Auto-approved, no restrictions
- **REVIEWED (2)**: Requires approval on first use
- **UNTRUSTED (3+)**: Blocked or strict approval required

### Event Journal

All operations are recorded as immutable events:

```json
{
  "seq": 42,
  "run_id": "01HXYZ...",
  "event_type": "command_submitted",
  "timestamp": "2026-04-17T10:30:00Z",
  "payload": {
    "capability": "fs:read",
    "args": { "path": "/data/file.txt" }
  }
}
```

### Grant Lifecycle

1. **Request**: Command submitted, policy classifies risk
2. **Approval**: Human approves/rejects high-risk operations
3. **Grant**: Approval creates time-limited grant
4. **Execution**: Adapter executes with grant reference
5. **Expiration**: Grants expire after TTL, require re-approval

## Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src/reins --cov-report=html

# Run specific test file
pytest tests/test_workflow.py -v
```

### Code Quality

```bash
# Linting
ruff check src/ tests/

# Type checking
mypy src/ --strict

# Format code
ruff format src/ tests/
```

### Project Structure

```
src/reins/
├── kernel/          # Event sourcing, orchestration, state reduction
├── policy/          # Capability classification, approval system
├── execution/       # Adapters (fs, shell, git, mcp, test)
├── skill/           # Discovery, trust tiers, capabilities
├── workflow/        # DAG graphs, state tracking, decisions
├── subagent/        # Multi-agent coordination
├── context/         # Context compilation
├── timeline/        # Execution history
├── memory/          # Checkpoint/restore
├── api/             # HTTP server
└── observability/   # Tracing and metrics

tests/
├── test_kernel/
├── test_policy/
├── test_execution/
├── test_skill_*.py
├── test_workflow.py
└── test_integration.py
```

## Testing

The project has comprehensive test coverage:

- **254 tests** covering all major components
- **Unit tests**: Individual component behavior
- **Integration tests**: End-to-end workflows
- **Regression tests**: Bug fixes and edge cases

Key test suites:

- `test_execution_boundary.py` - Adapter sandboxing
- `test_grant_lifecycle.py` - Approval flow
- `test_skill_trust.py` - Trust tier enforcement
- `test_workflow.py` - DAG execution (25 tests)
- `test_mcp_integration.py` - MCP server integration

## API Server

Start the HTTP API server:

```bash
python -m reins.api.server --port 8000 --journal ./journal
```

### Endpoints

- `POST /runs` - Submit command
- `GET /runs/{run_id}` - Get run state
- `GET /runs/{run_id}/timeline` - Get execution timeline
- `POST /approvals/{request_id}/approve` - Approve pending request
- `POST /approvals/{request_id}/reject` - Reject pending request
- `GET /mcp/servers` - List MCP servers
- `POST /mcp/servers/{server_id}/connect` - Connect to MCP server

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting (`pytest && ruff check`)
5. Commit your changes (`git commit -m 'feat: add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## License

[Add your license here]

## Acknowledgments

Built with:

- [Pydantic](https://pydantic.dev/) - Data validation
- [aiohttp](https://docs.aiohttp.org/) - Async HTTP
- [structlog](https://www.structlog.org/) - Structured logging
- [pytest](https://pytest.org/) - Testing framework
