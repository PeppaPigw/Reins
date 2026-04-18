"""Tests for skill activation and execution."""

import pytest

from reins.skill.catalog import SkillDescriptor, SkillRegistry
from reins.skill.capability import (
    SkillCapabilityRequest,
    SkillCapabilityGrant,
    SkillCapabilityWrapper,
)
from reins.skill.resolver import SkillResolver


@pytest.fixture
def skill_registry(tmp_path):
    """Create a registry with skills having different capabilities."""
    registry_file = tmp_path / "skills.jsonl"

    skills = [
        SkillDescriptor(
            skill_id="file-reader",
            source="test",
            version="1.0.0",
            manifest_hash="hash1",
            name="File Reader",
            description="Reads files",
            trust_tier=0,
            allowed_capabilities=["read_file", "list_directory"],
        ),
        SkillDescriptor(
            skill_id="file-writer",
            source="test",
            version="1.0.0",
            manifest_hash="hash2",
            name="File Writer",
            description="Writes files",
            trust_tier=1,
            allowed_capabilities=["read_file", "write_file", "delete_file"],
        ),
        SkillDescriptor(
            skill_id="network-client",
            source="test",
            version="1.0.0",
            manifest_hash="hash3",
            name="Network Client",
            description="Makes network requests",
            trust_tier=2,
            allowed_capabilities=["http_get", "http_post"],
        ),
        SkillDescriptor(
            skill_id="restricted-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash4",
            name="Restricted Skill",
            description="Has no capabilities",
            trust_tier=3,
            allowed_capabilities=[],
        ),
    ]

    import json

    with open(registry_file, "w") as f:
        for skill in skills:
            f.write(json.dumps(skill.__dict__) + "\n")

    return SkillRegistry(registry_file)


class TestSkillCapabilityWrapper:
    """Tests for skill capability wrapper."""

    def test_can_execute_allowed_capability(self, skill_registry):
        """Test checking if skill can execute allowed capability."""
        descriptor = SkillDescriptor(
            skill_id="test-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash",
            name="Test",
            description="Test skill",
            allowed_capabilities=["read_file", "write_file"],
        )
        wrapper = SkillCapabilityWrapper(descriptor)

        assert wrapper.can_execute("read_file")
        assert wrapper.can_execute("write_file")

    def test_cannot_execute_disallowed_capability(self, skill_registry):
        """Test checking if skill cannot execute disallowed capability."""
        descriptor = SkillDescriptor(
            skill_id="test-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash",
            name="Test",
            description="Test skill",
            allowed_capabilities=["read_file"],
        )
        wrapper = SkillCapabilityWrapper(descriptor)

        assert not wrapper.can_execute("write_file")
        assert not wrapper.can_execute("delete_file")

    def test_create_request(self, skill_registry):
        """Test creating capability request."""
        descriptor = SkillDescriptor(
            skill_id="test-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash",
            name="Test",
            description="Test skill",
            allowed_capabilities=["read_file"],
        )
        wrapper = SkillCapabilityWrapper(descriptor)

        request = wrapper.create_request(
            "read_file",
            {"path": "/tmp/test.txt"},
            "run-123",
        )

        assert request.skill_id == "test-skill"
        assert request.capability == "read_file"
        assert request.args == {"path": "/tmp/test.txt"}
        assert request.run_id == "run-123"
        assert request.requested_by == "skill"

    def test_empty_capabilities(self, skill_registry):
        """Test skill with no capabilities."""
        descriptor = SkillDescriptor(
            skill_id="test-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash",
            name="Test",
            description="Test skill",
            allowed_capabilities=[],
        )
        wrapper = SkillCapabilityWrapper(descriptor)

        assert not wrapper.can_execute("read_file")
        assert not wrapper.can_execute("write_file")


class TestSkillCapabilityRequest:
    """Tests for capability request dataclass."""

    def test_create_request(self):
        """Test creating a capability request."""
        request = SkillCapabilityRequest(
            skill_id="test-skill",
            capability="read_file",
            args={"path": "/tmp/test.txt"},
            run_id="run-123",
        )

        assert request.skill_id == "test-skill"
        assert request.capability == "read_file"
        assert request.args == {"path": "/tmp/test.txt"}
        assert request.run_id == "run-123"
        assert request.requested_by == "skill"

    def test_create_request_with_custom_requester(self):
        """Test creating request with custom requester."""
        request = SkillCapabilityRequest(
            skill_id="test-skill",
            capability="read_file",
            args={},
            run_id="run-123",
            requested_by="orchestrator",
        )

        assert request.requested_by == "orchestrator"


class TestSkillCapabilityGrant:
    """Tests for capability grant dataclass."""

    def test_create_grant_approved(self):
        """Test creating an approved grant."""
        grant = SkillCapabilityGrant(
            request_id="req-123",
            skill_id="test-skill",
            capability="read_file",
            granted=True,
            grant_id="grant-456",
        )

        assert grant.request_id == "req-123"
        assert grant.skill_id == "test-skill"
        assert grant.capability == "read_file"
        assert grant.granted is True
        assert grant.grant_id == "grant-456"
        assert grant.reason == ""

    def test_create_grant_denied(self):
        """Test creating a denied grant."""
        grant = SkillCapabilityGrant(
            request_id="req-123",
            skill_id="test-skill",
            capability="write_file",
            granted=False,
            reason="Insufficient permissions",
        )

        assert grant.granted is False
        assert grant.grant_id is None
        assert grant.reason == "Insufficient permissions"


