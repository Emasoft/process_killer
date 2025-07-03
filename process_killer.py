#!/usr/bin/env python3
"""
memory_leak_killer.py
=====================

A macOS watchdog that

1. **Detects persistent memory leaks** with linear-regression analysis and kills
   the offender after a configurable number of confirmations.
2. **Guards against system-wide memory pressure**: when total RAM exceeds a
   “high” threshold (default 90 %) it frees memory by terminating the *most
   suspicious* user processes until usage falls below a “low” threshold
   (default 85 %).
3. **Logs every kill** (reason = “leak” or “pressure”) and, if a process keeps
   respawning and re-filling memory, raises a native macOS notification so you
   can hunt the parent down yourself.
4. **Optionally restricts monitoring to iTerm2-spawned processes**
   (`--iterm-only`), useful when you want to sandbox experiments launched from
   a terminal while leaving the rest of the desktop alone.
5. Ships with an *augmented* critical-process whitelist to avoid destabilising
   the system.
6. **Two operation modes**:
   - Protection Mode (default): Only kills leaks when system RAM is high (≥85%)
   - Hunting Mode: Aggressively kills all detected leaks regardless of RAM
7. **Docker container monitoring** (--docker): Tracks and kills containers with
   memory leaks using the same detection algorithms

Optimal defaults are chosen for a 16-32 GB Mac running Sonoma (14.x), but
every heuristic can be tuned at runtime.

────────────────────────────────────────────────────────────────────────────
USAGE EXAMPLES
────────────────────────────────────────────────────────────────────────────
# 1) Ad-hoc run with defaults
sudo ./memory_leak_killer.py

# 2) More aggressive leak detection (steeper slope, larger growth window)
sudo ./memory_leak_killer.py --slope 30 --growth 150 --history 10

# 3) Guard only what you start from iTerm2
sudo ./memory_leak_killer.py --iterm-only

# 4) Install as a LaunchDaemon that starts at boot
sudo ./memory_leak_killer.py --install-daemon

# 5) Raise a notification after the same (name,parent) gets killed 5 × in 15 min
sudo ./memory_leak_killer.py --notify-threshold 5 --notify-window 900

# 6) Run in hunting mode to kill all leaks regardless of RAM usage
sudo ./memory_leak_killer.py --hunting-mode

# 7) Run in protection mode with custom threshold (only kill when RAM ≥ 90%)
sudo ./memory_leak_killer.py --protection-mode --leak-threshold 90

# 8) Monitor both processes and Docker containers
sudo ./memory_leak_killer.py --docker --slope 15 --growth 30
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

# Version information
try:
    from _version import __version__
except ImportError:
    __version__ = "unknown"

# ──────────────────────────── Heuristic defaults ────────────────────────────
DEF_SAMPLE_INT = 5  # s between samples
DEF_HISTORY_LEN = 6  # samples / regression window
DEF_GROW_MB = 50  # net growth inside window
DEF_SLOPE_MB_MIN = 20  # slope (MB/min) inside window
DEF_CONFIRMATIONS = 2  # bad windows before kill
DEF_GRACE_SEC = 60  # ignore first N s of process life
DEF_COOLDOWN_SEC = 300  # forgiveness after plateau

DEF_HIGH_PCT = 90  # trigger pressure relief at ≥
DEF_LOW_PCT = 85  # stop pressure relief at ≤
DEF_RECENT_SEC = 180  # “very young process” window
DEF_CHILD_WEIGHT = 5  # score bump per child proc

DEF_NOTIFY_THRESHOLD = 3  # kills before notification
DEF_NOTIFY_WINDOW_SEC = 600  # look-back window for recidivism
DEF_LEAK_THRESHOLD_PCT = 85  # min RAM % to kill leaks in protection mode

# Dynamic adjustment factors
ADJUST_INTERVAL_SEC = 30  # how often to adjust parameters

# ───────────────────────────────  Files / paths ─────────────────────────────
LOG_FILE = Path.home() / "memory_leak_killer.log"
DAEMON_PLIST_PATH = "/Library/LaunchDaemons/com.memoryleakkiller.monitor.plist"

# ──────────────────────  Critical processes never to kill  ──────────────────
# (union of Apple default daemons, GUI essentials, security agents, etc.)
WHITELIST = {
    # Kernels & launchers
    "kernel_task",
    "launchd",
    "launchservicesd",
    # UI core
    "WindowServer",
    "dock",
    "Finder",
    "ControlCenter",
    "NotificationCenter",
    # I/O + system daemons
    "syslogd",
    "UserEventAgent",
    "fseventsd",
    "diskarbitrationd",
    "locationd",
    "powerd",
    "hidd",
    "bluetoothd",
    "usbd",
    "cfprefsd",
    "configd",
    "mds",
    "mdworker",
    "mds_stores",
    "systemstats",
    "pboard",
    # Security / entitlement
    "securityd",
    "syspolicyd",
    "amfid",
    "trustd",
    "tccd",
    "sandboxd",
    # Misc Apple
    "rapportd",
    "notifyd",
    "distnoted",
    "opendirectoryd",
    "loginwindow",
    "accountsd",
    "sharingd",
    "lsd",
    "storeaccountd",
    # Docker daemon itself (but not containers)
    "com.docker.backend",
    "dockerd",
    "containerd",
}


# ──────────────────────────────  Data structures  ───────────────────────────
@dataclass
class SystemInfo:
    """System configuration and capabilities."""

    total_ram_gb: float
    cpu_count: int
    macos_version: str

    @classmethod
    def detect(cls) -> SystemInfo:
        """Detect current system configuration."""
        vm = psutil.virtual_memory()
        cpu_count = psutil.cpu_count(logical=True)
        return cls(
            total_ram_gb=vm.total / (1024**3),
            cpu_count=cpu_count if cpu_count is not None else 1,
            macos_version=platform.mac_ver()[0],
        )

    def optimize_params(self, args: argparse.Namespace) -> None:
        """Adjust parameters based on system configuration."""
        # Smaller systems need tighter monitoring
        if self.total_ram_gb <= 8:
            args.slope = min(args.slope, 10)
            args.growth = min(args.growth, 25)
            args.interval = min(args.interval, 3)
            args.high = min(args.high, 85)
            args.low = min(args.low, 80)
            args.leak_threshold = min(args.leak_threshold, 75)
        elif self.total_ram_gb <= 16:
            args.slope = min(args.slope, 15)
            args.growth = min(args.growth, 40)
            args.interval = min(args.interval, 4)
            args.high = min(args.high, 88)
            args.low = min(args.low, 83)
            args.leak_threshold = min(args.leak_threshold, 80)
        # Larger systems can be more relaxed
        elif self.total_ram_gb >= 64:
            args.interval = max(args.interval, 8)
            args.grace = max(args.grace, 90)

        # CPU-bound adjustment
        if self.cpu_count <= 4:
            args.interval = max(args.interval, 6)  # Less frequent monitoring

        log(f"System: {self.total_ram_gb:.1f}GB RAM, {self.cpu_count} CPUs, macOS {self.macos_version}")
        log(f"Optimized params: slope={args.slope}, growth={args.growth}, interval={args.interval}")


@dataclass
class DynamicParams:
    """Parameters that adjust during runtime based on pressure."""

    base_slope: float
    base_growth: float
    base_confirmations: int
    current_slope: float
    current_growth: float
    current_confirmations: int
    last_adjust: float = 0.0
    pressure_factor: float = 1.0

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> DynamicParams:
        """Initialize from command line arguments."""
        slope_bps = args.slope * 1024**2 / 60
        growth_b = args.growth * 1024**2
        return cls(
            base_slope=slope_bps,
            base_growth=growth_b,
            base_confirmations=args.conf,
            current_slope=slope_bps,
            current_growth=growth_b,
            current_confirmations=args.conf,
        )

    def adjust_for_pressure(self, vm_percent: float) -> None:
        """Tighten parameters when memory pressure increases."""
        now = time.time()
        if now - self.last_adjust < ADJUST_INTERVAL_SEC:
            return

        self.last_adjust = now

        # Calculate pressure factor (0.5 to 1.0)
        if vm_percent >= 90:
            self.pressure_factor = 0.5
        elif vm_percent >= 85:
            self.pressure_factor = 0.6
        elif vm_percent >= 80:
            self.pressure_factor = 0.7
        elif vm_percent >= 75:
            self.pressure_factor = 0.85
        else:
            self.pressure_factor = 1.0

        # Apply pressure factor
        self.current_slope = self.base_slope * self.pressure_factor
        self.current_growth = self.base_growth * self.pressure_factor
        self.current_confirmations = max(1, int(self.base_confirmations * self.pressure_factor))

        if self.pressure_factor < 1.0:
            log(f"Adjusted params for {vm_percent:.1f}% RAM: slope factor={self.pressure_factor:.2f}")


@dataclass
class ProcTracker:
    rss_hist: deque[tuple[float, int]] = field(default_factory=lambda: deque(maxlen=DEF_HISTORY_LEN))
    suspect_runs: int = 0
    exempt_until: float = 0.0
    growth_rate: float = 0.0  # Track growth rate for predictive killing

    @property
    def full(self) -> bool:
        return len(self.rss_hist) == self.rss_hist.maxlen

    def add(self, rss: int) -> None:
        self.rss_hist.append((time.time(), rss))

    def reset(self) -> None:
        self.suspect_runs = 0


# Type definitions
KillRecord = dict[tuple[str, str], list[float]]  # (proc_name, parent_name) → kill timestamps

# Global state - consider thread safety if ever made concurrent
ProcessTable: dict[int, ProcTracker] = defaultdict(ProcTracker)
Recidivism: KillRecord = defaultdict(list)
DockerContainers: dict[str, ProcTracker] = defaultdict(ProcTracker)  # container_id → tracker


# ─────────────────────────────  Tiny helpers  ───────────────────────────────
def log(msg: str) -> None:
    """Log message with automatic rotation at 50MB."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Rotate log if it gets too large (50MB)
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 50 * 1024 * 1024:
            backup = LOG_FILE.with_suffix(".old")
            if backup.exists():
                backup.unlink()
            LOG_FILE.rename(backup)
    except OSError:
        pass  # Continue logging even if rotation fails

    try:
        with LOG_FILE.open("a") as fp:
            fp.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass  # Fail silently to avoid disrupting monitoring


