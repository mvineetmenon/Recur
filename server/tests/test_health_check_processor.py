"""
Unit tests for HealthCheckProcessor (nested report processing, roll-up, history)
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
from server.app.services.health_check import HealthCheckProcessor
from server.app.services.system_manager import SystemManager


def _make_agent(db, agent_id="proc-agent"):
    agent = Agent(
        agent_id=agent_id,
        hostname="proc.local",
        ip_address="192.168.1.50",
        status=HealthStatus.UNKNOWN,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _register_root(db, agent, config=None):
    config = config or {
        "name": "Root",
        "tasks": [
            {"name": "t1", "type": "command", "command": "true"},
        ],
    }
    system = SystemManager.register_system(
        system_id="root-sys",
        name="Root",
        description=None,
        config=config,
        db=db,
        agent_id=agent.id,
    )
    return system


def _find_task(db, system_id, task_id):
    return (
        db.query(Task)
        .join(System, System.id == Task.system_id)
        .filter(System.system_id == system_id, Task.task_id == task_id)
        .first()
    )


def _find_system(db, system_id):
    return db.query(System).filter(System.system_id == system_id).first()


class TestProcessStatusReport:
    """process_status_report against registered systems"""

    def test_records_task_results(self, test_db):
        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        report = HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "name": "Root",
                "status": "UP",
                "tasks": [
                    {
                        "task_id": "t1",
                        "name": "t1",
                        "type": "command",
                        "status": "UP",
                        "duration_ms": 12.5,
                    },
                ],
                "dependencies": [],
            },
            db=db,
        )

        assert report.id is not None
        assert report.system_id is not None

        task = _find_task(db, "root-sys", "t1")
        assert task.status == HealthStatus.UP
        assert task.last_duration_ms == 12.5

        result = db.query(TaskResult).filter(TaskResult.task_id == task.id).first()
        assert result is not None
        assert result.status == HealthStatus.UP

    def test_nested_report_creates_child_system_and_link(self, test_db):
        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "name": "Root",
                "status": "DOWN",
                "tasks": [
                    {"task_id": "t1", "name": "t1", "type": "command", "status": "UP"},
                ],
                "dependencies": [
                    {
                        "system_id": "db-layer",
                        "name": "DB Layer",
                        "status": "DOWN",
                        "tasks": [
                            {
                                "task_id": "pg",
                                "name": "pg",
                                "type": "tcp",
                                "status": "DOWN",
                                "error": "connection refused",
                            },
                        ],
                        "dependencies": [],
                    },
                ],
            },
            db=db,
        )

        # Child system auto-created (parent-prefixed id) with its task
        child = _find_system(db, "root-sys/db-layer")
        assert child is not None
        pg_task = _find_task(db, "root-sys/db-layer", "pg")
        assert pg_task is not None
        assert pg_task.status == HealthStatus.DOWN
        assert pg_task.last_error == "connection refused"

        # Parent -> child dependency link exists
        root = _find_system(db, "root-sys")
        link = (
            db.query(SystemDependency)
            .filter(
                SystemDependency.parent_system_id == root.id,
                SystemDependency.child_system_id == child.id,
            )
            .first()
        )
        assert link is not None

    def test_roll_up_down_propagates_to_root(self, test_db):
        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "status": "UP",
                "tasks": [
                    {"task_id": "t1", "name": "t1", "type": "command", "status": "UP"},
                ],
                "dependencies": [
                    {
                        "system_id": "child",
                        "name": "Child",
                        "status": "DOWN",
                        "tasks": [
                            {
                                "task_id": "leaf",
                                "name": "leaf",
                                "type": "command",
                                "status": "DOWN",
                            },
                        ],
                    },
                ],
            },
            db=db,
        )

        db.expire_all()
        root = _find_system(db, "root-sys")
        # Root's own task is UP but a DOWN child makes the root DOWN
        assert root.status == HealthStatus.DOWN

    def test_all_up_roll_up(self, test_db):
        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "status": "UP",
                "tasks": [
                    {"task_id": "t1", "name": "t1", "type": "command", "status": "UP"},
                ],
                "dependencies": [
                    {
                        "system_id": "child",
                        "name": "Child",
                        "status": "UP",
                        "tasks": [
                            {"task_id": "leaf", "name": "leaf", "type": "command", "status": "UP"},
                        ],
                    },
                ],
            },
            db=db,
        )

        db.expire_all()
        root = _find_system(db, "root-sys")
        assert root.status == HealthStatus.UP

    def test_unknown_system_raises(self, test_db):
        db = test_db
        agent = _make_agent(db)

        with pytest.raises(ValueError):
            HealthCheckProcessor.process_status_report(
                agent_id=agent.id,
                system_id="does-not-exist",
                report_timestamp=datetime.now(timezone.utc),
                report_data={"system_id": "does-not-exist", "tasks": []},
                db=db,
            )

    def test_self_referencing_dependency_link_skipped(self, test_db):
        """A report listing the root as its own dependency creates no self-link

        Regression: the auto-created self-link made recursive evaluation
        loop forever (RecursionError / 500 on every tree request).
        """
        from server.app.services.status_evaluator import StatusEvaluator

        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "tasks": [
                    {"task_id": "t1", "name": "t1", "type": "command", "status": "UP"},
                ],
                "dependencies": [
                    {"system_id": "root-sys", "name": "Self", "status": "UP", "tasks": []},
                ],
            },
            db=db,
        )

        root = _find_system(db, "root-sys")
        links = (
            db.query(SystemDependency)
            .filter(
                SystemDependency.parent_system_id == root.id,
                SystemDependency.child_system_id == root.id,
            )
            .all()
        )
        assert links == []

        # Evaluation and tree building remain safe
        assert StatusEvaluator.evaluate_system_status(root, db) in (
            HealthStatus.UP,
            HealthStatus.UNKNOWN,
        )
        assert StatusEvaluator.get_system_tree(root, db)["system_id"] == "root-sys"

    def test_ancestor_dependency_link_skipped(self, test_db):
        """A child report referencing its parent as a dependency creates no back-link"""
        from server.app.services.status_evaluator import StatusEvaluator

        db = test_db
        agent = _make_agent(db)
        _register_root(
            db,
            agent,
            config={
                "name": "Root",
                "tasks": [{"name": "t1", "type": "command", "command": "true"}],
                "dependencies": [
                    {
                        "name": "Child",
                        "tasks": [{"name": "c1", "type": "command", "command": "true"}],
                    }
                ],
            },
        )
        child = _find_system(db, "root-sys/child")
        assert child is not None

        # The child "reports" that it depends on its own parent
        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys/child",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "child",
                "name": "Child",
                "tasks": [
                    {"task_id": "c1", "name": "c1", "type": "command", "status": "UP"},
                ],
                "dependencies": [
                    {"system_id": "root-sys", "name": "Root", "status": "UP", "tasks": []},
                ],
            },
            db=db,
        )

        root = _find_system(db, "root-sys")
        back_links = (
            db.query(SystemDependency)
            .filter(
                SystemDependency.parent_system_id == child.id,
                SystemDependency.child_system_id == root.id,
            )
            .all()
        )
        assert back_links == []

        # The tree still evaluates without looping
        tree = StatusEvaluator.get_system_tree(root, db)
        assert tree["system_id"] == "root-sys"
        assert len(tree["dependencies"]) == 1

    def test_report_for_unknown_agent_rejected_by_api(self, client):
        """The router rejects status reports from unregistered agents (404)"""
        response = client.post(
            "/api/v1/status",
            json={
                "agent_id": "ghost-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {"system_id": "nope", "tasks": []},
            },
        )
        assert response.status_code == 404

    def test_report_for_unknown_system_rejected_by_api(self, client):
        """A registered agent reporting an unknown system gets 400"""
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "known-agent",
                "hostname": "known.local",
                "ip_address": "192.168.1.60",
            },
        )
        response = client.post(
            "/api/v1/status",
            json={
                "agent_id": "known-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {"system_id": "ghost-system", "tasks": []},
            },
        )
        assert response.status_code == 400

    def test_task_status_uses_latest_result(self, test_db):
        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        # First report: DOWN
        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "tasks": [
                    {
                        "task_id": "t1",
                        "name": "t1",
                        "type": "command",
                        "status": "DOWN",
                        "error": "first failure",
                    },
                ],
            },
            db=db,
        )
        task = _find_task(db, "root-sys", "t1")
        assert task.status == HealthStatus.DOWN

        # Second report: UP
        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "tasks": [
                    {"task_id": "t1", "name": "t1", "type": "command", "status": "UP"},
                ],
            },
            db=db,
        )
        db.expire_all()
        task = _find_task(db, "root-sys", "t1")
        assert task.status == HealthStatus.UP

        # Only the latest result decides
        results = (
            db.query(TaskResult)
            .filter(TaskResult.task_id == task.id)
            .order_by(TaskResult.created_at.desc())
            .all()
        )
        assert len(results) == 2
        assert results[0].status == HealthStatus.UP


class TestHistory:
    """get_system_history / get_task_history"""

    def test_system_history(self, test_db):
        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        now = datetime.now(timezone.utc)
        for _ in range(3):
            HealthCheckProcessor.process_status_report(
                agent_id=agent.id,
                system_id="root-sys",
                report_timestamp=now,
                report_data={"system_id": "root-sys", "tasks": []},
                db=db,
            )

        reports = HealthCheckProcessor.get_system_history("root-sys", db)
        assert len(reports) == 3
        assert all(isinstance(r, StatusReport) for r in reports)

        limited = HealthCheckProcessor.get_system_history("root-sys", db, limit=2)
        assert len(limited) == 2

    def test_system_history_empty(self, test_db):
        db = test_db
        assert HealthCheckProcessor.get_system_history("missing-system", db) == []

    def test_task_history(self, test_db):
        db = test_db
        agent = _make_agent(db)
        _register_root(db, agent)

        HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id="root-sys",
            report_timestamp=datetime.now(timezone.utc),
            report_data={
                "system_id": "root-sys",
                "tasks": [
                    {"task_id": "t1", "name": "t1", "type": "command", "status": "UP"},
                ],
            },
            db=db,
        )

        results = HealthCheckProcessor.get_task_history(task_id="t1", system_id="root-sys", db=db)
        assert len(results) == 1
        assert results[0].status == HealthStatus.UP