@pytest.mark.asyncio
async def test_skill_activation_with_capabilities(skill_registry):
    """Test activating skills and checking their capabilities."""
    resolver = SkillResolver(skill_registry)

    # Resolve file-reader skill
    results = await resolver.resolve("file reader", top_k=1)
    assert len(results) > 0

    descriptor = results[0]
    wrapper = SkillCapabilityWrapper(descriptor)

    # Check allowed capabilities
    assert wrapper.can_execute("read_file")
    assert wrapper.can_execute("list_directory")
    assert not wrapper.can_execute("write_file")


@pytest.mark.asyncio
async def test_skill_activation_trust_and_capabilities(skill_registry):
    """Test that trust tier and capabilities work together."""
    resolver = SkillResolver(skill_registry)

    # Get file-writer skill
    file_writer_results = await resolver.resolve("file writer", top_k=1)
    assert len(file_writer_results) > 0
    file_writer = file_writer_results[0]
    wrapper = SkillCapabilityWrapper(file_writer)
    assert wrapper.can_execute("write_file")
    assert wrapper.can_execute("delete_file")

    # Get network-client skill
    network_results = await resolver.resolve("network client", top_k=1)
    assert len(network_results) > 0
    network_client = network_results[0]
    wrapper = SkillCapabilityWrapper(network_client)
    assert wrapper.can_execute("http_get")
    assert wrapper.can_execute("http_post")
    assert not wrapper.can_execute("write_file")


@pytest.mark.asyncio
async def test_capability_request_flow(skill_registry):
    """Test complete capability request flow."""
    resolver = SkillResolver(skill_registry)

    # Resolve skill
    results = await resolver.resolve("file writer", top_k=1)
    descriptor = results[0]

    # Create wrapper
    wrapper = SkillCapabilityWrapper(descriptor)

    # Check capability
    assert wrapper.can_execute("write_file")

    # Create request
    request = wrapper.create_request(
        "write_file",
        {"path": "/tmp/test.txt", "content": "Hello"},
        "run-123",
    )

    assert request.skill_id == descriptor.skill_id
    assert request.capability == "write_file"

    # Simulate grant
    grant = SkillCapabilityGrant(
        request_id="req-123",
        skill_id=request.skill_id,
        capability=request.capability,
        granted=True,
        grant_id="grant-456",
    )

    assert grant.granted is True


@pytest.mark.asyncio
async def test_restricted_skill_cannot_execute(skill_registry):
    """Test that restricted skill cannot execute any capabilities."""
    # Get the restricted skill directly from registry
    all_skills = await skill_registry.search("", [])
    descriptor = next(s for s in all_skills if s.skill_id == "restricted-skill")

    wrapper = SkillCapabilityWrapper(descriptor)

    # Should not be able to execute anything
    assert not wrapper.can_execute("read_file")
    assert not wrapper.can_execute("write_file")
    assert not wrapper.can_execute("http_get")


@pytest.mark.asyncio
async def test_capability_enforcement_with_trust_tiers(skill_registry):
    """Test that capability enforcement works across trust tiers."""
    resolver = SkillResolver(skill_registry)

    # Get skills at different trust tiers
    all_results = await resolver.resolve("skill", top_k=10)

    for descriptor in all_results:
        wrapper = SkillCapabilityWrapper(descriptor)
        _ = await resolver.get_trust_classification_async(descriptor.skill_id)

        # Verify capabilities are enforced regardless of trust tier
        for capability in descriptor.allowed_capabilities:
            assert wrapper.can_execute(capability)

        # Verify disallowed capabilities are blocked
        if "write_file" not in descriptor.allowed_capabilities:
            assert not wrapper.can_execute("write_file")


@pytest.mark.asyncio
async def test_multiple_capability_requests(skill_registry):
    """Test creating multiple capability requests from same skill."""
    resolver = SkillResolver(skill_registry)

    results = await resolver.resolve("file writer", top_k=1)
    descriptor = results[0]
    wrapper = SkillCapabilityWrapper(descriptor)

    # Create multiple requests
    requests = []
    for i in range(3):
        request = wrapper.create_request(
            "write_file",
            {"path": f"/tmp/test{i}.txt"},
            f"run-{i}",
        )
        requests.append(request)

    assert len(requests) == 3
    assert all(r.skill_id == descriptor.skill_id for r in requests)
    assert all(r.capability == "write_file" for r in requests)
    assert [r.run_id for r in requests] == ["run-0", "run-1", "run-2"]


@pytest.mark.asyncio
async def test_capability_request_with_complex_args(skill_registry):
    """Test capability request with complex arguments."""
    resolver = SkillResolver(skill_registry)

    results = await resolver.resolve("network", top_k=1)
    descriptor = results[0]
    wrapper = SkillCapabilityWrapper(descriptor)

    # Create request with complex args
    request = wrapper.create_request(
        "http_post",
        {
            "url": "https://api.example.com/data",
            "headers": {"Content-Type": "application/json"},
            "body": {"key": "value", "nested": {"data": [1, 2, 3]}},
            "timeout": 30,
        },
        "run-123",
    )

    assert request.args["url"] == "https://api.example.com/data"
    assert request.args["headers"]["Content-Type"] == "application/json"
    assert request.args["body"]["nested"]["data"] == [1, 2, 3]
    assert request.args["timeout"] == 30
