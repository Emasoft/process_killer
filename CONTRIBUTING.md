# Contributing to Process Killer

Thank you for your interest in contributing to Process Killer! This document provides guidelines and instructions for contributing.

## ⚠️ Important Notice

This project is in **EARLY ALPHA** stage. Expect breaking changes and instability.

## Code of Conduct

By participating in this project, you agree to abide by our Code of Conduct:

- Be respectful and inclusive
- Welcome newcomers and help them get started
- Focus on constructive criticism
- Respect differing viewpoints and experiences

## How to Contribute

### Reporting Bugs

Before creating bug reports, please check existing issues. When creating a bug report, include:

1. **Clear title and description**
2. **Steps to reproduce**
3. **Expected behavior**
4. **Actual behavior**
5. **System information** (macOS version, Python version, RAM size)
6. **Relevant logs** from `~/memory_leak_killer.log`

### Suggesting Enhancements

Enhancement suggestions are welcome! Please:

1. **Check existing issues** first
2. **Provide a clear use case**
3. **Explain the expected behavior**
4. **Consider backwards compatibility**

### Pull Requests

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Make your changes**
4. **Run pre-commit hooks** (automatic)
5. **Test thoroughly**
6. **Commit with clear messages**
7. **Push to your branch**
8. **Open a Pull Request**

## Development Setup

### Prerequisites

- macOS (Sonoma 14.x or later recommended)
- Python 3.10+ (3.12 recommended)
- uv (for dependency management)
- Docker (optional, for container monitoring features)

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/Emasoft/process_killer.git
   cd process_killer
   ```

2. **Install uv** (if not already installed)
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Install dependencies**
   ```bash
   uv sync
   ```

4. **Install pre-commit hooks**
   ```bash
   uv run pre-commit install
   uv run pre-commit install --hook-type pre-push
   ```

### Running Tests

```bash
# Type checking
uv run mypy process_killer.py

# Linting
uv run ruff check .
uv run black --check .

# Import test
uv run python -c "import process_killer; print(process_killer.__version__)"

# CLI test
uv run python process_killer.py --help
```

### Security Checks

Before submitting, ensure:

1. **No secrets in code** (TruffleHog will check automatically)
2. **No hardcoded paths** (except system paths)
3. **Proper error handling**
4. **Safe subprocess calls**

## Coding Standards

### Python Style

- Follow PEP 8
- Use Black for formatting (automatic via pre-commit)
- Use Ruff for linting (automatic via pre-commit)
- Type hints are required for all functions

### Commit Messages

Follow conventional commits:

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Test additions/changes
- `chore`: Maintenance tasks

### Documentation

- Update README.md for user-facing changes
- Update CLAUDE.md for AI assistant guidance
- Add docstrings to all functions
- Include usage examples

## Testing Guidelines

### Manual Testing

Test your changes with:

1. **Protection mode** (default)
   ```bash
   sudo python process_killer.py
   ```

2. **Hunting mode** (aggressive)
   ```bash
   sudo python process_killer.py --hunting-mode
   ```

3. **iTerm-only mode** (safe testing)
   ```bash
   sudo python process_killer.py --iterm-only
   ```

4. **Docker mode** (if applicable)
   ```bash
   sudo python process_killer.py --docker
   ```

### Creating Test Scenarios

Use memory-consuming test scripts:

```python
# memory_hog.py - Test script for leak detection
import time
data = []
while True:
    data.append("x" * 1024 * 1024)  # 1MB per iteration
    time.sleep(1)
```

## Release Process

1. **Version bump** in `_version.py`
2. **Update CHANGELOG.md**
3. **Create git tag** (`git tag -a v1.0.1 -m "Release v1.0.1"`)
4. **Push tag** (`git push origin v1.0.1`)
5. **GitHub Actions** will handle the rest

## Getting Help

- Check existing issues and discussions
- Read the documentation thoroughly
- Ask in discussions for general questions
- Create issues for bugs and features

## Recognition

Contributors will be recognized in:
- CONTRIBUTORS.md file
- Release notes
- Project README

Thank you for contributing to make Process Killer better! 🎉
