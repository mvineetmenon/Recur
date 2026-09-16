"""
Tests for Recur server service layer

Services expose static methods: call e.g. `SystemManager.register_system(...)`
with an explicit `db` session (the shared `test_db` fixture from conftest).
"""

import pytest

from server.app.models import Agent, HealthStatus, System, Task, TaskResult
from server.app.services.status_evaluator import StatusEvaluator
from server.app.services.system_manager import SystemManager


@pytest.fixture
def agent_setup(test_db):
    """Create a test agent and return its database id (int FK)"""
    agent = Agent(
        agent_id="test-agent",
        hostname="test.local",
        ip_address="192.168.1.100",
        status=HealthStatus.UP,
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)
    return agent.id


def _add_report(test_db, system_pk, agent_pk):
    """Create a minimal StatusReport row to anchor TaskResults"""
    from datetime import datetime

    from server.app.models import StatusReport

    report = StatusReport(
        agent_id=agent_pk,
        system_id=system_pk,
        report_timestamp=datetime.utcnow(),
        report_data={},
    )
    test_db.add(report)
    test_db.flush()
    return report.id


def _add_task_result(test_db, task, status, agent_pk, error=None):
    """Attach a TaskResult row (anchored to a StatusReport) to a task"""
    report_id = _add_report(test_db, task.system_id, agent_pk)
    result = TaskResult(
        task_id=task.id,
        status_report_id=report_id,
        status=status,
        duration_ms=5.0,
        error_message=error,
    )
    test_db.add(result)
    test_db.commit()
    test_db.refresh(task)
    return result


