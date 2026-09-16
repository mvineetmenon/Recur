"""
Unit tests for StatusEvaluator (recursive evaluation, tree building, summaries)
"""

from datetime import datetime, timezone

import pytest

from server.app.models import (
    Agent,
    HealthStatus,
    StatusReport,
    System,
    SystemDependency,
    Task,
    TaskResult,
)
from server.app.services.status_evaluator import StatusEvaluator


@pytest.fixture
def tree_db(test_db):
    """
    A three-level system tree:

        root (task: root-task)
        └── child (task: child-task)
            └── leaf (task: leaf-task)
    """
    db = test_db

    agent = Agent(
        agent_id="eval-agent",
        hostname="eval.local",
        ip_address="192.168.1.70",
        status=HealthStatus.UNKNOWN,
    )
    db.add(agent)
    db.flush()

    root = System(
        system_id="root", name="Root", config={"name": "Root", "tasks": []},
        status=HealthStatus.UNKNOWN, agent_id=agent.id,
    )
    child = System(
        system_id="child", name="Child", config={"name": "Child", "tasks": []},
        status=HealthStatus.UNKNOWN, agent_id=agent.id,
    )
    leaf = System(
        system_id="leaf", name="Leaf", config={"name": "Leaf", "tasks": []},
        status=HealthStatus.UNKNOWN, agent_id=agent.id,
    )
    db.add_all([root, child, leaf])
    db.flush()

    root_task = Task(
        task_id="root-task", system_id=root.id, name="root-task",
        task_type="command", config={}, status=HealthStatus.UNKNOWN,
    )
    child_task = Task(
        task_id="child-task", system_id=child.id, name="child-task",
        task_type="command", config={}, status=HealthStatus.UNKNOWN,
    )
    leaf_task = Task(
        task_id="leaf-task", system_id=leaf.id, name="leaf-task",
        task_type="command", config={}, status=HealthStatus.UNKNOWN,
    )
    db.add_all([root_task, child_task, leaf_task])
    db.flush()

    report = StatusReport(
        agent_id=agent.id,
        system_id=root.id,
        report_timestamp=datetime.now(timezone.utc),
        report_data={},
    )
    db.add(report)
    db.flush()

    db.add_all([
        SystemDependency(parent_system_id=root.id, child_system_id=child.id,
                         criticality="HIGH"),
        SystemDependency(parent_system_id=child.id, child_system_id=leaf.id,
                         criticality="HIGH"),
    ])
    db.commit()

    return {
        "db": db,
        "agent": agent,
        "root": root,
        "child": child,
        "leaf": leaf,
        "root_task": root_task,
        "child_task": child_task,
        "leaf_task": leaf_task,
        "report": report,
    }


def _add_result(ctx, task, status, report=None, created_offset=0):
    """Add a TaskResult row for a task (created_at offset distinguishes ordering)"""
    report = report or ctx["report"]
    result = TaskResult(
        task_id=task.id,
        status_report_id=report.id,
        status=status,
        created_at=datetime.now(timezone.utc).replace(
            microsecond=created_offset
        ),
    )
    ctx["db"].add(result)
    ctx["db"].commit()
    return result


