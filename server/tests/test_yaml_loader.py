"""
Tests for YAML configuration loader
"""

import pytest
import tempfile
from pathlib import Path

from server.app.utils.yaml_loader import (
    YAMLConfigError,
    load_yaml_file,
    validate_system_config,
    validate_task_type_config,
)


class TestYAMLLoader:
    """Tests for YAML loading functionality"""
    
    def test_load_valid_yaml(self):
        """Test loading a valid YAML file"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
system:
  name: Test System
  tasks:
    - name: test
      type: http
      url: http://localhost/health
""")
            f.flush()
            
            config = load_yaml_file(f.name)
            
            assert "system" in config
            assert config["system"]["name"] == "Test System"
            
            Path(f.name).unlink()
    
    def test_load_nonexistent_file(self):
        """Test loading a non-existent file"""
        with pytest.raises(YAMLConfigError):
            load_yaml_file("/nonexistent/file.yaml")
    
    def test_validate_system_config_valid(self):
        """Test validation of valid system config"""
        config = {
            "system": {
                "name": "Test",
                "tasks": [
                    {
                        "name": "test",
                        "type": "http",
                        "url": "http://localhost/health",
                    }
                ]
            }
        }
        
        # Should not raise
        validate_system_config(config)
    
    def test_validate_system_config_missing_name(self):
        """Test validation fails without system name"""
        config = {
            "system": {
                "tasks": []
            }
        }
        
        with pytest.raises(YAMLConfigError):
            validate_system_config(config)
    
    def test_validate_system_config_no_system_key(self):
        """Test validation fails without system key"""
        config = {"name": "Test"}
        
        with pytest.raises(YAMLConfigError):
            validate_system_config(config)
    
    def test_validate_task_http(self):
        """Test HTTP task validation"""
        task = {
            "type": "http",
            "url": "http://localhost/health",
            "expected_status": 200,
        }
        
        # Should not raise
        validate_task_type_config(task)
    
    def test_validate_task_http_missing_url(self):
        """Test HTTP task validation fails without URL"""
        task = {
            "type": "http",
            "expected_status": 200,
        }
        
        with pytest.raises(YAMLConfigError):
            validate_task_type_config(task)
    
    def test_validate_task_tcp(self):
        """Test TCP task validation"""
        task = {
            "type": "tcp",
            "host": "localhost",
            "port": 5432,
        }
        
        # Should not raise
        validate_task_type_config(task)
    
    def test_validate_task_command(self):
        """Test command task validation"""
        task = {
            "type": "command",
            "command": "test -f /tmp/file",
        }
        
        # Should not raise
        validate_task_type_config(task)
    
    def test_validate_task_invalid_type(self):
        """Test validation fails for invalid task type"""
        config = {
            "system": {
                "name": "Test",
                "tasks": [
                    {
                        "name": "test",
                        "type": "invalid_type",
                    }
                ]
            }
        }
        
        with pytest.raises(YAMLConfigError):
            validate_system_config(config)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