class TestSystemManager:
    """Tests for SystemManager service"""

    def test_register_system(self, test_db, agent_setup):
        """Test system registration"""
        config = {
            "name": "Test System",
            "tasks": [
                {
                    "name": "http_check",
                    "type": "http",
                    "url": "http://localhost/health",
                    "expected_status": 200,
                }
            ],
        }

        system = SystemManager.register_system(
            system_id="test-sys",
            name="Test System",
            description=None,
            config=config,
            db=test_db,
            agent_id=agent_setup,
        )

        assert system is not None
        assert system.system_id == "test-sys"
        assert system.name == "Test System"

    def test_register_system_duplicate_updates(self, test_db, agent_setup):
        """Test registering duplicate system updates it (idempotent)"""
        config = {"name": "Test System", "tasks": []}

        system1 = SystemManager.register_system(
            system_id="test-sys-dup",
            name="Test System",
            description=None,
            config=config,
            db=test_db,
            agent_id=agent_setup,
        )

        system2 = SystemManager.register_system(
            system_id="test-sys-dup",
            name="Updated System",
            description=None,
            config=config,
            db=test_db,
            agent_id=agent_setup,
        )

        assert system1.id == system2.id
        assert system2.name == "Updated System"

    def test_register_system_invalid_config(self, test_db, agent_setup):
        """Test invalid config (missing name) is rejected"""
        with pytest.raises(ValueError):
            SystemManager.register_system(
                system_id="bad-sys",
                name="Bad",
                description=None,
                config={"tasks": []},
                db=test_db,
                agent_id=agent_setup,
            )

    def test_register_system_unknown_agent(self, test_db):
        """Test registering with a nonexistent agent fails"""
        with pytest.raises(ValueError):
            SystemManager.register_system(
                system_id="orphan-sys",
                name="Orphan",
                description=None,
                config={"name": "Orphan", "tasks": []},
                db=test_db,
                agent_id=999999,
            )

    def test_register_system_with_dependencies(self, test_db, agent_setup):
        """Test nested dependencies register child systems and links"""
        config = {
            "name": "Parent",
            "tasks": [{"name": "p-task", "type": "http", "url": "http://x"}],
            "dependencies": [
                {
                    "name": "Child",
                    "tasks": [{"name": "c-task", "type": "tcp", "host": "x", "port": 1}],
                    "dependencies": [
                        {
                            "name": "Grandchild",
                            "tasks": [{"name": "g-task", "type": "ping", "host": "x"}],
                        }
                    ],
                }
            ],
        }

        SystemManager.register_system(
            system_id="parent",
            name="Parent",
            description=None,
            config=config,
            db=test_db,
            agent_id=agent_setup,
        )

        child = SystemManager.get_system("parent/child", test_db)
        grandchild = SystemManager.get_system("parent/child/grandchild", test_db)

        assert child is not None
        assert child.name == "Child"
        assert grandchild is not None

        # Dependency links exist at both levels
        links = test_db.query(System).filter(System.system_id == "parent").first().dependencies
        assert len(links) == 1
        assert links[0].child_system.system_id == "parent/child"
        assert len(child.dependencies) == 1
        assert child.dependencies[0].child_system.system_id == "parent/child/grandchild"

        # Child tasks were created
        child_tasks = test_db.query(Task).filter(Task.system_id == child.id).all()
        assert len(child_tasks) == 1
        assert child_tasks[0].task_type == "tcp"

    def test_register_system_dependency_idempotent(self, test_db, agent_setup):
        """Test re-registering a system with deps does not duplicate rows"""
        config = {
            "name": "Parent",
            "tasks": [],
            "dependencies": [
                {"name": "Child", "tasks": [{"name": "c-task", "type": "http", "url": "http://x"}]}
            ],
        }

        SystemManager.register_system(
            system_id="idem",
            name="Parent",
            description=None,
            config=config,
            db=test_db,
            agent_id=agent_setup,
        )
        SystemManager.register_system(
            system_id="idem",
            name="Parent2",
            description=None,
            config=config,
            db=test_db,
            agent_id=agent_setup,
        )

        children = test_db.query(System).filter(System.system_id.like("idem/%")).all()
        assert len(children) == 1
        assert children[0].name == "Child"

    def test_get_system(self, test_db, agent_setup):
        """Test getting system"""
        SystemManager.register_system(
            system_id="test-get",
            name="Test",
            description=None,
            config={"name": "Test", "tasks": []},
            db=test_db,
            agent_id=agent_setup,
        )

        system = SystemManager.get_system("test-get", test_db)

        assert system is not None
        assert system.system_id == "test-get"

    def test_get_nonexistent_system(self, test_db):
        """Test getting nonexistent system returns None"""
        system = SystemManager.get_system("nonexistent", test_db)
        assert system is None

    def test_list_systems(self, test_db, agent_setup):
        """Test listing systems returns (list, total)"""
        for i in range(3):
            SystemManager.register_system(
                system_id=f"test-sys-{i}",
                name=f"Test System {i}",
                description=None,
                config={"name": "Test", "tasks": []},
                db=test_db,
                agent_id=agent_setup,
            )

        systems, total = SystemManager.list_systems(test_db)
        assert total >= 3
        assert len(systems) >= 3

    def test_list_systems_pagination(self, test_db, agent_setup):
        """Test system listing with pagination"""
        for i in range(5):
            SystemManager.register_system(
                system_id=f"test-page-{i}",
                name=f"Test {i}",
                description=None,
                config={"name": "Test", "tasks": []},
                db=test_db,
                agent_id=agent_setup,
            )

        systems, total = SystemManager.list_systems(test_db, skip=1, limit=2)
        assert total >= 5
        assert len(systems) <= 2

    def test_update_system(self, test_db, agent_setup):
        """Test updating system name and config"""
        SystemManager.register_system(
            system_id="test-update",
            name="Original",
            description=None,
            config={"name": "Original", "tasks": []},
            db=test_db,
            agent_id=agent_setup,
        )

        updated = SystemManager.update_system(
            system_id="test-update",
            name="Updated Name",
            description=None,
            config={"name": "Updated", "tasks": []},
            db=test_db,
        )

        assert updated.name == "Updated Name"

    def test_update_system_not_found(self, test_db):
        """Test updating unknown system raises"""
        with pytest.raises(ValueError):
            SystemManager.update_system(
                system_id="ghost",
                name="X",
                description=None,
                config=None,
                db=test_db,
            )

    def test_delete_system(self, test_db, agent_setup):
        """Test deleting system removes it and its dependency links"""
        SystemManager.register_system(
            system_id="test-del",
            name="Test",
            description=None,
            config={
                "name": "Test",
                "tasks": [],
                "dependencies": [
                    {"name": "Child", "tasks": [{"name": "t", "type": "http", "url": "http://x"}]}
                ],
            },
            db=test_db,
            agent_id=agent_setup,
        )

        assert SystemManager.delete_system("test-del", test_db) is True
        assert SystemManager.get_system("test-del", test_db) is None

        from server.app.models import SystemDependency

        orphans = (
            test_db.query(SystemDependency)
            .filter(
                SystemDependency.child_system_id
                == test_db.query(System).filter(System.system_id == "test-del/child").first().id
            )
            .all()
        )
        assert orphans == []

    def test_delete_system_not_found(self, test_db):
        """Test deleting unknown system returns False"""
        assert SystemManager.delete_system("ghost", test_db) is False

    def test_delete_system_with_reports(self, test_db, agent_setup):
        """Deleting a system that has reports removes reports/results FK-safely

        Regression: StatusReport.system_id is a non-nullable FK with no
        cascade, so the delete used to raise IntegrityError (500 via API).
        """
        from datetime import datetime

        from server.app.models import StatusReport, TaskResult
        from server.app.services.health_check import HealthCheckProcessor

        SystemManager.register_system(
            system_id="del-with-reports",
            name="T",
            description=None,
            config={
                "name": "T",
                "tasks": [{"name": "t1", "type": "http", "url": "http://x"}],
            },
            db=test_db,
            agent_id=agent_setup,
        )
        HealthCheckProcessor.process_status_report(
            agent_id=agent_setup,
            system_id="del-with-reports",
            report_timestamp=datetime.utcnow(),
            report_data={
                "system_id": "del-with-reports",
                "tasks": [{"task_id": "t1", "name": "t1", "type": "http", "status": "UP"}],
            },
            db=test_db,
        )
        assert test_db.query(StatusReport).count() == 1
        assert test_db.query(TaskResult).count() == 1

        assert SystemManager.delete_system("del-with-reports", test_db) is True
        assert SystemManager.get_system("del-with-reports", test_db) is None

        # No orphaned report or result rows remain
        assert test_db.query(StatusReport).count() == 0
        assert test_db.query(TaskResult).count() == 0
        assert test_db.query(Task).count() == 0

    def test_update_system_config_with_existing_results(self, test_db, agent_setup):
        """Replacing a config with existing task results deletes tasks FK-safely

        Regression: a bulk DELETE on tasks left TaskResult rows dangling
        (or raised IntegrityError where FKs are enforced).
        """
        from datetime import datetime

        from server.app.models import TaskResult
        from server.app.services.health_check import HealthCheckProcessor

        SystemManager.register_system(
            system_id="upd-with-results",
            name="T",
            description=None,
            config={
                "name": "T",
                "tasks": [{"name": "t1", "type": "http", "url": "http://x"}],
            },
            db=test_db,
            agent_id=agent_setup,
        )
        HealthCheckProcessor.process_status_report(
            agent_id=agent_setup,
            system_id="upd-with-results",
            report_timestamp=datetime.utcnow(),
            report_data={
                "system_id": "upd-with-results",
                "tasks": [{"task_id": "t1", "name": "t1", "type": "http", "status": "UP"}],
            },
            db=test_db,
        )
        assert test_db.query(TaskResult).count() == 1

        updated = SystemManager.update_system(
            system_id="upd-with-results",
            name=None,
            description=None,
            config={
                "name": "T2",
                "tasks": [{"name": "t2", "type": "tcp", "host": "h", "port": 1}],
            },
            db=test_db,
        )

        tasks = test_db.query(Task).filter(Task.system_id == updated.id).all()
        assert {t.task_id for t in tasks} == {"t2"}
        # The old task's results were removed together with the old task
        assert test_db.query(TaskResult).count() == 0

    def test_create_tasks_from_config(self, test_db, agent_setup):
        """Test task creation from config"""
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "http_check",
                    "type": "http",
                    "url": "http://localhost/health",
                    "expected_status": 200,
                },
                {
                    "name": "tcp_check",
                    "type": "tcp",
                    "host": "localhost",
                    "port": 5432,
                },
            ],
        }

        system = SystemManager.register_system(
            system_id="test-tasks",
            name="Test",
            description=None,
            config=config,
            db=test_db,
            agent_id=agent_setup,
        )

        tasks = test_db.query(Task).filter(Task.system_id == system.id).all()
        assert len(tasks) == 2
        assert {t.task_type for t in tasks} == {"http", "tcp"}


