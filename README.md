# Process Killer

<div align="center">

[![CI/CD Pipeline](https://github.com/Emasoft/process_killer/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Emasoft/process_killer/actions/workflows/ci.yml)
[![Security Scan](https://img.shields.io/badge/security-TruffleHog%20v3-green)](https://github.com/trufflesecurity/trufflehog)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)](https://www.apple.com/macos/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Development Status](https://img.shields.io/badge/status-alpha-red)](https://github.com/Emasoft/process_killer)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

</div>

---

## WARNING - ALPHA SOFTWARE

> **This software is in EARLY ALPHA stage and is NOT READY FOR PRODUCTION USE.**
>
> Use at your own risk. This tool can terminate system processes and Docker containers.
> Always test in a safe environment first.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
  - [From Source](#from-source)
  - [System Requirements](#system-requirements)
- [Usage](#usage)
  - [Basic Usage](#basic-usage)
  - [Operation Modes](#operation-modes)
  - [Command Line Options](#command-line-options)
  - [Examples](#examples)
- [How It Works](#how-it-works)
  - [Memory Leak Detection](#memory-leak-detection)
  - [Memory Pressure Relief](#memory-pressure-relief)
  - [Adaptive Behavior](#adaptive-behavior)
- [Docker Support](#docker-support)
- [Daemon Installation](#daemon-installation)
- [Configuration](#configuration)
- [Security](#security)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Overview

Process Killer is a macOS memory management watchdog that monitors and kills processes exhibiting memory leaks or causing high memory pressure. It uses linear regression analysis to detect persistent memory leaks and implements a scoring system for intelligent process termination.

## Features

- **Memory Leak Detection**: Linear regression analysis to identify processes with persistent memory growth
- **Two Operation Modes**:
  - **Protection Mode** (default): Only kills leaks when system RAM is critical (>=85%)
  - **Hunting Mode**: Aggressively kills all detected memory leaks
- **Docker Container Support**: Monitor and kill containers with memory leaks
- **Adaptive Heuristics**: Automatically adjusts parameters based on system configuration
- **Predictive Killing**: Terminates processes before they can crash the system
- **Native macOS Notifications**: Alerts for recurring problematic processes
- **iTerm2 Sandboxing**: Option to monitor only terminal-spawned processes
- **Comprehensive Logging**: All actions logged to `~/memory_leak_killer.log`
- **LaunchDaemon Support**: Can run automatically at system startup

## Quick Start

```bash
# Clone the repository
git clone https://github.com/Emasoft/process_killer.git
cd process_killer

# Install dependencies
uv sync

# Run with default settings (protection mode)
sudo uv run python process_killer.py

# Run in hunting mode (kills all leaks)
sudo uv run python process_killer.py --hunting-mode
```

## Installation

### From Source

1. **Prerequisites**:
   - macOS (Sonoma 14.x or later recommended)
   - Python 3.10+ (3.12 recommended)
   - [uv](https://github.com/astral-sh/uv) for dependency management
   - Docker CLI (optional, for container monitoring)

2. **Clone and Setup**:
   ```bash
   # Clone the repository
   git clone https://github.com/Emasoft/process_killer.git
   cd process_killer

   # Install uv if not already installed
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Install dependencies
   uv sync

   # Install pre-commit hooks (for development)
   uv run pre-commit install
   ```

3. **Verify Installation**:
   ```bash
   uv run python process_killer.py --version
   # Output: Process Killer v1.0.0
   ```

### System Requirements

- **Operating System**: macOS 10.15+ (optimized for Sonoma 14.x)
- **Python**: 3.10, 3.11, or 3.12
- **Memory**: Minimum 8GB RAM (16GB+ recommended)
- **Permissions**: Requires sudo/root access to monitor and kill processes

## Usage

### Basic Usage

```bash
# Run with default protection mode
sudo uv run python process_killer.py

# Or if installed globally
sudo process-killer
```

### Operation Modes

1. **Protection Mode** (default):
   - Only kills processes when system RAM usage >= 85%
   - Safe for production environments
   - Prevents system instability from memory pressure

2. **Hunting Mode**:
   - Kills ALL detected memory leaks immediately
   - Useful for development and testing
   - More aggressive leak prevention

### Command Line Options

```
usage: process_killer.py [-h] [--version]
                         [--install-daemon | --uninstall-daemon | --start | --stop]
                         [--interval INTERVAL] [--history HISTORY]
                         [--growth GROWTH] [--slope SLOPE] [--conf CONF]
                         [--grace GRACE] [--cool COOL] [--high HIGH]
                         [--low LOW] [--recent RECENT] [--child-wt CHILD_WT]
                         [--notify-threshold NOTIFY_THRESHOLD]
                         [--notify-window NOTIFY_WINDOW] [--iterm-only]
                         [--docker] [--protection-mode | --hunting-mode]
                         [--leak-threshold LEAK_THRESHOLD]
```

#### Key Options:

- `--interval INTERVAL`: Sampling interval in seconds (default: 5)
- `--history HISTORY`: Number of samples in regression window (default: 6)
- `--growth GROWTH`: Minimum net memory growth (MB) to consider a leak (default: 50)
- `--slope SLOPE`: Minimum growth rate (MB/min) to consider a leak (default: 20)
- `--conf CONF`: Consecutive confirmations before killing (default: 2)
- `--grace GRACE`: Seconds to ignore new processes (default: 60)
- `--cool COOL`: Cooldown after a process plateaus (default: 300)
- `--high HIGH`: RAM % to trigger pressure relief (default: 90)
- `--low LOW`: RAM % to stop pressure relief (default: 85)
- `--docker`: Enable Docker container monitoring
- `--iterm-only`: Only monitor iTerm2-spawned processes
- `--protection-mode`: Only kill when RAM is high (default)
- `--hunting-mode`: Kill all detected leaks
- `--leak-threshold`: Min RAM % for protection mode (default: 85)

### Examples

```bash
# 1. Default protection mode (safe for production)
sudo process-killer

# 2. Aggressive leak hunting (for development)
sudo process-killer --hunting-mode --slope 10 --growth 20

# 3. Custom thresholds for sensitive systems
sudo process-killer --high 80 --low 70 --leak-threshold 75

# 4. Monitor only terminal-spawned processes
sudo process-killer --iterm-only --hunting-mode

# 5. Include Docker container monitoring
sudo process-killer --docker --hunting-mode

# 6. More aggressive leak detection
sudo process-killer --slope 30 --growth 150 --history 10

# 7. Install as system daemon
sudo process-killer --install-daemon

# 8. Quick 15-minute development session
sudo process-killer --iterm-only --hunting-mode --notify-threshold 5
```

## How It Works

### Memory Leak Detection

A process is considered leaking when:
1. Its RSS (Resident Set Size) growth follows an upward slope >= `--slope` MB/min
2. Net growth is >= `--growth` MB within the sliding window
3. This pattern persists for `--conf` consecutive windows

### Memory Pressure Relief

When system RAM exceeds `--high` threshold:
1. All non-whitelisted processes are scored based on:
   - Leak confirmation status
   - Memory growth slope
   - Process age (younger = more suspicious)
   - Number of child processes
   - Current memory usage
2. Highest-scoring processes are terminated until RAM drops below `--low`

### Adaptive Behavior

The tool automatically adjusts based on:
- **System Configuration**:
  - 8GB systems: Aggressive parameters
  - 16GB systems: Moderate parameters
  - 64GB+ systems: Relaxed parameters
- **Memory Pressure**: Parameters tighten as RAM usage increases
- **Predictive Analysis**: Kills processes that would crash the system before next check

## Docker Support

Monitor and manage Docker containers:

```bash
# Enable Docker monitoring
sudo process-killer --docker

# Aggressive Docker leak hunting
sudo process-killer --docker --hunting-mode --slope 15

# Docker + iTerm2 only
sudo process-killer --docker --iterm-only
```

Requirements:
- Docker CLI must be installed and accessible
- Containers are monitored using the same leak detection algorithms
- Containers are gracefully stopped with `docker stop`

## Daemon Installation

Run Process Killer automatically at system startup:

```bash
# Install as LaunchDaemon
sudo process-killer --install-daemon

# Control the daemon
sudo process-killer --start   # Start the daemon
sudo process-killer --stop    # Stop the daemon

# Uninstall daemon
sudo process-killer --uninstall-daemon
```

The daemon:
- Runs with default protection mode settings
- Logs to `~/memory_leak_killer.log`
- Starts automatically at boot
- Can be controlled via `launchctl`

## Configuration

### Whitelisted Processes

The following critical system processes are never killed:
- kernel_task, launchd, loginwindow
- WindowServer, coreservicesd, systemd
- mds, mdworker, Spotlight
- Finder, Dock, SystemUIServer
- And many more system-critical processes

### Log File

All actions are logged to: `~/memory_leak_killer.log`

Format:
```
[2024-01-07 14:32:15] Killed PID 12345 (leaky_app) reason=leak rss=2048.5MB slope≈35.2MB/min
[2024-01-07 14:33:20] Protection mode: will only kill leaks when RAM >= 85%
```

## Security

This project implements comprehensive security measures:

1. **Secret Scanning**: TruffleHog v3 scans all commits
2. **Pre-commit Hooks**: Security checks before every commit
3. **CI/CD Security**: Automated scanning in GitHub Actions
4. **Safe Defaults**: Protection mode prevents aggressive killing
5. **Audit Logging**: All actions are logged

See [SECURITY.md](SECURITY.md) for details.

## Development

### Setup Development Environment

```bash
# Clone and setup
git clone https://github.com/Emasoft/process_killer.git
cd process_killer

# Install with dev dependencies
uv sync
uv pip install -e ".[dev]"

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run mypy process_killer.py
uv run ruff check .
uv run black --check .
```

### Testing Memory Leaks

Create a test script:
```python
# memory_leak_test.py
import time
data = []
while True:
    data.append("x" * 1024 * 1024)  # 1MB per iteration
    time.sleep(1)
```

Run Process Killer in another terminal:
```bash
sudo process-killer --iterm-only --hunting-mode
```

## Versioning

This project uses [Semantic Versioning](https://semver.org/) with automatic version bumping based on commit messages:

- **MAJOR** version (X.0.0): Breaking changes
  - Commits with `BREAKING CHANGE:`, `breaking:`, `break:`, or `BREAKING:` prefix
- **MINOR** version (0.X.0): New features (backwards compatible)
  - Commits with `feat:` prefix
- **PATCH** version (0.0.X): Bug fixes and minor changes
  - Commits with `fix:`, `perf:`, `refactor:`, `style:`, `docs:`, `test:`, `build:`, `ci:`, or `chore:` prefix

### Commit Message Format

Use conventional commits format:
```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

Examples:
- `feat: add memory threshold configuration`
- `fix: correct Docker container detection`
- `breaking: change CLI argument structure`

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Key points:
- Fork and create feature branches
- Use conventional commit messages for automatic versioning
- Run pre-commit hooks
- Add tests for new features
- Update documentation
- Follow Python code style (Ruff with line-length=320)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**WARNING: This is ALPHA software. Use at your own risk!**

Made with care for the macOS community

[Report Bug](https://github.com/Emasoft/process_killer/issues) · [Request Feature](https://github.com/Emasoft/process_killer/issues)

</div>