class TestEvaluateSystemStatus:
    """Recursive status evaluation over real dependency trees"""

    def test_no_data_is_unknown(self, tree_db):
        ctx = tree_db
        assert (
            StatusEvaluator.evaluate_system_status(ctx["root"], ctx["db"])
            is HealthStatus.UNKNOWN
        )

    def test_empty_system_is_unknown(self, test_db):
        db = test_db
        system = System(
            system_id="lonely", name="Lonely",
            config={"name": "Lonely", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        db.add(system)
        db.commit()
        assert (
            StatusEvaluator.evaluate_system_status(system, db)
            is HealthStatus.UNKNOWN
        )

    def test_all_up_is_up(self, tree_db):
        ctx = tree_db
        for i, task in enumerate([ctx["leaf_task"], ctx["child_task"], ctx["root_task"]]):
            _add_result(ctx, task, HealthStatus.UP, created_offset=i)
        db = ctx["db"]
        db.expire_all()
        assert (
            StatusEvaluator.evaluate_system_status(ctx["root"], db) is HealthStatus.UP
        )
        assert (
            StatusEvaluator.evaluate_system_status(ctx["child"], db) is HealthStatus.UP
        )

    def test_down_leaf_propagates_to_root(self, tree_db):
        """A DOWN two levels deep makes the root DOWN"""
        ctx = tree_db
        _add_result(ctx, ctx["root_task"], HealthStatus.UP, created_offset=0)
        _add_result(ctx, ctx["child_task"], HealthStatus.UP, created_offset=1)
        _add_result(ctx, ctx["leaf_task"], HealthStatus.DOWN, created_offset=2)
        db = ctx["db"]
        db.expire_all()

        assert (
            StatusEvaluator.evaluate_system_status(ctx["leaf"], db) is HealthStatus.DOWN
        )
        assert (
            StatusEvaluator.evaluate_system_status(ctx["child"], db) is HealthStatus.DOWN
        )
        assert (
            StatusEvaluator.evaluate_system_status(ctx["root"], db) is HealthStatus.DOWN
        )

    def test_unknown_child_keeps_root_unknown(self, tree_db):
        """UP tasks plus a child with no data => UNKNOWN (not UP, not DOWN)"""
        ctx = tree_db
        _add_result(ctx, ctx["root_task"], HealthStatus.UP, created_offset=0)
        _add_result(ctx, ctx["child_task"], HealthStatus.UP, created_offset=1)
        # leaf_task has no result
        db = ctx["db"]
        db.expire_all()
        assert (
            StatusEvaluator.evaluate_system_status(ctx["root"], db) is HealthStatus.UNKNOWN
        )

    def test_uses_latest_result(self, tree_db):
        ctx = tree_db
        _add_result(ctx, ctx["leaf_task"], HealthStatus.DOWN, created_offset=0)
        _add_result(ctx, ctx["leaf_task"], HealthStatus.UP, created_offset=1)
        _add_result(ctx, ctx["child_task"], HealthStatus.UP, created_offset=2)
        _add_result(ctx, ctx["root_task"], HealthStatus.UP, created_offset=3)
        db = ctx["db"]
        db.expire_all()
        assert (
            StatusEvaluator.evaluate_system_status(ctx["root"], db) is HealthStatus.UP
        )


class TestGetSystemTree:
    """Tree building over nested dependencies"""

    def test_tree_contains_full_hierarchy(self, tree_db):
        ctx = tree_db
        _add_result(ctx, ctx["root_task"], HealthStatus.UP, created_offset=0)
        _add_result(ctx, ctx["child_task"], HealthStatus.UP, created_offset=1)
        _add_result(ctx, ctx["leaf_task"], HealthStatus.DOWN, created_offset=2)
        # Tree reports the stored system status (refreshed by report processing)
        ctx["root"].status = HealthStatus.DOWN
        ctx["db"].commit()
        ctx["db"].expire_all()

        tree = StatusEvaluator.get_system_tree(ctx["root"], ctx["db"])

        assert tree["system_id"] == "root"
        assert tree["status"] is HealthStatus.DOWN
        assert len(tree["tasks"]) == 1
        assert tree["tasks"][0]["task_id"] == "root-task"
        assert tree["tasks"][0]["status"] is HealthStatus.UP

        assert len(tree["dependencies"]) == 1
        child_tree = tree["dependencies"][0]
        assert child_tree["system_id"] == "child"
        assert child_tree["tasks"][0]["task_id"] == "child-task"

        assert len(child_tree["dependencies"]) == 1
        leaf_tree = child_tree["dependencies"][0]
        assert leaf_tree["system_id"] == "leaf"
        assert leaf_tree["tasks"][0]["task_id"] == "leaf-task"
        assert leaf_tree["tasks"][0]["status"] is HealthStatus.DOWN

    def test_tree_task_without_result_is_unknown(self, tree_db):
        ctx = tree_db
        ctx["db"].expire_all()
        tree = StatusEvaluator.get_system_tree(ctx["root"], ctx["db"])
        assert tree["tasks"][0]["status"] is HealthStatus.UNKNOWN
        assert tree["tasks"][0]["duration_ms"] is None


class TestCycleGuard:
    """Evaluator must stay safe even if a cycle exists in the data"""

    def _make_cycle(self, db):
        a = System(
            system_id="cy-a", name="A", config={"name": "A", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        b = System(
            system_id="cy-b", name="B", config={"name": "B", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        db.add_all([a, b])
        db.flush()
        db.add_all([
            SystemDependency(parent_system_id=a.id, child_system_id=b.id,
                             criticality="HIGH"),
            SystemDependency(parent_system_id=b.id, child_system_id=a.id,
                             criticality="HIGH"),
        ])
        db.commit()
        return a

    def test_cycle_evaluation_returns_unknown(self, test_db):
        a = self._make_cycle(test_db)
        # Must terminate (no RecursionError) and not report UP/DOWN
        assert (
            StatusEvaluator.evaluate_system_status(a, test_db)
            is HealthStatus.UNKNOWN
        )

    def test_cycle_tree_terminates(self, test_db):
        a = self._make_cycle(test_db)
        tree = StatusEvaluator.get_system_tree(a, test_db)
        assert tree["system_id"] == "cy-a"
        # The cycle is cut at the back-reference: B contains A as a stub
        # (empty tasks/dependencies) instead of recursing forever
        assert len(tree["dependencies"]) == 1
        b_tree = tree["dependencies"][0]
        assert b_tree["system_id"] == "cy-b"
        assert len(b_tree["dependencies"]) == 1
        a_stub = b_tree["dependencies"][0]
        assert a_stub["system_id"] == "cy-a"
        assert a_stub["dependencies"] == []
        assert a_stub["tasks"] == []

    def test_diamond_dependency_evaluated_on_every_path(self, test_db):
        """A shared child (diamond) is not mistaken for a cycle"""
        top = System(
            system_id="dia-top", name="Top", config={"name": "T", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        left = System(
            system_id="dia-left", name="Left", config={"name": "L", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        right = System(
            system_id="dia-right", name="Right", config={"name": "R", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        shared = System(
            system_id="dia-shared", name="Shared", config={"name": "S", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        test_db.add_all([top, left, right, shared])
        test_db.flush()
        test_db.add_all([
            SystemDependency(parent_system_id=top.id, child_system_id=left.id),
            SystemDependency(parent_system_id=top.id, child_system_id=right.id),
            SystemDependency(parent_system_id=left.id, child_system_id=shared.id),
            SystemDependency(parent_system_id=right.id, child_system_id=shared.id),
        ])
        test_db.commit()

        tree = StatusEvaluator.get_system_tree(top, test_db)
        # Shared child appears fully rendered under both parents
        assert tree["dependencies"][0]["system_id"] == "dia-left"
        assert tree["dependencies"][1]["system_id"] == "dia-right"
        assert (
            tree["dependencies"][0]["dependencies"][0]["system_id"] == "dia-shared"
        )
        assert (
            tree["dependencies"][1]["dependencies"][0]["system_id"] == "dia-shared"
        )


class TestHealthSummary:
    """get_system_health_summary"""

    def test_summary_counts(self, tree_db):
        ctx = tree_db
        _add_result(ctx, ctx["root_task"], HealthStatus.UP, created_offset=0)
        _add_result(ctx, ctx["child_task"], HealthStatus.DOWN, created_offset=1)
        _add_result(ctx, ctx["leaf_task"], HealthStatus.DOWN, created_offset=2)
        ctx["db"].expire_all()

        summary = StatusEvaluator.get_system_health_summary(ctx["root"], ctx["db"])

        assert summary["system_id"] == "root"
        assert summary["status"] is HealthStatus.DOWN
        assert summary["task_count"] == 1
        assert summary["task_statuses"] == {"UP": 1}
        assert summary["dependency_count"] == 1
