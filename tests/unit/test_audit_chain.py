"""Tests for tamper-evident audit chain."""

from __future__ import annotations

import pytest

from reins.audit_chain import (
    AuditAction,
    AuditChain,
    AuditChainStats,
    AuditEntry,
    AuditQuery,
    AuditSeverity,
    ChainVerification,
    IntegrityStatus,
)


@pytest.fixture
def chain() -> AuditChain:
    return AuditChain()


def test_record_entry(chain):
    entry = chain.record(AuditAction.AGENT_STARTED, agent_id="agent-1",
                         subject="Task execution begun")
    assert entry.sequence == 0
    assert entry.action == AuditAction.AGENT_STARTED
    assert entry.entry_hash != ""
    assert entry.previous_hash == "genesis"


def test_chain_linking(chain):
    e1 = chain.record(AuditAction.AGENT_STARTED, agent_id="a")
    e2 = chain.record(AuditAction.TOOL_INVOKED, agent_id="a")
    assert e2.previous_hash == e1.entry_hash
    assert e2.sequence == 1


def test_verify_valid_chain(chain):
    chain.record(AuditAction.AGENT_STARTED, agent_id="a")
    chain.record(AuditAction.DATA_ACCESSED, agent_id="a")
    chain.record(AuditAction.AGENT_COMPLETED, agent_id="a")
    result = chain.verify()
    assert result.status == IntegrityStatus.VALID
    assert result.entries_checked == 3


def test_verify_empty_chain(chain):
    result = chain.verify()
    assert result.status == IntegrityStatus.VALID
    assert result.entries_checked == 0


def test_verify_detects_tampering(chain):
    chain.record(AuditAction.AGENT_STARTED, agent_id="a")
    chain.record(AuditAction.DATA_MODIFIED, agent_id="a",
                 details={"file": "secret.txt"})
    chain._entries[1] = chain._entries[1].model_copy(
        update={"entry_hash": "tampered_hash_value"}
    )
    result = chain.verify()
    assert result.status == IntegrityStatus.TAMPERED
    assert result.first_invalid == 1


def test_verify_detects_broken_chain(chain):
    chain.record(AuditAction.AGENT_STARTED, agent_id="a")
    chain.record(AuditAction.TOOL_INVOKED, agent_id="a")
    chain._entries[1] = chain._entries[1].model_copy(
        update={"previous_hash": "wrong_previous"}
    )
    result = chain.verify()
    assert result.status == IntegrityStatus.BROKEN_CHAIN
    assert result.first_invalid == 1


def test_query_by_agent(chain):
    chain.record(AuditAction.AGENT_STARTED, agent_id="a")
    chain.record(AuditAction.AGENT_STARTED, agent_id="b")
    chain.record(AuditAction.AGENT_COMPLETED, agent_id="a")
    results = chain.query(AuditQuery(agent_id="a"))
    assert len(results) == 2


def test_query_by_action(chain):
    chain.record(AuditAction.TOOL_INVOKED, agent_id="a")
    chain.record(AuditAction.DATA_ACCESSED, agent_id="a")
    chain.record(AuditAction.TOOL_INVOKED, agent_id="b")
    results = chain.query(AuditQuery(action=AuditAction.TOOL_INVOKED))
    assert len(results) == 2


def test_query_by_severity(chain):
    chain.record(AuditAction.SAFETY_VIOLATION, severity=AuditSeverity.CRITICAL)
    chain.record(AuditAction.DATA_ACCESSED, severity=AuditSeverity.INFO)
    results = chain.query(AuditQuery(severity=AuditSeverity.CRITICAL))
    assert len(results) == 1


def test_query_by_sequence_range(chain):
    for i in range(10):
        chain.record(AuditAction.TOOL_INVOKED, agent_id="a",
                     subject=f"step-{i}")
    results = chain.query(AuditQuery(from_sequence=3, to_sequence=6))
    assert len(results) == 4
    assert results[0].sequence == 3
    assert results[-1].sequence == 6


def test_query_limit(chain):
    for _ in range(20):
        chain.record(AuditAction.TOOL_INVOKED, agent_id="a")
    results = chain.query(AuditQuery(limit=5))
    assert len(results) == 5


def test_query_all(chain):
    chain.record(AuditAction.AGENT_STARTED)
    chain.record(AuditAction.AGENT_COMPLETED)
    assert len(chain.query()) == 2


def test_get_entry(chain):
    chain.record(AuditAction.AGENT_STARTED, agent_id="a")
    chain.record(AuditAction.AGENT_COMPLETED, agent_id="a")
    assert chain.get_entry(0).action == AuditAction.AGENT_STARTED
    assert chain.get_entry(1).action == AuditAction.AGENT_COMPLETED
    assert chain.get_entry(99) is None


def test_get_latest(chain):
    for i in range(20):
        chain.record(AuditAction.TOOL_INVOKED, subject=f"op-{i}")
    latest = chain.get_latest(5)
    assert len(latest) == 5
    assert latest[0].sequence == 15


def test_export_range(chain):
    for i in range(5):
        chain.record(AuditAction.DATA_ACCESSED, subject=f"file-{i}")
    exported = chain.export_range(1, 3)
    assert len(exported) == 3
    assert exported[0]["sequence"] == 1


def test_stats(chain):
    chain.record(AuditAction.AGENT_STARTED, agent_id="a",
                 severity=AuditSeverity.INFO)
    chain.record(AuditAction.SAFETY_VIOLATION, agent_id="b",
                 severity=AuditSeverity.CRITICAL)
    chain.record(AuditAction.TOOL_INVOKED, agent_id="a",
                 severity=AuditSeverity.INFO)
    stats = chain.get_stats()
    assert stats.total_entries == 3
    assert stats.integrity_status == IntegrityStatus.VALID
    assert stats.by_action["agent.started"] == 1
    assert stats.by_action["safety.violation"] == 1
    assert stats.by_severity["critical"] == 1
    assert stats.by_agent["a"] == 2


def test_all_actions(chain):
    for action in AuditAction:
        chain.record(action, agent_id="test")
    assert len(chain.query()) == len(AuditAction)
    result = chain.verify()
    assert result.status == IntegrityStatus.VALID


def test_details_preserved(chain):
    entry = chain.record(AuditAction.DATA_MODIFIED, agent_id="a",
                         details={"file": "/etc/config", "diff_lines": 42})
    assert entry.details["file"] == "/etc/config"
    assert entry.details["diff_lines"] == 42


def test_long_chain_integrity(chain):
    for i in range(100):
        chain.record(AuditAction.TOOL_INVOKED, agent_id=f"agent-{i % 5}",
                     subject=f"operation-{i}")
    result = chain.verify()
    assert result.status == IntegrityStatus.VALID
    assert result.entries_checked == 100