class TestStatusEvaluator:
    """Tests for StatusEvaluator service"""

    def _make_system(self, test_db, agent_setup, system_id, task_names):
        """Create a system with tasks, return (system, tasks)"""
        system = System(
            system_id=system_id,
            agent_id=agent_setup,
            name=system_id,
            config={"name": system_id, "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        test_db.add(system)
        test_db.flush()

        tasks = []
        for name in task_names:
            task = Task(
                task_id=name,
                system_id=system.id,
                name=name,
                task_type="http",
                config={},
                status=HealthStatus.UNKNOWN,
            )
            test_db.add(task)
            tasks.append(task)
        test_db.commit()
        return system, tasks

    def test_evaluate_all_tasks_up(self, test_db, agent_setup):
        """Test evaluation when all tasks have UP results"""
        system, tasks = self._make_system(test_db, agent_setup, "eval-up", ["check1"])
        _add_task_result(test_db, tasks[0], HealthStatus.UP, agent_setup)

        status = StatusEvaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.UP

    def test_evaluate_failed_task(self, test_db, agent_setup):
        """Test evaluation when a task result is DOWN"""
        system, tasks = self._make_system(test_db, agent_setup, "eval-down", ["check1"])
        _add_task_result(test_db, tasks[0], HealthStatus.DOWN, agent_setup, "boom")

        status = StatusEvaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.DOWN

    def test_evaluate_task_without_results(self, test_db, agent_setup):
        """Test evaluation with tasks that have no results yet is UNKNOWN"""
        system, _ = self._make_system(test_db, agent_setup, "eval-unknown", ["check1"])

        status = StatusEvaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.UNKNOWN

    def test_evaluate_empty_system(self, test_db, agent_setup):
        """Test system without tasks or dependencies is UNKNOWN"""
        system = System(
            system_id="eval-empty",
            agent_id=agent_setup,
            name="Empty",
            config={"name": "Empty", "tasks": []},
            status=HealthStatus.UNKNOWN,
        )
        test_db.add(system)
        test_db.commit()

        status = StatusEvaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.UNKNOWN

    def test_evaluate_mixed_status(self, test_db, agent_setup):
        """Test one DOWN among UP tasks makes the system DOWN"""
        system, tasks = self._make_system(test_db, agent_setup, "eval-mixed", ["check1", "check2"])
        _add_task_result(test_db, tasks[0], HealthStatus.UP, agent_setup)
        _add_task_result(test_db, tasks[1], HealthStatus.DOWN, agent_setup)

        status = StatusEvaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.DOWN

    def test_evaluate_uses_latest_result(self, test_db, agent_setup):
        """Test the evaluator uses the most recent result per task"""
        system, tasks = self._make_system(test_db, agent_setup, "eval-latest", ["check1"])
        _add_task_result(test_db, tasks[0], HealthStatus.DOWN, agent_setup)
        _add_task_result(test_db, tasks[0], HealthStatus.UP, agent_setup)

        status = StatusEvaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.UP

    def test_get_system_tree(self, test_db, agent_setup):
        """Test getting system tree structure"""
        system, tasks = self._make_system(test_db, agent_setup, "tree-test", ["check1"])
        _add_task_result(test_db, tasks[0], HealthStatus.UP, agent_setup)

        tree = StatusEvaluator.get_system_tree(system, test_db)

        assert tree is not None
        assert tree["system_id"] == "tree-test"
        assert "tasks" in tree
        assert "dependencies" in tree
        assert tree["tasks"][0]["status"] == HealthStatus.UP
