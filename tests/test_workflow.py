"""Tests for multi-node workflow system."""

import pytest

from reins.workflow.graph import (
    NodeType,
    TaskGraphBuilder,
)
from reins.workflow.state import (
    NodeStateTracker,
    NodeStatus,
)
from reins.workflow.decision import (
    DecisionManager,
)


class TestTaskGraphBuilder:
    """Tests for task graph building."""

    def test_create_graph(self):
        """Test creating a new workflow graph."""
        builder = TaskGraphBuilder()
        graph = builder.create_graph("test-graph")

        assert graph.graph_id == "test-graph"
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_add_node(self):
        """Test adding nodes to graph."""
        builder = TaskGraphBuilder()
        builder.create_graph("test-graph")

        node = builder.add_node("test-graph", "node1", NodeType.TASK, "Task 1")

        assert node.node_id == "node1"
        assert node.node_type == NodeType.TASK
        assert node.name == "Task 1"
        assert len(node.dependencies) == 0

    def test_add_edge(self):
        """Test adding edges between nodes."""
        builder = TaskGraphBuilder()
        builder.create_graph("test-graph")
        builder.add_node("test-graph", "node1", NodeType.TASK, "Task 1")
        builder.add_node("test-graph", "node2", NodeType.TASK, "Task 2")

        builder.add_edge("test-graph", "node1", "node2")

        graph = builder.get_graph("test-graph")
        assert ("node1", "node2") in graph.edges
        assert "node1" in graph.nodes["node2"].dependencies

    def test_add_edge_nonexistent_graph(self):
        """Test adding edge to nonexistent graph raises error."""
        builder = TaskGraphBuilder()

        with pytest.raises(ValueError, match="Graph .* not found"):
            builder.add_edge("nonexistent", "node1", "node2")

    def test_complex_graph(self):
        """Test building a complex graph with multiple dependencies."""
        builder = TaskGraphBuilder()
        builder.create_graph("complex")

        # Create nodes
        builder.add_node("complex", "start", NodeType.TASK, "Start")
        builder.add_node("complex", "task1", NodeType.TASK, "Task 1")
        builder.add_node("complex", "task2", NodeType.TASK, "Task 2")
        builder.add_node("complex", "decision", NodeType.DECISION, "Decision")
        builder.add_node("complex", "end", NodeType.TASK, "End")

        # Create edges
        builder.add_edge("complex", "start", "task1")
        builder.add_edge("complex", "start", "task2")
        builder.add_edge("complex", "task1", "decision")
        builder.add_edge("complex", "task2", "decision")
        builder.add_edge("complex", "decision", "end")

        graph = builder.get_graph("complex")
        assert len(graph.nodes) == 5
        assert len(graph.edges) == 5
        assert len(graph.nodes["decision"].dependencies) == 2
        assert len(graph.nodes["end"].dependencies) == 1


