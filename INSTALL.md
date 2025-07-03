# Installation Guide

## Requirements

### System Requirements
- macOS 10.15 (Catalina) or later
- Python 3.8 or later
- Administrator (sudo) access for killing processes
- Docker CLI (optional, only if using `--docker` flag)

### Python Dependencies

Install Python dependencies using pip:

```bash
pip install -r requirements.txt
```

Or install manually:

```bash
pip install psutil>=5.9.0
```

### Docker Support (Optional)

If you want to monitor Docker containers with the `--docker` flag:

1. Install Docker Desktop for Mac from https://www.docker.com/products/docker-desktop
2. Ensure Docker CLI is accessible from terminal:
   ```bash
   docker --version
   ```

## Installation Steps

1. Clone or download the repository
2. Install Python dependencies:
   ```bash
   cd PROCESS_KILLER
   pip install -r requirements.txt
   ```
3. Make the script executable:
   ```bash
   chmod +x process_killer.py
   ```
4. Test the installation:
   ```bash
   sudo ./process_killer.py --help
   ```

## Running as a System Service

To install as a LaunchDaemon that starts at boot:

```bash
sudo ./process_killer.py --install-daemon
```

To uninstall the daemon:

```bash
sudo ./process_killer.py --uninstall-daemon
```

## Troubleshooting

### "psutil not found" error
Make sure you've installed the requirements:
```bash
pip install -r requirements.txt
```

### "Docker command not found" error
Install Docker Desktop or disable Docker monitoring by not using the `--docker` flag.

### Permission denied
The script requires sudo privileges to monitor and kill processes:
```bash
sudo ./process_killer.py
```

### Python version issues
Ensure you're using Python 3.8 or later:
```bash
python3 --version
```