def esc(s: str) -> str:  # simple shell-safe escaper for osascript strings
    return s.replace('"', '\\"')


def is_critical_threat(trk: ProcTracker, vm_percent: float, sys_info: SystemInfo) -> bool:
    """Predict if a process will crash the system before next check."""
    if not trk.full or trk.growth_rate <= 0:
        return False

    # Estimate time until system crash
    available_mb = (100 - vm_percent) * sys_info.total_ram_gb * 1024 / 100
    growth_mb_per_min = trk.growth_rate * 60 / (1024 * 1024)  # Convert bytes/sec to MB/min

    # Avoid division by zero and handle very slow growth
    if growth_mb_per_min < 1.0:  # Less than 1 MB/min is not a critical threat
        return False

    time_to_crash_min = available_mb / growth_mb_per_min

    # Kill if crash likely within 2 check intervals (2 minutes)
    return time_to_crash_min < 2.0


def should_kill_leak(args: argparse.Namespace) -> bool:
    """Determine if we should kill memory leaks based on mode and memory usage."""
    if hasattr(args, "hunting_mode") and args.hunting_mode:
        return True  # Always kill leaks in hunting mode

    # In protection mode, only kill if memory is high
    vm = psutil.virtual_memory()
    leak_threshold = getattr(args, "leak_threshold", DEF_LEAK_THRESHOLD_PCT)
    return bool(vm.percent >= leak_threshold)


