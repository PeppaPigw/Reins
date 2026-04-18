# Phase 6: Superiority Features Beyond Trellis

## Overview

Features that establish Reins as superior to Trellis. Focus on event sourcing, policy-driven execution, MCP-native architecture, and advanced agent coordination.

## Feature Breakdown

### 1. Advanced Event Sourcing & Time Travel

**Files to create:**
- `src/reins/kernel/event/time_travel.py` - State reconstruction at any point
- `src/reins/kernel/event/projections.py` - Derived views from events

**Capabilities:**
```python
# Reconstruct state at specific timestamp
state = time_travel.reconstruct_at(timestamp="2026-04-18T10:30:00Z")

# Query historical state
tasks_at_time = time_travel.query_tasks(timestamp=ts)

# Create projections
agent_activity = projections.agent_activity_summary(
    from_time=start,
    to_time=end,
)
```

**Superiority over Trellis:**
- Trellis: No event sourcing, state is mutable
- Reins: Full audit trail, time travel, projections

### 2. Policy-Driven Execution Engine

**Files to create:**
- `src/reins/policy/rules.py` - Declarative policy rules
- `src/reins/policy/constraints.py` - Runtime constraints
- `src/reins/policy/audit.py` - Policy decision audit

**Capabilities:**
```yaml
# .reins/policy.yaml
policies:
  - name: require-approval-for-destructive
    condition: command.risk_tier >= HIGH
    action: require_approval
    
  - name: auto-approve-read-only
    condition: command.risk_tier == READ_ONLY
    action: auto_approve
    
  - name: rate-limit-api-calls
    condition: adapter.type == "api"
    constraint: max_calls_per_minute = 10
```

**Superiority over Trellis:**
- Trellis: No policy engine, manual approval only
- Reins: Declarative policies, automatic enforcement, audit trail

### 3. MCP-Native Architecture

**Files to create:**
- `src/reins/mcp/session.py` - MCP session management
- `src/reins/mcp/registry.py` - Tool/resource registry
- `src/reins/mcp/bridge.py` - Bridge to external MCP servers

**Capabilities:**
```python
# Register MCP tools dynamically
mcp_session.register_tool(
    name="gitnexus_query",
    server="gitnexus",
    schema=tool_schema,
)

# Route tool calls through MCP
result = await mcp_session.call_tool(
    tool="gitnexus_query",
    params={"query": "authentication flow"},
)

# Bridge to remote MCP servers
bridge.connect("codex-mcp", url="http://localhost:3000")
```

**Superiority over Trellis:**
- Trellis: No MCP integration, tools are hardcoded
- Reins: MCP-native, dynamic tool discovery, remote servers

### 4. A2A Remote Agent Coordination

**Files to create:**
- `src/reins/a2a/protocol.py` - Agent-to-agent protocol
- `src/reins/a2a/coordinator.py` - Multi-agent coordination
- `src/reins/a2a/discovery.py` - Agent discovery service

**Capabilities:**
```python
# Register agent with coordinator
coordinator.register_agent(
    agent_id="agent-123",
    capabilities=["python", "typescript"],
    endpoint="http://agent-123:8000",
)

# Discover agents for task
agents = coordinator.discover(
    required_capabilities=["python"],
    max_agents=3,
)

# Coordinate multi-agent task
result = await coordinator.execute_distributed(
    task_id="task-456",
    agents=agents,
    strategy="parallel",
)
```

**Superiority over Trellis:**
- Trellis: Local agents only, no remote coordination
- Reins: A2A protocol, distributed execution, agent discovery

### 5. Checkpoint/Resume System

**Files to create:**
- `src/reins/memory/checkpoint.py` - Enhanced checkpoint system
- `src/reins/memory/dehydration.py` - State dehydration
- `src/reins/memory/wake_conditions.py` - Wake condition evaluation

**Capabilities:**
```python
# Create checkpoint with wake conditions
checkpoint = await checkpoint_manager.create(
    task_id="task-123",
    wake_conditions=[
        WakeCondition(type="time", value="2026-04-18T15:00:00Z"),
        WakeCondition(type="event", value="build.completed"),
        WakeCondition(type="file_change", value="src/main.py"),
    ],
)

# Dehydrate long-running state
dehydrated = dehydration.dehydrate(
    state=current_state,
    keep_fields=["task_id", "agent_id"],
)

# Resume from checkpoint
state = await checkpoint_manager.resume(checkpoint_id="cp-456")
```

**Superiority over Trellis:**
- Trellis: No checkpoint system
- Reins: Explicit checkpoints, wake conditions, dehydration

### 6. Evaluation Framework

**Files to create:**
- `src/reins/evaluation/metrics.py` - Success metrics
- `src/reins/evaluation/feedback_loop.py` - Learning from failures
- `src/reins/evaluation/quality_gates.py` - Quality enforcement

**Capabilities:**
```python
# Define success metrics
metrics = [
    Metric(name="test_coverage", threshold=0.8),
    Metric(name="lint_errors", threshold=0),
    Metric(name="type_errors", threshold=0),
]

# Evaluate task completion
evaluation = await evaluator.evaluate(
    task_id="task-123",
    metrics=metrics,
)

# Learn from failures
feedback = feedback_loop.analyze_failure(
    task_id="task-123",
    error=error,
)
feedback_loop.update_policy(feedback)
```

