import json
import os
from pathlib import Path


CONFIG_DIR = Path.home() / ".queuectl"
CONFIG_FILE = CONFIG_DIR / "config.json"
DB_PATH = CONFIG_DIR / "queue.db"
PID_FILE = CONFIG_DIR / "worker.pid"

DEFAULT_CONFIG = {
    "max_retries": 3,
    "backoff_base": 2, 
}

def ensure_config_dir():
    """Ensures the ~/.queuectl directory exists."""
    CONFIG_DIR.mkdir(exist_ok=True)

def load_config():
    """Loads configuration from file, or returns defaults."""
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                config.setdefault(key, value)
            return config
    except json.JSONDecodeError:
        return DEFAULT_CONFIG

def save_config(config_data):
    """Saves configuration data to the file."""
    ensure_config_dir()
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=2)

def write_pid():
    """Writes the current process ID to the PID file."""
    ensure_config_dir()
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def read_pid():
    """Reads the process ID from the PID file."""
    try:
        with open(PID_FILE, 'r') as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None

def remove_pid():
    """Removes the PID file."""
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass

def is_worker_running():
    """Checks if the worker process (by PID) is active."""
    pid = read_pid()
    if not pid:
        return False
    
    
    try:
        os.kill(pid, 0)
    except OSError:
        return False  
    else:
        return True