def handle_critical_leak(proc: psutil.Process, args: argparse.Namespace) -> None:  # noqa: ARG001
    """Handle a critical leak that threatens system stability."""
    try:
        name = proc.name()
        pid = proc.pid
        rss_mb = proc.memory_info().rss / 1024 / 1024

        # Send urgent notification
        notify(
            "CRITICAL Memory Leak!",
            f"{name} (PID {pid}) using {rss_mb:.0f}MB and growing rapidly. Killed to prevent system crash.",
        )

        # Log critical event
        log(f"CRITICAL: Predictive kill of {name} (PID {pid}) to prevent system crash")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def notify(title: str, message: str) -> None:
    """
    Fire a macOS user notification via AppleScript.
    Runs best when invoked as root from launchd (no extra privileges needed).
    """
    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    with contextlib.suppress(subprocess.TimeoutExpired):
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)


def window_stats(hist: deque[tuple[float, int]]) -> tuple[float, int]:
    """Return (slope_bytes_per_sec, net_growth_bytes) for one window."""
    n = len(hist)
    if n == 0:
        return 0.0, 0
    if n == 1:
        return 0.0, 0
    xs = [t for t, _ in hist]
    ys = [v for _, v in hist]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom < 1e-9:  # More robust near-zero check
        return 0.0, ys[-1] - ys[0]
    slope = sum((x - mean_x) * (y - mean_y) for x, y in hist) / denom
    return slope, ys[-1] - ys[0]


def is_leaking(trk: ProcTracker, slope_limit_bps: float, growth_limit_b: float, pos_ratio: float = 0.8) -> bool:
    """Return True if the rss history matches our definition of a leak."""
    if not trk.full:
        return False
    slope, growth = window_stats(trk.rss_hist)
    nondecr = sum(1 for i in range(1, len(trk.rss_hist)) if trk.rss_hist[i][1] >= trk.rss_hist[i - 1][1])
    return nondecr / (len(trk.rss_hist) - 1) >= pos_ratio and slope > slope_limit_bps and growth > growth_limit_b