class TestNodeStateTracker:
    """Tests for node state tracking."""

    def test_initialize_node(self):
        """Test initializing node state."""
        tracker = NodeStateTracker()
        state = tracker.initialize_node("node1")

        assert state.node_id == "node1"
        assert state.status == NodeStatus.PENDING
        assert state.started_at is None
        assert state.completed_at is None
        assert state.error is None

    def test_start_node(self):
        """Test starting a node."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")

        tracker.start_node("node1")

        state = tracker.get_state("node1")
        assert state.status == NodeStatus.RUNNING
        assert state.started_at is not None

    def test_complete_node(self):
        """Test completing a node."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")
        tracker.start_node("node1")

        output = {"result": "success"}
        tracker.complete_node("node1", output)

        state = tracker.get_state("node1")
        assert state.status == NodeStatus.COMPLETED
        assert state.completed_at is not None
        assert state.output == output

    def test_fail_node(self):
        """Test failing a node."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")
        tracker.start_node("node1")

        tracker.fail_node("node1", "Test error")

        state = tracker.get_state("node1")
        assert state.status == NodeStatus.FAILED
        assert state.completed_at is not None
        assert state.error == "Test error"

    def test_is_ready_no_dependencies(self):
        """Test node is ready when it has no dependencies."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")

        assert tracker.is_ready("node1", [])

    def test_is_ready_with_completed_dependencies(self):
        """Test node is ready when all dependencies are completed."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")
        tracker.initialize_node("node2")
        tracker.start_node("node1")
        tracker.complete_node("node1")

        assert tracker.is_ready("node2", ["node1"])

    def test_is_not_ready_with_pending_dependencies(self):
        """Test node is not ready when dependencies are pending."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")
        tracker.initialize_node("node2")

        assert not tracker.is_ready("node2", ["node1"])

    def test_is_not_ready_with_running_dependencies(self):
        """Test node is not ready when dependencies are running."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")
        tracker.initialize_node("node2")
        tracker.start_node("node1")

        assert not tracker.is_ready("node2", ["node1"])

    def test_is_not_ready_with_failed_dependencies(self):
        """Test node is not ready when dependencies have failed."""
        tracker = NodeStateTracker()
        tracker.initialize_node("node1")
        tracker.initialize_node("node2")
        tracker.start_node("node1")
        tracker.fail_node("node1", "Error")

        assert not tracker.is_ready("node2", ["node1"])


class TestDecisionManager:
    """Tests for decision and question management."""

    def test_create_decision(self):
        """Test creating a decision point."""
        manager = DecisionManager()
        decision = manager.create_decision(
            "dec1", "node1", "Choose option?", ["A", "B", "C"]
        )

        assert decision.decision_id == "dec1"
        assert decision.node_id == "node1"
        assert decision.question == "Choose option?"
        assert decision.options == ["A", "B", "C"]
        assert decision.selected is None
        assert decision.decided_at is None

    def test_make_decision(self):
        """Test making a decision."""
        manager = DecisionManager()
        manager.create_decision("dec1", "node1", "Choose?", ["A", "B"])

        manager.make_decision("dec1", "A")

        decision = manager.decisions["dec1"]
        assert decision.selected == "A"
        assert decision.decided_at is not None

    def test_create_question(self):
        """Test creating a question."""
        manager = DecisionManager()
        question = manager.create_question("q1", "node1", "What is your name?")

        assert question.question_id == "q1"
        assert question.node_id == "node1"
        assert question.question == "What is your name?"
        assert question.answer is None
        assert question.answered_at is None

    def test_answer_question(self):
        """Test answering a question."""
        manager = DecisionManager()
        manager.create_question("q1", "node1", "What is your name?")

        manager.answer_question("q1", "Alice")

        question = manager.questions["q1"]
        assert question.answer == "Alice"
        assert question.answered_at is not None

    def test_get_pending_decisions(self):
        """Test getting pending decisions."""
        manager = DecisionManager()
        manager.create_decision("dec1", "node1", "Q1?", ["A", "B"])
        manager.create_decision("dec2", "node2", "Q2?", ["X", "Y"])
        manager.make_decision("dec1", "A")

        pending = manager.get_pending_decisions()

        assert len(pending) == 1
        assert pending[0].decision_id == "dec2"

    def test_get_pending_questions(self):
        """Test getting pending questions."""
        manager = DecisionManager()
        manager.create_question("q1", "node1", "Q1?")
        manager.create_question("q2", "node2", "Q2?")
        manager.answer_question("q1", "Answer 1")

        pending = manager.get_pending_questions()

        assert len(pending) == 1
        assert pending[0].question_id == "q2"


class TestWorkflowIntegration:
    """Integration tests for complete workflow scenarios."""

    def test_simple_sequential_workflow(self):
        """Test a simple sequential workflow execution."""
        # Build graph
        builder = TaskGraphBuilder()
        builder.create_graph("seq")
        builder.add_node("seq", "task1", NodeType.TASK, "Task 1")
        builder.add_node("seq", "task2", NodeType.TASK, "Task 2")
        builder.add_node("seq", "task3", NodeType.TASK, "Task 3")
        builder.add_edge("seq", "task1", "task2")
        builder.add_edge("seq", "task2", "task3")

        # Track state
        tracker = NodeStateTracker()
        tracker.initialize_node("task1")
        tracker.initialize_node("task2")
        tracker.initialize_node("task3")

        # Execute task1
        assert tracker.is_ready("task1", [])
        tracker.start_node("task1")
        tracker.complete_node("task1", {"result": "done"})

        # Execute task2
        assert tracker.is_ready("task2", ["task1"])
        tracker.start_node("task2")
        tracker.complete_node("task2", {"result": "done"})

        # Execute task3
        assert tracker.is_ready("task3", ["task2"])
        tracker.start_node("task3")
        tracker.complete_node("task3", {"result": "done"})

        # Verify all completed
        assert tracker.get_state("task1").status == NodeStatus.COMPLETED
        assert tracker.get_state("task2").status == NodeStatus.COMPLETED
        assert tracker.get_state("task3").status == NodeStatus.COMPLETED

    def test_parallel_workflow(self):
        """Test a workflow with parallel execution."""
        # Build graph
        builder = TaskGraphBuilder()
        builder.create_graph("parallel")
        builder.add_node("parallel", "start", NodeType.TASK, "Start")
        builder.add_node("parallel", "parallel1", NodeType.TASK, "Parallel 1")
        builder.add_node("parallel", "parallel2", NodeType.TASK, "Parallel 2")
        builder.add_node("parallel", "end", NodeType.TASK, "End")
        builder.add_edge("parallel", "start", "parallel1")
        builder.add_edge("parallel", "start", "parallel2")
        builder.add_edge("parallel", "parallel1", "end")
        builder.add_edge("parallel", "parallel2", "end")

        # Track state
        tracker = NodeStateTracker()
        for node_id in ["start", "parallel1", "parallel2", "end"]:
            tracker.initialize_node(node_id)

        # Execute start
        tracker.start_node("start")
        tracker.complete_node("start")

        # Execute parallel tasks
        assert tracker.is_ready("parallel1", ["start"])
        assert tracker.is_ready("parallel2", ["start"])
        tracker.start_node("parallel1")
        tracker.start_node("parallel2")
        tracker.complete_node("parallel1")
        tracker.complete_node("parallel2")

        # Execute end
        assert tracker.is_ready("end", ["parallel1", "parallel2"])
        tracker.start_node("end")
        tracker.complete_node("end")

        # Verify all completed
        for node_id in ["start", "parallel1", "parallel2", "end"]:
            assert tracker.get_state(node_id).status == NodeStatus.COMPLETED

    def test_workflow_with_decision(self):
        """Test workflow with decision point."""
        # Build graph
        builder = TaskGraphBuilder()
        builder.create_graph("decision")
        builder.add_node("decision", "task1", NodeType.TASK, "Task 1")
        builder.add_node("decision", "decision", NodeType.DECISION, "Decision")
        builder.add_node("decision", "task2a", NodeType.TASK, "Task 2A")
        builder.add_node("decision", "task2b", NodeType.TASK, "Task 2B")
        builder.add_edge("decision", "task1", "decision")

        # Track state and decisions
        tracker = NodeStateTracker()
        decision_mgr = DecisionManager()
        for node_id in ["task1", "decision", "task2a", "task2b"]:
            tracker.initialize_node(node_id)

        # Execute task1
        tracker.start_node("task1")
        tracker.complete_node("task1")

        # Create decision
        decision_mgr.create_decision(
            "dec1", "decision", "Choose path?", ["path_a", "path_b"]
        )
        assert len(decision_mgr.get_pending_decisions()) == 1

        # Make decision
        decision_mgr.make_decision("dec1", "path_a")
        assert len(decision_mgr.get_pending_decisions()) == 0

        # Execute chosen path
        tracker.start_node("task2a")
        tracker.complete_node("task2a")

        # Verify
        assert tracker.get_state("task1").status == NodeStatus.COMPLETED
        assert tracker.get_state("task2a").status == NodeStatus.COMPLETED
        assert tracker.get_state("task2b").status == NodeStatus.PENDING

    def test_workflow_with_failure(self):
        """Test workflow handling node failure."""
        # Build graph
        builder = TaskGraphBuilder()
        builder.create_graph("failure")
        builder.add_node("failure", "task1", NodeType.TASK, "Task 1")
        builder.add_node("failure", "task2", NodeType.TASK, "Task 2")
        builder.add_edge("failure", "task1", "task2")

        # Track state
        tracker = NodeStateTracker()
        tracker.initialize_node("task1")
        tracker.initialize_node("task2")

        # Execute task1 with failure
        tracker.start_node("task1")
        tracker.fail_node("task1", "Simulated error")

        # Verify task2 cannot proceed
        assert not tracker.is_ready("task2", ["task1"])
        assert tracker.get_state("task1").status == NodeStatus.FAILED
        assert tracker.get_state("task1").error == "Simulated error"
        assert tracker.get_state("task2").status == NodeStatus.PENDING

    def test_workflow_with_questions(self):
        """Test workflow with user questions."""
        # Build graph
        builder = TaskGraphBuilder()
        builder.create_graph("questions")
        builder.add_node("questions", "task1", NodeType.TASK, "Task 1")
        builder.add_node("questions", "task2", NodeType.TASK, "Task 2")
        builder.add_edge("questions", "task1", "task2")

        # Track state and questions
        tracker = NodeStateTracker()
        question_mgr = DecisionManager()
        tracker.initialize_node("task1")
        tracker.initialize_node("task2")

        # Execute task1 and create question
        tracker.start_node("task1")
        question_mgr.create_question("q1", "task1", "What is the input?")
        assert len(question_mgr.get_pending_questions()) == 1

        # Answer question and complete task1
        question_mgr.answer_question("q1", "test input")
        assert len(question_mgr.get_pending_questions()) == 0
        tracker.complete_node("task1", {"input": "test input"})

        # Execute task2
        assert tracker.is_ready("task2", ["task1"])
        tracker.start_node("task2")
        tracker.complete_node("task2")

        # Verify
        assert tracker.get_state("task1").status == NodeStatus.COMPLETED
        assert tracker.get_state("task2").status == NodeStatus.COMPLETED
        assert question_mgr.questions["q1"].answer == "test input"
