"""
CLI Daemon Commands — cw daemon [start|stop|restart|status|ping]
===============================================================

Implements the actual daemon lifecycle commands called from cli.py.
"""

import argparse
import json
import os
import sys
import time

# ── Colors (reuse from parent) ────────────────────────────────
C = type("C", (), {
    k: v for k, v in {
        "RED": "\033[91m" if os.name != "nt" else "",
        "GREEN": "\033[92m" if os.name != "nt" else "",
        "YELLOW": "\033[93m" if os.name != "nt" else "",
        "BLUE": "\033[94m" if os.name != "nt" else "",
        "CYAN": "\033[96m" if os.name != "nt" else "",
        "BOLD": "\033[1m" if os.name != "nt" else "",
        "DIM": "\033[2m" if os.name != "nt" else "",
        "END": "\033[0m" if os.name != "nt" else "",
    }.items()
})()


def _parse_daemon_args(args):
    """Parse common daemon CLI arguments."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--wiki", default="./wiki", help="Wiki directory path")
    parser.add_argument("--port", type=int, default=9877, help="API port")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--llm-provider", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--config", default=None, help="Config file path")
    parsed = parser.parse_known_args(args)[0]
    return parsed


def cmd_daemon_start(rest_args=None):
    """Start the daemon in the foreground or background."""
    args = _parse_daemon_args(rest_args or [])

    print(f"{C.BOLD}{C.BLUE}🔧 Compound Wiki Daemon v2{C.END}")
    print(f"{C.BOLD}   Universal AI Memory Service{C.END}\n")

    # Check if already running
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://{args.host}:{args.port}/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "healthy":
                pid_path = str(Path(args.wiki).parent / ".daemon" / "cw-daemon.pid")
                existing_pid = "?"
                if os.path.exists(pid_path):
                    existing_pid = open(pid_path).read().strip()
                print(f"{C.YELLOW}⚠️  Daemon is already running (PID {existing_pid}){C.END}")
                print(f"  API: http://{args.host}:{args.port}")
                print(f"\n  Use 'cw daemon stop' to stop it first.")
                return
    except Exception:
        pass  # Not running, good

    print(f"  Wiki:   {os.path.abspath(args.wiki)}")
    print(f"  API:    http://{args.host}:{args.port}")

    llm_provider = args.llm_provider or os.environ.get("CW_LLM_PROVIDER", "openai")
    llm_model = args.llm_model or os.environ.get("CW_LLM_MODEL", "gpt-4o-mini")
    print(f"  LLM:    {llm_provider}/{llm_model}\n")

    # Build config
    config_data = {
        "wiki_path": os.path.abspath(args.wiki),
        "raw_path": os.path.abspath(os.path.join(args.wiki, "..", "raw")),
        "port": args.port,
        "host": args.host,
        "llm": {
            "provider": llm_provider,
            "model": llm_model,
            "api_key": os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", ""),
            "base_url": os.environ.get("CW_LLM_BASE_URL", ""),
        },
    }

    # Save config
    config_path = Path(args.wiki).parent / "cw-daemon.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, default=str)
    print(f"  Config: {config_path}\n")

    # Try to start the daemon process
    # We use subprocess so it runs independently of this shell session
    import subprocess

    daemon_script = os.path.join(os.path.dirname(__file__), "..", "cw_daemon", "_run.py")
    if not os.path.exists(daemon_script):
        # Fallback: try as a module
        daemon_cmd = [
            sys.executable, "-m", "cw_daemon._run",
            "--config", str(config_path),
        ]
    else:
        daemon_cmd = [sys.executable, daemon_script, "--config", str(config_path)]

    # Start in background on Unix, or as a detached process on Windows
    if os.name == "nt":
        # Windows: use CREATE_NEW_PROCESS_GROUP to detach
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | \
                        subprocess.DETACHED_PROCESS
        proc = subprocess.Popen(
            daemon_cmd,
            stdout=open(os.devnull, "w"),
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
    else:
        # Unix: double-fork for true daemonization
        pid = os.fork()
        if pid > 0:
            # Parent: wait briefly then check child status
            time.sleep(1)

            print(f"{C.GREEN}✅ Daemon starting...{C.END}")
            print(f"  Checking API at http://{args.host}:{args.port}/health ...", end=" ", flush=True)

            # Wait for daemon to be ready
            max_wait = 10
            started = False
            for i in range(max_wait):
                time.sleep(0.5)
                try:
                    req = urllib.request.Request(
                        f"http://{args.host}:{args.port}/health"
                    )
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        data = json.loads(resp.read().decode())
                        if data.get("status") == "healthy":
                            started = True
                            break
                except Exception:
                    continue

            if started:
                print(f"{C.GREEN}✅ Online!{C.END}\n")
                print(f"  Agent 接入方式:")
                print(f"    POST http://{args.host}:{args.port}/hook")
                print(f"    GET  http://{args.host}:{args.port}/query?q=...")
                print()
                print(f"  管理命令:")
                print(f"    cw daemon status")
                print(f"    cw daemon stop")
                print(f"    cw daemon ping\n")
            else:
                print(f"{C.YELLOW}⚠️  Daemon started but not yet online.{C.END}")
                print(f"  Check: cw daemon status")
                print(f"  Logs:  .daemon/daemon.log\n")
            return
        else:
            # Child: exec the daemon
            os.setsid()
            os.execlp(sys.executable, sys.executable, *daemon_cmd)

    # Windows path (no fork)
    time.sleep(1.5)
    print(f"{C.GREEN}✅ Daemon starting (PID {proc.pid}){C.END}\n")
    print(f"  检查状态: cw daemon status")
    print(f"  停止运行: cw daemon stop\n")


def cmd_daemon_stop():
    """Stop the running daemon."""
    print(f"{C.BOLD}🛑 Stopping Compound Wiki Daemon{C.END}\n")

    # Find PID file locations to check
    possible_pids = []
    wiki_dirs = ["./wiki"]
    root = find_wiki_root_silent()
    if root:
        wiki_dirs.insert(0, os.path.join(root, "wiki"))

    for wdir in wiki_dirs:
        ppath = Path(wdir).parent / ".daemon" / "cw-daemon.pid"
        if ppath.exists():
            possible_pids.append(ppath)

    if not possible_pids:
        # Try current directory
        cwd_pid = Path(".daemon/cw-daemon.pid")
        if cwd_pid.exists():
            possible_pids.append(cwd_pid)

    stopped = False
    for ppath in possible_pids:
        try:
            pid_str = ppath.read_text().strip()
            pid = int(pid_str)

            print(f"  找到 PID 文件: {ppath}")
            print(f"  PID: {pid}\n")

            # Try graceful shutdown via API first
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"http://127.0.0.1:9877/shutdown",
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=3)
                print(f"{C.GREEN}✅ Graceful shutdown requested{C.END}")
                stopped = True
            except Exception:
                pass

            if not stopped:
                # Force kill
                os.kill(pid, signal.SIGTERM if hasattr(signal, "SIGTERM") else 15)
                time.sleep(1)
                # Check if still alive
                try:
                    os.kill(pid, 0)
                    # Still alive, force kill
                    os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else 9)
                except OSError:
                    pass  # Already dead

            # Clean up PID file
            ppath.unlink(missing_ok=True)
            stopped = True
            break

        except (ValueError, ProcessLookupError, FileNotFoundError) as e:
            ppath.unlink(missing_ok=True)

    if stopped:
        print(f"\n{C.GREEN}✅ Daemon 已停止{C.END}")
    else:
        print(f"  {C.YELLOW}没有发现正在运行的 Daemon 实例{C.END}")


def cmd_daemon_restart(rest_args=None):
    """Restart the daemon."""
    print(f"🔄 Restarting Daemon...\n")
    cmd_daemon_stop()
    time.sleep(2)
    cmd_daemon_start(rest_args)


def cmd_daemon_status():
    """Show daemon status."""
    print(f"{C.BOLD}⚡ Compound Wiki Daemon Status{C.END}\n")

    # Check multiple PID locations
    found = False
    for wdir in ["./wiki"]:
        base = Path(wdir).parent
        state_file = base / ".daemon/state.json"

        if state_file.exists() and state_file.stat().st_size > 5:
            try:
                sdata = json.loads(state_file.read_text())

                # Check if actually running
                pid = sdata.get("pid")
                running = False
                if pid:
                    try:
                        os.kill(int(pid), 0)
                        running = True
                    except (OSError, ValueError, TypeError):
                        pass

                cfg = sdata.get("config", {})
                icon = f"{C.GREEN}●{C.END}" if running else f"{C.RED}○{C.END}"
                status_text = "Running" if running else "Stopped"

                print(f"  状态:  {icon} {status_text}")
                print(f"  PID:   {pid or 'N/A'}")
                print(f"  Port:  {cfg.get('port', '?')}")
                print(f"  Host:  {cfg.get('host', '?')}")
                print(f"  LLM:   {cfg.get('llm_provider', '?')} / {cfg.get('llm_model', '?')}")
                print(f"  Wiki:  {cfg.get('wiki_path', '?')}")

                if running:
                    # Try hitting health endpoint
                    port = cfg.get("port", 9877)
                    host = cfg.get("host", "127.0.0.1")
                    try:
                        import urllib.request
                        req = urllib.request.Request(f"http://{host}:{port}/health")
                        with urllib.request.urlopen(req, timeout=3) as resp:
                            hdata = json.loads(resp.read().decode())
                        print(f"\n  API:   {C.GREEN}在线{C.END} (v{hdata.get('version','?')})")
                    except Exception:
                        print(f"\n  API:   {C.YELLOW}离线（进程存在但API无响应）{C.END}")
                found = True
                break
            except json.JSONDecodeError:
                continue

    if not found:
        print(f"  状态:  {C.RED}未启动{C.END}")
        print(f"\n  启动: {C.CYAN}cw daemon start{C.END}")

    print()


def cmd_daemon_ping():
    """Quick ping — just checks if daemon responds."""
    try:
        import urllib.request
        start = time.time()
        req = urllib.request.Request(
            "http://127.0.0.1:9877/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            elapsed_ms = (time.time() - start) * 1000

            if data.get("status") == "healthy":
                print(f"{C.GREEN}● Daemon 在线{C.END} "
                      f"({elapsed_ms:.0f}ms) v{data.get('version','?')}")
            else:
                print(f"{C.RED}● Daemon 异常: {data}{C.END}")
    except Exception as e:
        print(f"{C.RED}○ Daemon 离线 ({e}){C.END}")


# ── Helpers ───────────────────────────────────────────────────

def find_wiki_root_silent():
    """Find wiki root without printing errors."""
    from pathlib import Path
    CLAUDE_FILE = "schema/CLAUDE.md"
    current = Path(os.getcwd())
    while current != current.parent:
        if (current / CLAUDE_FILE).exists():
            return str(current)
        current = current.parent
    return None


# Signal import (may not exist on all platforms)
try:
    import signal
except ImportError:
    signal = None


# Path import
from pathlib import Path