def is_descendant_of_iterm(proc: psutil.Process) -> bool:
    """True if *any* ancestor is iTerm2 (GUI or helper)."""
    try:
        for anc in proc.parents():
            try:
                name = anc.name()
                exe = anc.exe() or ""
                if name.startswith("iTerm2") or "iTerm.app" in exe:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
        pass
    return False


def get_docker_container_stats() -> dict[str, dict[str, Any]]:
    """Get memory stats for all running Docker containers."""
    try:
        # Get container stats in JSON format
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            if result.returncode == 127:  # Command not found
                log("Docker command not found. Please install Docker.")
            return {}

        stats = {}
        for line in result.stdout.strip().split("\n"):
            if line:
                data = json.loads(line)
                # Safely get container ID
                container_id = data.get("Container", "")
                if not container_id:
                    continue
                container_id = container_id[:12]

                # Parse memory usage (e.g., "1.5GiB / 2GiB")
                mem_usage = data.get("MemUsage", "0B / 0B")
                usage_parts = mem_usage.split(" / ")
                if len(usage_parts) == 2:
                    current = parse_memory_string(usage_parts[0])
                    limit = parse_memory_string(usage_parts[1])

                    stats[container_id] = {
                        "name": data.get("Name", container_id),
                        "memory_usage_bytes": current,
                        "memory_limit_bytes": limit,
                        "memory_percent": (current / limit * 100) if limit > 0 else 0,
                    }
        return stats
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log(f"Error parsing Docker stats: {e}")
        return {}
    except Exception as e:
        log(f"Unexpected error getting Docker stats: {e}")
        return {}


def parse_memory_string(mem_str: str) -> int:
    """Parse Docker memory string (e.g., '1.5GiB') to bytes."""
    mem_str = mem_str.strip()
    match = re.match(r"([0-9.]+)\s*([A-Za-z]+)", mem_str)
    if not match:
        return 0

    value = float(match.group(1))
    unit = match.group(2).upper()

    multipliers = {
        "B": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024**2,
        "MIB": 1024**2,
        "GB": 1024**3,
        "GIB": 1024**3,
    }

    return int(value * multipliers.get(unit, 1))


def kill_docker_container(container_id: str, container_name: str, reason: str, args: argparse.Namespace) -> None:
    """Kill a Docker container."""
    try:
        # First try to stop gracefully
        subprocess.run(["docker", "stop", "-t", "10", container_id], check=False, timeout=15)

        msg = f"Killed Docker container {container_id} ({container_name}), reason={reason}"
        print(f"[{reason.upper()}] {msg}")
        log(msg)

        # Update recidivism tracking
        key = (f"docker:{container_name}", "docker")
        now = time.time()
        Recidivism[key].append(now)
        Recidivism[key] = [t for t in Recidivism[key] if now - t <= args.notify_window]

        if len(Recidivism[key]) >= args.notify_threshold:
            notify(
                "Docker Container Memory Leak",
                f"Container {container_name} killed {len(Recidivism[key])}× in {args.notify_window // 60} minutes",
            )
            Recidivism[key].clear()
    except Exception as e:
        log(f"Failed to kill container {container_id}: {e}")


# ───────────────────────────── Kill wrapper  ────────────────────────────────
def kill_process(proc: psutil.Process, reason: str, slope_mb_min: float, args: argparse.Namespace) -> None:
    """
    Wrapper that:
      • kills the process,
      • logs with explicit reason,
      • updates recidivism table,
      • fires notification if repeated offender.
    """
    try:
        pid = proc.pid
        name = proc.name()
        rss_mb = proc.memory_info().rss / 1024 / 1024
        try:
            parent = proc.parent()
            parent_name = parent.name() if parent else "—"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            parent_name = "—"
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return

    try:
        # Try SIGTERM first, then SIGKILL if needed
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return

    msg = f"Killed PID {pid} ({name}) parent={parent_name} rss={rss_mb:.1f} MB, slope≈{slope_mb_min:.1f} MB/min, reason={reason}"
    print(f"[{reason.upper()}] {msg}")
    log(msg)

    # ── recidivism tracking & notification ─────────────────────────────
    key = (name, parent_name)
    now = time.time()
    Recidivism[key].append(now)
    # keep list trimmed to window
    Recidivism[key] = [t for t in Recidivism[key] if now - t <= args.notify_window]
    if len(Recidivism[key]) >= args.notify_threshold:
        title = "Memory Leak Killer"
        body = f"{name} (parent: {parent_name}) was killed {len(Recidivism[key])}× in the last {args.notify_window // 60} minutes."
        notify(title, body)
        # prevent notification spam by clearing records
        Recidivism[key].clear()


