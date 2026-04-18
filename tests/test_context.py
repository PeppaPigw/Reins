"""Tests for the context compiler."""

from reins.context.compiler import ContextCompiler, ContextShard, _estimate_tokens


def test_token_estimation():
    assert _estimate_tokens("") == 1  # min 1
    assert _estimate_tokens("a" * 400) == 100


def test_standing_law_loads(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Rules\nBe good.\n")
    compiler = ContextCompiler()
    shards = compiler.load_standing_law(repo)
    assert len(shards) == 1
    assert shards[0].tier == "A"
    assert "Be good" in shards[0].content


def test_active_set_builds():
    compiler = ContextCompiler()
    shards = compiler.build_active_set(
        run_id="run-1",
        snapshot={"run_phase": "executing", "pending_approvals": ["a1"]},
        open_nodes=[{"node_id": "n1", "objective": "fix bug"}],
        eval_failures=[{"failure_class": "logic_failure", "details": "test failed"}],
        affected_files=["src/foo.py"],
    )
    assert len(shards) == 4  # snapshot + open_node + eval_failure + affected_files
    assert all(s.tier == "B" for s in shards)


def test_active_set_includes_repair_metadata():
    compiler = ContextCompiler()
    shards = compiler.build_active_set(
        run_id="run-1",
        snapshot={"run_phase": "resumable"},
        open_nodes=[],
        eval_failures=[
            {
                "failure_class": "logic_failure",
                "details": "assertion failed",
                "repair_route": "change_hypothesis",
                "retry_allowed": False,
                "repair_hints": ["fix assertion", "rewrite expectation"],
            }
        ],
        affected_files=[],
    )

    eval_shard = next(shard for shard in shards if shard.source == "eval_failure")
    assert "Repair route: change_hypothesis" in eval_shard.content
    assert "Retry allowed: False" in eval_shard.content
    assert "fix assertion" in eval_shard.content


def test_active_set_includes_repairing_command_in_snapshot():
    compiler = ContextCompiler()
    shards = compiler.build_active_set(
        run_id="run-1",
        snapshot={"run_phase": "executing", "repairing_command_id": "cmd-repair-1"},
        open_nodes=[],
        eval_failures=[],
        affected_files=[],
    )
    snapshot_shard = next(shard for shard in shards if shard.source == "snapshot")
    assert "Repairing command: cmd-repair-1" in snapshot_shard.content


def test_active_set_includes_last_completed_repair_in_snapshot():
    compiler = ContextCompiler()
    shards = compiler.build_active_set(
        run_id="run-1",
        snapshot={
            "run_phase": "resumable",
            "last_completed_repair": {
                "failure_class": "logic_failure",
                "command_id": "cmd-repair-1",
            },
        },
        open_nodes=[],
        eval_failures=[],
        affected_files=[],
    )
    snapshot_shard = next(shard for shard in shards if shard.source == "snapshot")
    assert (
        "Last completed repair: logic_failure via cmd-repair-1"
        in snapshot_shard.content
    )


def test_compile_respects_budget():
    compiler = ContextCompiler(token_budget=50)
    # Tier A shard
    big = ContextShard(
        tier="A",
        source="agents.md",
        content="x" * 200,
        token_estimate=50,
        priority=100.0,
    )
    small = ContextShard(
        tier="B", source="nodes", content="y" * 40, token_estimate=10, priority=90.0
    )
    tiny = ContextShard(
        tier="C", source="episode", content="z" * 40, token_estimate=10, priority=50.0
    )

    compiler._standing_law = [big]
    ws = compiler.compile("run-1", [small, tiny])

    # Budget is 50 tokens.  big=50, small=10 would exceed, so only big fits
    assert ws.total_tokens == 50
    assert len(ws.shards) == 1
    assert ws.shards[0].source == "agents.md"
    assert "nodes" in ws.dropped or "episode" in ws.dropped


def test_compile_drops_lowest_priority():
    compiler = ContextCompiler(token_budget=100)
    hi = ContextShard(
        tier="A", source="law", content="x" * 200, token_estimate=60, priority=100.0
    )
    lo = ContextShard(
        tier="D", source="cold", content="y" * 200, token_estimate=60, priority=10.0
    )

    ws = compiler.compile("run-1", [hi, lo])
    # Only room for one (60 tokens each, budget 100)
    assert len(ws.shards) == 1
    assert ws.shards[0].source == "law"  # higher priority wins
    assert "cold" in ws.dropped
