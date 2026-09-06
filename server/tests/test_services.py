"""
Tests for Recur server service layer
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server.app.database import Base
from server.app.models import Agent, HealthStatus, System, Task
from server.app.services.status_evaluator import StatusEvaluator
from server.app.services.system_manager import SystemManager


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def test_db():
    """Create test database"""
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    yield TestingSessionLocal()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def agent_setup(test_db):
    """Create test agent"""
    agent = Agent(
        agent_id="test-agent",
        hostname="test.local",
        ip_address="192.168.1.100",
        status=HealthStatus.UP,
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)
    return agent


class TestSystemManager:
    """Tests for SystemManager service"""

    def test_register_system(self, test_db, agent_setup):
        """Test system registration"""
        manager = SystemManager(test_db)
        
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
        
        system = manager.register_system(
            system_id="test-sys",
            name="Test System",
            config=config,
            agent_id="test-agent",
        )
        
        assert system is not None
        assert system.system_id == "test-sys"
        assert system.name == "Test System"

    def test_register_system_duplicate(self, test_db, agent_setup):
        """Test registering duplicate system updates it"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test System",
            "tasks": [],
        }
        
        # Register first time
        system1 = manager.register_system(
            system_id="test-sys-dup",
            name="Test System",
            config=config,
            agent_id="test-agent",
        )
        
        # Register again
        system2 = manager.register_system(
            system_id="test-sys-dup",
            name="Updated System",
            config=config,
            agent_id="test-agent",
        )
        
        assert system1.id == system2.id
        assert system2.name == "Updated System"

    def test_get_system(self, test_db, agent_setup):
        """Test getting system"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        manager.register_system(
            system_id="test-get",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        system = manager.get_system("test-get")
        
        assert system is not None
        assert system.system_id == "test-get"

    def test_get_nonexistent_system(self, test_db):
        """Test getting nonexistent system"""
        manager = SystemManager(test_db)
        system = manager.get_system("nonexistent")
        assert system is None

    def test_list_systems(self, test_db, agent_setup):
        """Test listing systems"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        for i in range(3):
            manager.register_system(
                system_id=f"test-sys-{i}",
                name=f"Test System {i}",
                config=config,
                agent_id="test-agent",
            )
        
        systems = manager.list_systems()
        assert len(systems) >= 3

    def test_list_systems_pagination(self, test_db, agent_setup):
        """Test system listing with pagination"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        for i in range(5):
            manager.register_system(
                system_id=f"test-page-{i}",
                name=f"Test {i}",
                config=config,
                agent_id="test-agent",
            )
        
        systems = manager.list_systems(skip=1, limit=2)
        assert len(systems) <= 2

    def test_update_system(self, test_db, agent_setup):
        """Test updating system"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Original",
            "tasks": [],
        }
        
        manager.register_system(
            system_id="test-update",
            name="Original",
            config=config,
            agent_id="test-agent",
        )
        
        new_config = {
            "name": "Updated",
            "tasks": [],
        }
        
        updated = manager.update_system(
            system_id="test-update",
            name="Updated Name",
            config=new_config,
        )
        
        assert updated.name == "Updated Name"

    def test_delete_system(self, test_db, agent_setup):
        """Test deleting system"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        manager.register_system(
            system_id="test-del",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        manager.delete_system("test-del")
        
        system = manager.get_system("test-del")
        assert system is None

    def test_create_tasks_from_config(self, test_db, agent_setup):
        """Test task creation from config"""
        manager = SystemManager(test_db)
        
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
        
        system = manager.register_system(
            system_id="test-tasks",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        tasks = test_db.query(Task).filter(Task.system_id == system.id).all()
        assert len(tasks) == 2
        assert tasks[0].task_type == "http"
        assert tasks[1].task_type == "tcp"


class TestStatusEvaluator:
    """Tests for StatusEvaluator service"""

    def test_evaluate_all_tasks_up(self, test_db, agent_setup):
        """Test evaluation when all tasks are UP"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "check1",
                    "type": "http",
                    "url": "http://localhost/health",
                    "expected_status": 200,
                },
            ],
        }
        
        system = manager.register_system(
            system_id="eval-up",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        # Mark task as UP
        task = test_db.query(Task).filter(Task.system_id == system.id).first()
        task.status = HealthStatus.UP
        test_db.commit()
        
        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        
        assert status == HealthStatus.UP

    def test_evaluate_failed_task(self, test_db, agent_setup):
        """Test evaluation when task is DOWN"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "check1",
                    "type": "http",
                    "url": "http://localhost/health",
                    "expected_status": 200,
                },
            ],
        }
        
        system = manager.register_system(
            system_id="eval-down",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        # Mark task as DOWN
        task = test_db.query(Task).filter(Task.system_id == system.id).first()
        task.status = HealthStatus.DOWN
        test_db.commit()
        
        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        
        assert status == HealthStatus.DOWN

    def test_evaluate_unknown_status(self, test_db, agent_setup):
        """Test evaluation with UNKNOWN status"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "check1",
                    "type": "http",
                    "url": "http://localhost/health",
                    "expected_status": 200,
                },
            ],
        }
        
        system = manager.register_system(
            system_id="eval-unknown",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        # Task status defaults to UNKNOWN
        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        
        assert status == HealthStatus.UNKNOWN

    def test_evaluate_mixed_status(self, test_db, agent_setup):
        """Test evaluation with mixed task statuses"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "check1",
                    "type": "http",
                    "url": "http://localhost/health",
                    "expected_status": 200,
                },
                {
                    "name": "check2",
                    "type": "tcp",
                    "host": "localhost",
                    "port": 5432,
                },
            ],
        }
        
        system = manager.register_system(
            system_id="eval-mixed",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        tasks = test_db.query(Task).filter(Task.system_id == system.id).all()
        tasks[0].status = HealthStatus.UP
        tasks[1].status = HealthStatus.DOWN
        test_db.commit()
        
        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        
        # Should be DOWN because one task is DOWN
        assert status == HealthStatus.DOWN

    def test_get_system_tree(self, test_db, agent_setup):
        """Test getting system with full tree info"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "check1",
                    "type": "http",
                    "url": "http://localhost/health",
                    "expected_status": 200,
                },
            ],
        }
        
        system = manager.register_system(
            system_id="tree-test",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        evaluator = StatusEvaluator()
        tree = evaluator.get_system_tree(system, test_db)
        
        assert tree is not None
        assert tree["system_id"] == "tree-test"
        assert "tasks" in tree
        assert "dependencies" in tree

    def test_get_system_health_summary(self, test_db, agent_setup):
        """Test getting system health summary"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        system = manager.register_system(
            system_id="health-test",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        evaluator = StatusEvaluator()
        summary = evaluator.get_system_health_summary(system, test_db)
        
        assert summary is not None
        assert "status" in summary
        assert "task_count" in summary


class TestEdgeCases:
    """Tests for edge cases and error conditions"""

    def test_system_without_tasks(self, test_db, agent_setup):
        """Test system with no tasks"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        system = manager.register_system(
            system_id="no-tasks",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        assert system is not None
        tasks = test_db.query(Task).filter(Task.system_id == system.id).all()
        assert len(tasks) == 0

    def test_system_with_all_task_types(self, test_db, agent_setup):
        """Test system with all supported task types"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "http",
                    "type": "http",
                    "url": "http://localhost",
                    "expected_status": 200,
                },
                {
                    "name": "https",
                    "type": "https",
                    "url": "https://localhost",
                    "expected_status": 200,
                },
                {
                    "name": "tcp",
                    "type": "tcp",
                    "host": "localhost",
                    "port": 5432,
                },
                {
                    "name": "ping",
                    "type": "ping",
                    "host": "localhost",
                },
                {
                    "name": "command",
                    "type": "command",
                    "command": "echo test",
                },
            ],
        }
        
        system = manager.register_system(
            system_id="all-types",
            name="Test",
            config=config,
            agent_id="test-agent",
        )
        
        tasks = test_db.query(Task).filter(Task.system_id == system.id).all()
        assert len(tasks) == 5
        
        task_types = {task.task_type for task in tasks}
        assert "http" in task_types
        assert "tcp" in task_types
        assert "ping" in task_types
        assert "command" in task_types

    def test_invalid_task_config_missing_url(self, test_db, agent_setup):
        """Test invalid task config (HTTP without URL)"""
        manager = SystemManager(test_db)
        
        config = {
            "name": "Test",
            "tasks": [
                {
                    "name": "bad",
                    "type": "http",
                    # Missing 'url'
                },
            ],
        }
        
        with pytest.raises(Exception):
            manager.register_system(
                system_id="bad-config",
                name="Test",
                config=config,
                agent_id="test-agent",
            )

    def test_long_system_name(self, test_db, agent_setup):
        """Test system with very long name"""
        manager = SystemManager(test_db)
        
        long_name = "A" * 500
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        system = manager.register_system(
            system_id="long-name",
            name=long_name,
            config=config,
            agent_id="test-agent",
        )
        
        assert system.name == long_name

    def test_unicode_in_system_name(self, test_db, agent_setup):
        """Test system with unicode characters"""
        manager = SystemManager(test_db)
        
        unicode_name = "Test Sistema 日本語 🚀"
        config = {
            "name": "Test",
            "tasks": [],
        }
        
        system = manager.register_system(
            system_id="unicode",
            name=unicode_name,
            config=config,
            agent_id="test-agent",
        )
        
        assert system.name == unicode_name