**Superiority over Trellis:**
- Trellis: No evaluation framework
- Reins: Metrics, quality gates, learning from failures

### 7. Skill Lazy Loading System

**Files to create:**
- `src/reins/skill/loader.py` - Lazy skill loading
- `src/reins/skill/policy_envelope.py` - Policy-wrapped skills
- `src/reins/skill/catalog.py` - Enhanced skill catalog

**Capabilities:**
```python
# Load skill on demand
skill = await skill_loader.load(
    skill_name="git-commit",
    policy_envelope=PolicyEnvelope(
        allowed_capabilities=["git.commit", "git.push"],
        max_execution_time=30,
    ),
)

# Execute skill with policy enforcement
result = await skill.execute(
    params={"message": "feat: add feature"},
    context=execution_context,
)
```

**Superiority over Trellis:**
- Trellis: Skills are static, no policy enforcement
- Reins: Lazy loading, policy envelopes, dynamic catalog

### 8. Context Compiler

**Files to create:**
- `src/reins/context/compiler.py` - Context compilation
- `src/reins/context/optimizer.py` - Context optimization
- `src/reins/context/cache.py` - Context caching

**Capabilities:**
```python
# Compile context from multiple sources
context = await compiler.compile(
    sources=[
        ContextSource(type="spec", path=".reins/spec/backend/"),
        ContextSource(type="task", task_id="task-123"),
        ContextSource(type="journal", event_types=["task.*"]),
    ],
    optimize=True,
)

# Optimize for token budget
optimized = optimizer.optimize(
    context=context,
    max_tokens=10000,
    priority=["task", "spec", "journal"],
)
```

**Superiority over Trellis:**
- Trellis: Simple file concatenation
- Reins: Smart compilation, optimization, caching

### 9. Approval Ledger

**Files to create:**
- `src/reins/approval/ledger.py` - Approval tracking
- `src/reins/approval/delegation.py` - Approval delegation
- `src/reins/approval/audit.py` - Approval audit trail

**Capabilities:**
```python
# Request approval
approval_request = await ledger.request(
    command=command_proposal,
    reason="Destructive operation",
    required_approvers=["human", "policy-engine"],
)

# Delegate approval authority
delegation = await ledger.delegate(
    from_actor="human",
    to_actor="senior-agent",
    scope=["git.commit", "git.push"],
    expires_at=datetime.now() + timedelta(hours=1),
)

# Audit approvals
audit = ledger.audit(
    from_time=start,
    to_time=end,
    actor="human",
)
```

**Superiority over Trellis:**
- Trellis: No approval tracking
- Reins: Full ledger, delegation, audit trail

### 10. Timeline Visualization

**Files to create:**
- `src/reins/observability/timeline.py` - Timeline generation
- `src/reins/observability/visualization.py` - Visual rendering
- `src/reins/observability/export.py` - Export formats

**Capabilities:**
```python
# Generate timeline from events
timeline = timeline_generator.generate(
    from_time=start,
    to_time=end,
    include_types=["task.*", "agent.*", "worktree.*"],
)

# Visualize as ASCII
ascii_viz = visualization.render_ascii(timeline)

# Export as JSON for web UI
json_export = export.to_json(timeline)
```

**Superiority over Trellis:**
- Trellis: No timeline visualization
- Reins: Event timeline, multiple formats, visual rendering

## Implementation Priority

### Phase 6A (High Priority)
1. Advanced Event Sourcing & Time Travel
2. Policy-Driven Execution Engine
3. Context Compiler
4. Approval Ledger

### Phase 6B (Medium Priority)
5. MCP-Native Architecture
6. Checkpoint/Resume System
7. Evaluation Framework
8. Timeline Visualization

### Phase 6C (Future)
9. A2A Remote Agent Coordination
10. Skill Lazy Loading System

## Success Criteria

- [ ] All Phase 6A features implemented
- [ ] Event sourcing supports time travel
- [ ] Policy engine enforces declarative rules
- [ ] Context compiler optimizes token usage
- [ ] Approval ledger tracks all decisions
- [ ] Integration tests for all features
- [ ] Documentation for all features
- [ ] Performance benchmarks show improvement
- [ ] Reins demonstrably superior to Trellis

## Comparison Matrix

| Feature | Trellis | Reins |
|---------|---------|-------|
| Event Sourcing | ❌ | ✅ Full audit trail + time travel |
| Policy Engine | ❌ | ✅ Declarative rules + enforcement |
| MCP Integration | ❌ | ✅ Native MCP + remote servers |
| Remote Agents | ❌ | ✅ A2A protocol + coordination |
| Checkpoints | ❌ | ✅ Wake conditions + dehydration |
| Evaluation | ❌ | ✅ Metrics + quality gates |
| Context Optimization | ❌ | ✅ Smart compilation + caching |
| Approval Tracking | ❌ | ✅ Full ledger + delegation |
| Timeline Viz | ❌ | ✅ Event timeline + export |
| Skill Loading | Static | ✅ Lazy + policy envelopes |
