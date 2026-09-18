# Contributing to Recur

Thank you for your interest in contributing to Recur! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and constructive in all interactions with the community.

## How to Contribute

### Reporting Issues

1. **Check existing issues** - Search to see if your issue has already been reported
2. **Be specific** - Include:
   - Version of Recur you're using
   - Your OS and Python version
   - Steps to reproduce
   - Expected vs actual behavior
   - Error logs or stack traces

### Suggesting Enhancements

1. Check if the feature has been suggested before
2. Provide a clear description of the enhancement
3. Explain why this feature would be useful
4. Provide examples of how it would work

### Code Contributions

#### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/mvineetmenon/Recur.git
cd Recur

# Setup development environment
./scripts/dev-setup.sh

# Activate virtual environment
source venv/bin/activate
```

#### Making Changes

1. **Create a feature branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes** - Follow the code style guidelines below

3. **Write tests** - Add tests for new features
   ```bash
   # Run tests
   pytest -v server/tests/
   ```

4. **Format and lint your code**
   ```bash
   make format
   make lint
   ```

5. **Commit with clear messages**
   ```bash
   git commit -m "Add feature: description of changes"
   ```

6. **Push to your fork**
   ```bash
   git push origin feature/my-feature
   ```

7. **Create a Pull Request** - Provide clear description of changes

#### Code Style Guidelines

- **Python**: Follow PEP 8, use `black` for formatting
- **Bash**: Use `bash -n` to check syntax, follow conventions
- **SQL**: Use uppercase for keywords
- **Documentation**: Use clear, concise language

#### Running Tests

```bash
# Run all tests
make test

# Run with coverage
pytest --cov=server/app server/tests/

# Run specific test
pytest server/tests/test_routers.py::TestSystems::test_create_system -v
```

#### Code Quality

```bash
# Format code
make format

# Run linting
make lint

# Type checking (note: mypy currently reports pre-existing errors on
# SQLAlchemy 1.x-style Column definitions; see REPORT.md — keep new code clean)
mypy server/
```

## Project Structure

```
Recur/
├── server/           # Central server (FastAPI)
│   ├── app/         # Application code
│   ├── tests/       # Test suite
│   └── logs/        # Log files
├── agent/           # Health check agent
├── configs/         # Example configurations
└── scripts/         # Setup and utility scripts
```

## Key Files

- **Server Entry Point**: `server/app/main.py`
- **API Routes**: `server/app/routers/`
- **Database Models**: `server/app/models.py`
- **Business Logic**: `server/app/services/`
- **Agent**: `agent/recur_agent.py` (check executor: `agent/health_check_utils.py`)
- **Tests**: `server/tests/`

## Adding New Features

### Adding a New Health Check Type

1. **Update YAML validation** in `server/app/utils/yaml_loader.py`
2. **Add check method** to `agent/health_check_utils.py`
3. **Add tests** in `server/tests/`
4. **Update documentation** in `README.md`

Example:

```python
# In health_check_utils.py
def _check_dns(self, task: Dict[str, Any], timeout: float) -> tuple[str, str]:
    """DNS resolution check"""
    hostname = task.get("hostname")
    expected_ip = task.get("expected_ip")
    
    try:
        import socket
        ip = socket.gethostbyname(hostname)
        if expected_ip and ip != expected_ip:
            return "DOWN", f"IP mismatch: {ip} != {expected_ip}"
        return "UP", ""
    except Exception as e:
        return "DOWN", str(e)
```

### Adding New API Endpoints

1. Create route in `server/app/routers/`
2. Add Pydantic schemas in `server/app/schemas.py`
3. Implement business logic in `server/app/services/`
4. Add tests in `server/tests/`
5. Document in README.md

## Documentation

- Update `README.md` for user-facing changes
- Update `QUICK_START.md` for setup changes
- Add docstrings to new functions/classes
- Update API examples in `scripts/api-examples.sh`

## Commit Message Guidelines

Format: `<type>: <subject>`

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `style`: Code style (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Example:
```
feat: add DNS health check type

- Implement DNS resolution checking
- Add DNS task type validation
- Include comprehensive tests
- Update documentation
```

## Pull Request Process

1. **Update** the README and other docs with details of changes
2. **Add tests** for new features
3. **Follow** the code style guidelines
4. **Include** a clear description of the changes
5. **Link** related issues if applicable
6. **Ensure** all tests pass locally

## Questions?

- Check existing issues and discussions
- Open a new discussion for questions
- Reach out on GitHub

## License

By contributing to Recur, you agree that your contributions will be licensed under the same MIT license as the project.

---

Thank you for contributing to make Recur better! 🚀
