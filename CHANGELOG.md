# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.0.0 (2025-07-03)

### Features
- Initial release with core functionality
- Memory leak detection using linear regression analysis
- Two operation modes: Protection (default) and Hunting
- Docker container monitoring support
- Adaptive heuristics based on system configuration
- Dynamic parameter adjustment under memory pressure
- Predictive killing to prevent system crashes
- iTerm2 sandboxing for safe testing
- Native macOS notifications for recurring issues
- LaunchDaemon support for automatic startup
- Comprehensive logging system
- Extensive process whitelist for system safety

### Technical
- Python 3.10+ support
- Uses psutil for cross-platform process monitoring
- Semantic versioning
- Comprehensive CLI with detailed help
- uv package manager integration
- Type hints throughout codebase

### Documentation
- Comprehensive README with examples
- Security policy and guidelines
- Contributing guidelines
- Installation instructions
- API documentation in code

### Known Issues
- Alpha software - not production ready
- Requires root/sudo access
- macOS only (optimized for Sonoma 14.x)