# ─────────────────────  Memory-pressure relief routine  ─────────────────────
def pressure_relief(args: argparse.Namespace, slope_limit_bps: float) -> None:  # noqa: ARG001
    vm = psutil.virtual_memory()
    if vm.percent < args.high:
        return

    print(f"[PRESSURE] RAM {vm.percent:.1f}% ≥ {args.high}%—relieving…")
    log(f"Pressure {vm.percent:.1f}%: starting relief")

    now = time.time()
    candidates: list[tuple[float, Any, float, str]] = []  # score, target, slope, type

    for proc in psutil.process_iter(["pid", "name", "create_time", "memory_info"]):
        try:
            if proc.info["name"] in WHITELIST:
                continue
            if hasattr(args, "iterm_only") and args.iterm_only and not is_descendant_of_iterm(proc):
                continue

            pid = proc.pid
            trk = ProcessTable.get(pid)
            slope_bps, _ = window_stats(trk.rss_hist) if (trk and trk.full) else (0.0, 0)
            slope_mb_min = slope_bps * 60 / (1024**2)

            create_time = proc.info.get("create_time", now)
            age = now - create_time

            try:
                child_cnt = len(proc.children(recursive=True))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                child_cnt = 0

            memory_info = proc.info.get("memory_info")
            if not memory_info:
                continue
            rss_mb = memory_info.rss / 1024 / 1024

            score = (trk.suspect_runs if trk else 0) * 20 + slope_mb_min * 2 + max(0, (args.recent - age) / args.recent) * 10 + child_cnt * args.child_wt + rss_mb / 100

            candidates.append((score, proc, slope_mb_min, "process"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Also consider Docker containers if enabled
    if hasattr(args, "docker") and args.docker:
        container_stats = get_docker_container_stats()
        for container_id, stats in container_stats.items():
            trk = DockerContainers.get(container_id)
            if trk and trk.full:
                slope_bps, _ = window_stats(trk.rss_hist)
                slope_mb_min = slope_bps * 60 / (1024**2)
                memory_mb = stats["memory_usage_bytes"] / 1024 / 1024

                score = (trk.suspect_runs) * 20 + slope_mb_min * 2 + memory_mb / 100

                candidates.append((score, (container_id, stats["name"]), slope_mb_min, "container"))

    for _score, target, slope_mb_min, target_type in sorted(candidates, key=lambda c: c[0], reverse=True):
        if target_type == "process":
            kill_process(target, "pressure", slope_mb_min, args)
        else:  # container
            container_id, container_name = target
            kill_docker_container(container_id, container_name, "pressure", args)

        if psutil.virtual_memory().percent <= args.low:
            print(f"✓ RAM now {psutil.virtual_memory().percent:.1f}% ≤ {args.low}%")
            break
    else:
        print("! Pressure persists—no remaining candidates.")


# ───────────────────────────── Main monitor  ────────────────────────────────
def monitor(args: argparse.Namespace) -> None:
    # Display version information
    print(f"Process Killer v{__version__}")
    print("─" * 40)

    # Detect system and optimize parameters
    sys_info = SystemInfo.detect()
    sys_info.optimize_params(args)

    # Initialize dynamic parameters
    dyn_params = DynamicParams.from_args(args)

    mode = "hunting" if hasattr(args, "hunting_mode") and args.hunting_mode else "protection"
    log(f"Process Killer v{__version__} - Monitoring started in {mode} mode with params: slope={args.slope}MB/min, growth={args.growth}MB, interval={args.interval}s")
    if not hasattr(args, "hunting_mode") or not args.hunting_mode:
        leak_threshold = getattr(args, "leak_threshold", DEF_LEAK_THRESHOLD_PCT)
        log(f"Protection mode: will only kill leaks when RAM ≥ {leak_threshold}%")
    if hasattr(args, "docker") and args.docker:
        log("Docker container monitoring enabled")

    while True:
        now = time.time()
        vm = psutil.virtual_memory()

        # Dynamically adjust parameters based on pressure
        dyn_params.adjust_for_pressure(vm.percent)

        # Monitor Docker containers if enabled
        if hasattr(args, "docker") and args.docker:
            monitor_docker_containers(args, dyn_params, sys_info)

        for proc in psutil.process_iter(["pid", "name", "memory_info", "create_time"]):
            try:
                name = proc.info["name"] or ""
                if name in WHITELIST:
                    continue
                if hasattr(args, "iterm_only") and args.iterm_only and not is_descendant_of_iterm(proc):
                    continue

                pid = proc.pid
                memory_info = proc.info.get("memory_info")
                if not memory_info:
                    continue
                rss = memory_info.rss
                create_time = proc.info.get("create_time", now)
                if now - create_time < args.grace:
                    continue  # warm-up grace

                trk = ProcessTable[pid]
                trk.add(rss)

                if trk.exempt_until > now:
                    continue  # in cooldown

                # Calculate and store growth rate for predictive analysis
                if trk.full:
                    slope, growth = window_stats(trk.rss_hist)
                    trk.growth_rate = slope

                if is_leaking(trk, dyn_params.current_slope, dyn_params.current_growth):
                    trk.suspect_runs += 1
                    if trk.suspect_runs >= dyn_params.current_confirmations:
                        # Predictive check: will this process likely crash the system?
                        if is_critical_threat(trk, vm.percent, sys_info):
                            kill_process(
                                proc,
                                "critical-leak",
                                slope_mb_min=dyn_params.current_slope * 60 / 1024 / 1024,
                                args=args,
                            )
                            ProcessTable.pop(pid, None)
                            continue
                        elif should_kill_leak(args):
                            kill_process(
                                proc,
                                "leak",
                                slope_mb_min=dyn_params.current_slope * 60 / 1024 / 1024,
                                args=args,
                            )
                            ProcessTable.pop(pid, None)
                            continue
                        else:
                            # Log that we detected but didn't kill
                            rss_mb = rss / 1024 / 1024
                            log(f"Leak detected but not killed (protection mode, RAM {vm.percent:.1f}%): PID {pid} ({name}) rss={rss_mb:.1f}MB slope≈{dyn_params.current_slope * 60 / 1024 / 1024:.1f}MB/min")
                else:
                    if trk.suspect_runs:
                        trk.exempt_until = now + args.cool
                    trk.reset()

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                ProcessTable.pop(proc.pid, None)

        pressure_relief(args, dyn_params.current_slope)
        time.sleep(args.interval)


def monitor_docker_containers(args: argparse.Namespace, dyn_params: DynamicParams, sys_info: SystemInfo) -> None:
    """Monitor Docker containers for memory leaks."""
    container_stats = get_docker_container_stats()

    for container_id, stats in container_stats.items():
        memory_bytes = stats["memory_usage_bytes"]
        container_name = stats["name"]

        # Track container memory
        trk = DockerContainers[container_id]
        trk.add(memory_bytes)

        if trk.full:
            slope, growth = window_stats(trk.rss_hist)
            trk.growth_rate = slope

            if is_leaking(trk, dyn_params.current_slope, dyn_params.current_growth):
                trk.suspect_runs += 1
                if trk.suspect_runs >= dyn_params.current_confirmations:
                    # Check if we should kill based on mode and system state
                    vm = psutil.virtual_memory()
                    if is_critical_threat(trk, vm.percent, sys_info):
                        kill_docker_container(container_id, container_name, "critical-leak", args)
                        DockerContainers.pop(container_id, None)
                    elif should_kill_leak(args):
                        kill_docker_container(container_id, container_name, "leak", args)
                        DockerContainers.pop(container_id, None)
                    else:
                        log(f"Docker container leak detected but not killed (protection mode, RAM {vm.percent:.1f}%): {container_name} ({container_id}) memory={memory_bytes / 1024 / 1024:.1f}MB")
            else:
                if trk.suspect_runs:
                    trk.exempt_until = time.time() + args.cool
                trk.reset()

    # Clean up containers that no longer exist
    active_containers = set(container_stats.keys())
    for container_id in list(DockerContainers.keys()):
        if container_id not in active_containers:
            DockerContainers.pop(container_id, None)


# ─────────────────────────── Launch-daemon helpers ──────────────────────────
def require_root() -> None:
    """Exit if not running as root."""
    if os.geteuid() != 0:
        sys.exit("This command must be run with sudo/root privileges.")


def install_daemon() -> None:
    require_root()
    # Validate Python executable exists
    if not Path(sys.executable).exists():
        sys.exit(f"Python executable not found: {sys.executable}")
    if not Path(__file__).exists():
        sys.exit(f"Script file not found: {__file__}")

    # Sanitize paths to prevent shell injection
    safe_python = os.path.abspath(sys.executable)
    safe_script = os.path.abspath(__file__)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.memoryleakkiller.monitor</string>
  <key>ProgramArguments</key><array>
    <string>{safe_python}</string>
    <string>{safe_script}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{LOG_FILE}</string>
  <key>StandardErrorPath</key><string>{LOG_FILE}</string>
</dict></plist>
"""
    Path(DAEMON_PLIST_PATH).write_text(plist)
    os.chmod(DAEMON_PLIST_PATH, 0o644)
    subprocess.run(["launchctl", "load", DAEMON_PLIST_PATH], check=False, timeout=10)
    log("Daemon installed")
    print("Launch-daemon installed and started.")


def uninstall_daemon() -> None:
    require_root()
    subprocess.run(
        ["launchctl", "unload", DAEMON_PLIST_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    Path(DAEMON_PLIST_PATH).unlink(missing_ok=True)
    log("Daemon removed")
    print("Launch-daemon removed.")


def daemon_ctl(action: str) -> None:
    require_root()
    subprocess.run(["launchctl", action, DAEMON_PLIST_PATH], check=False, timeout=10)
    print(f"Daemon {action}ed.")


# ────────────────────────────  CLI / argparse  ──────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    epilog = """
MEMORY LEAK DETECTION:
A process is considered a *leak* when its RSS fits an upward line whose
slope is ≥ --slope MB/min AND whose net growth is ≥ --growth MB within the
sliding window of --history samples. It must satisfy this in --conf
consecutive windows to be killed.

OPERATION MODES:
- Protection Mode (default): Only kills memory leaks when system RAM ≥ --leak-threshold %
- Hunting Mode: Aggressively kills ALL detected memory leaks regardless of available RAM

MEMORY PRESSURE RELIEF:
When total RAM exceeds --high %, the script ranks all non-whitelisted processes
by a heuristic score (confirmed leak, growth slope, age, child count, size) and
terminates the worst until RAM falls below --low %.

ADAPTIVE BEHAVIOR:
- Parameters auto-adjust based on system configuration (RAM size, CPU count)
- Dynamic tightening under memory pressure for faster leak detection
- Predictive killing of processes that would crash the system before next check

NOTIFICATIONS:
Native macOS notifications fire when the same (name, parent_name) pair has
been killed ≥ --notify-threshold times within --notify-window seconds.

EXAMPLES:
  # Default protection mode (safe for production)
  sudo ./memory_leak_killer.py

  # Aggressive leak hunting (for development)
  sudo ./memory_leak_killer.py --hunting-mode --slope 10 --growth 20

  # Custom thresholds for sensitive systems
  sudo ./memory_leak_killer.py --high 80 --low 70 --leak-threshold 75

  # Monitor only terminal-spawned processes
  sudo ./memory_leak_killer.py --iterm-only --hunting-mode

  # Include Docker container monitoring
  sudo ./memory_leak_killer.py --docker --hunting-mode
"""
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Kill persistent memory leakers and relieve RAM pressure.",
        epilog=epilog,
    )

    # Version flag
    p.add_argument("--version", action="version", version=f"Process Killer v{__version__}")

    mg = p.add_mutually_exclusive_group()
    mg.add_argument("--install-daemon", action="store_true", help="Install as LaunchDaemon (runs at boot)")
    mg.add_argument("--uninstall-daemon", action="store_true", help="Remove the LaunchDaemon")
    mg.add_argument("--start", action="store_true", help="Start the daemon")
    mg.add_argument("--stop", action="store_true", help="Stop the daemon")

    # Leak-detector knobs
    p.add_argument(
        "--interval",
        type=int,
        default=DEF_SAMPLE_INT,
        help=f"Sampling interval in seconds. Lower = more responsive but higher CPU. Auto-adjusted based on system specs. (default: {DEF_SAMPLE_INT})",
    )
    p.add_argument(
        "--history",
        type=int,
        default=DEF_HISTORY_LEN,
        help=f"Number of samples in regression window. More = smoother detection but slower response. (default: {DEF_HISTORY_LEN})",
    )
    p.add_argument(
        "--growth",
        type=int,
        default=DEF_GROW_MB,
        help=f"Minimum net memory growth (MB) within window to consider a leak. Auto-adjusted for system RAM. (default: {DEF_GROW_MB})",
    )
    p.add_argument(
        "--slope",
        type=int,
        default=DEF_SLOPE_MB_MIN,
        help=f"Minimum growth rate (MB/min) to consider a leak. Lower = catch slow leaks. Auto-adjusted under pressure. (default: {DEF_SLOPE_MB_MIN})",
    )
    p.add_argument(
        "--conf",
        type=int,
        default=DEF_CONFIRMATIONS,
        help=f"Consecutive bad windows needed before killing. Higher = fewer false positives. Auto-reduced under pressure. (default: {DEF_CONFIRMATIONS})",
    )
    p.add_argument(
        "--grace",
        type=int,
        default=DEF_GRACE_SEC,
        help=f"Seconds to ignore new processes (initialization period). (default: {DEF_GRACE_SEC})",
    )
    p.add_argument(
        "--cool",
        type=int,
        default=DEF_COOLDOWN_SEC,
        help=f"Cooldown seconds after a process plateaus (stops growing). (default: {DEF_COOLDOWN_SEC})",
    )

    # Pressure-relief knobs
    p.add_argument(
        "--high",
        type=int,
        default=DEF_HIGH_PCT,
        help=f"RAM percentage to trigger emergency pressure relief. Auto-adjusted for small systems. (default: {DEF_HIGH_PCT})",
    )
    p.add_argument(
        "--low",
        type=int,
        default=DEF_LOW_PCT,
        help=f"RAM percentage to stop pressure relief (hysteresis). Must be < --high. (default: {DEF_LOW_PCT})",
    )
    p.add_argument(
        "--recent",
        type=int,
        default=DEF_RECENT_SEC,
        help=f"Seconds to consider a process 'young' (more suspicious). (default: {DEF_RECENT_SEC})",
    )
    p.add_argument(
        "--child-wt",
        type=float,
        default=DEF_CHILD_WEIGHT,
        help=f"Suspicion score multiplier per child process. (default: {DEF_CHILD_WEIGHT})",
    )

    # Notification & scope
    p.add_argument(
        "--notify-threshold",
        type=int,
        default=DEF_NOTIFY_THRESHOLD,
        help=f"Number of kills of same process before user notification. (default: {DEF_NOTIFY_THRESHOLD})",
    )
    p.add_argument(
        "--notify-window",
        type=int,
        default=DEF_NOTIFY_WINDOW_SEC,
        help=f"Time window (seconds) for counting repeated kills. (default: {DEF_NOTIFY_WINDOW_SEC})",
    )
    p.add_argument(
        "--iterm-only",
        action="store_true",
        help="Only monitor processes spawned from iTerm2. Useful for safely testing in development without affecting system processes.",
    )
    p.add_argument(
        "--docker",
        action="store_true",
        help="Enable Docker container monitoring. Tracks and kills containers with memory leaks. Requires Docker CLI to be installed.",
    )

    # Operation modes
    mode_group = p.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--protection-mode",
        action="store_true",
        default=True,
        help="Only kill leaks when RAM is high (default)",
    )
    mode_group.add_argument(
        "--hunting-mode",
        action="store_true",
        help="Kill all detected leaks regardless of RAM usage",
    )
    p.add_argument(
        "--leak-threshold",
        type=int,
        default=DEF_LEAK_THRESHOLD_PCT,
        help=f"Minimum RAM percentage to start killing leaks in protection mode. Ignored in hunting mode. (default: {DEF_LEAK_THRESHOLD_PCT})",
    )

    return p


# ───────────────────────────── entry-point ──────────────────────────────────
def main() -> None:
    args = build_parser().parse_args()

    # Set mode flags properly (protection mode is default)
    if not hasattr(args, "hunting_mode") or not args.hunting_mode:
        args.protection_mode = True
        args.hunting_mode = False

    # Check Docker availability if --docker is specified
    if hasattr(args, "docker") and args.docker:
        try:
            result = subprocess.run(["docker", "--version"], capture_output=True, check=False, timeout=5)
            if result.returncode != 0:
                sys.exit("Error: Docker is not installed or not in PATH. Please install Docker to use --docker option.")
        except FileNotFoundError:
            sys.exit("Error: Docker command not found. Please install Docker to use --docker option.")

    # Validate arguments
    if args.high <= args.low:
        sys.exit(f"Error: --high ({args.high}) must be greater than --low ({args.low})")
    if args.interval < 1:
        sys.exit("Error: --interval must be at least 1 second")
    if args.history < 2:
        sys.exit("Error: --history must be at least 2 samples")
    if args.slope < 0 or args.growth < 0:
        sys.exit("Error: --slope and --growth must be non-negative")
    if hasattr(args, "leak_threshold") and (args.leak_threshold < 0 or args.leak_threshold > 100):
        sys.exit("Error: --leak-threshold must be between 0 and 100")

    # propagate history length to existing trackers
    for trk in ProcessTable.values():
        trk.rss_hist = deque(maxlen=args.history)

    if args.install_daemon:
        install_daemon()
    elif args.uninstall_daemon:
        uninstall_daemon()
    elif args.start:
        daemon_ctl("load")
    elif args.stop:
        daemon_ctl("unload")
    else:
        try:
            monitor(args)
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            log("Monitoring stopped by user.")


if __name__ == "__main__":
    main()
