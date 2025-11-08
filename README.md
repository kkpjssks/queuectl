# QueueCTL - Background Job Queue System

`queuectl` is a CLI-based background job queue system built in Python. It manages background jobs with worker processes, handles retries using exponential backoff, and maintains a Dead Letter Queue (DLQ) for permanently failed jobs.

**[Link to Working CLI Demo]** <- *You must record this and place the link here!*

---

## 🚀 Features

* **CLI Interface**: All operations managed via a clean `queuectl` command.
* **Persistent Storage**: Uses **SQLite** to ensure jobs, states, and retries persist across restarts.
* **Concurrent Workers**: Supports multiple worker processes (`queuectl worker start --count 4`)
* **Atomic Operations**: Safely fetches jobs without race conditions using database transactions.
* **Exponential Backoff**: Automatically retries failed jobs with increasing delays (`base ^ attempts`).
* **Dead Letter Queue (DLQ)**: Moves jobs to a DLQ after all retries are exhausted.
* **Graceful Shutdown**: Workers finish their current job before exiting on `Ctrl+C` or `queuectl worker stop`.
* **Configurable**: Manage retries and backoff base via `queuectl config set`.

## 🛠️ Setup Instructions

1.  **Clone the Repository**
    ```bash
    git clone [https://github.com/your-username/queuectl.git](https://github.com/your-username/queuectl.git)
    cd queuectl
    ```

2.  **Create a Virtual Environment**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install in Editable Mode**
    This command uses `setup.py` to install the `queuectl` command while allowing you to edit the source code.
    ```bash
    pip install -e .
    ```

4.  **Verify Installation**
    You should now have the `queuectl` command available.
    ```bash
    queuectl --version
    ```

All data, configuration, and logs are stored in `~/.queuectl/`.

## ⚙️ Usage Examples

### 1. Enqueueing Jobs

Add jobs using a JSON string. An `id` is optional and will be generated if missing.

```bash

$ queuectl enqueue '{"command":"echo Hello World > job1.txt"}'
Job enqueued with ID: 5f9b...


$ queuectl enqueue '{"id":"fail-job", "command":"command_not_found"}'
Job enqueued with ID: fail-job


$ queuectl enqueue '{"command":"sleep 10 && echo done > job2.txt"}'
Job enqueued with ID: 7a2e...
```

### 2. Starting Workers

Start one or more workers. This command runs in the foreground.

```bash

$ queuectl worker start --count 2

Starting 2 workers (Manager PID: 12345)...
Press Ctrl+C to stop.
[Worker-0] Started.
[Worker-1] Started.
[Worker-0] Executing job 5f9b...: echo Hello World > job1.txt
[Worker-1] Executing job fail-job: command_not_found
[Worker-0] Job 5f9b... completed successfully.
[Worker-1] Job fail-job raised an exception: ...
[Worker-1] Job fail-job failed (attempt 1), retrying in 2s.
[Worker-0] Executing job 7a2e...: sleep 10 && echo done > job2.txt
[Worker-1] Job fail-job failed (attempt 2), retrying in 4s.
[Worker-1] Job fail-job failed (attempt 3), retrying in 8s.
[Worker-1] Job fail-job failed permanently, moved to DLQ.
...
^C
[Manager] Shutdown signal received. Stopping workers...
[Worker-0] Stopping.
[Worker-1] Stopping.
[Manager] All workers have stopped. Exiting.
```

### 3. Stopping Workers (from another terminal)

```bash
$ queuectl worker stop
Sent SIGTERM to worker manager (PID: 12345).
```

### 4. Checking Status

```bash
$ queuectl status
--- Worker Status ---
  Stopped

--- Job Queue ---
  Completed: 2
  Total: 2

--- Dead Letter Queue ---
  Dead: 1
```

### 5. Listing Jobs

```bash

$ queuectl list --state completed
ID: 5f9b... (Attempts: 0)
  Cmd: echo Hello World > job1.txt
  Updated: 2025-11-08 14:30:00
--------------------
ID: 7a2e... (Attempts: 0)
  Cmd: sleep 10 && echo done > job2.txt
  Updated: 2025-11-08 14:30:10
--------------------
```

### 6. Managing the DLQ

```bash

$ queuectl dlq list
--- DLQ Jobs (1) ---
ID: fail-job (Failed at: 2025-11-08 14:30:15)
  Cmd: command_not_found
  Attempts: 3
--------------------


$ queuectl dlq retry fail-job
Job fail-job moved back to queue as 'pending'.
```

### 7. Configuration

```bash

$ queuectl config show
{
  "max_retries": 3,
  "backoff_base": 2
}

$ queuectl config set max_retries 5
Set max_retries = 5
```

## 🏛️ Architecture Overview

### Job Lifecycle

1.  **Enqueue**: A job is added via `queuectl enqueue`. It's inserted into the `jobs` table in `queue.db` with `state = 'pending'` and `run_at = NOW`.
2.  **Fetch**: A worker process calls `db.fetch_job()`. This function **atomically** selects the next available job (`pending` or `failed` with `run_at <= NOW`) and updates its state to `processing` inside a `BEGIN IMMEDIATE` transaction. This prevents two workers from ever grabbing the same job.
3.  **Execute**: The worker runs the `command` using `subprocess.run()`.
4.  **Complete**: If the command's exit code is `0`, the job state is updated to `completed`.
5.  **Fail & Retry**: If the command fails (non-zero exit, timeout, or exception), the `attempts` counter is incremented.
    * If `attempts < max_retries`, the state is set to `failed` and `run_at` is updated to `NOW + (backoff_base ^ attempts)` seconds.
    * If `attempts >= max_retries`, the job is moved to the DLQ.
6.  **DLQ**: The job is deleted from the `jobs` table and inserted into the `dlq` table, where it stays until manually retried.

### Persistence

* **Database**: A single **SQLite** file (`~/.queuectl/queue.db`) stores all state.
* **Why SQLite?**: It's serverless, transactional, and built into Python. Using `PRAGMA journal_mode=WAL` and `BEGIN IMMEDIATE` transactions provides excellent concurrency support for multiple worker processes,
    preventing race conditions. This is far more robust than a JSON file.

### Worker Management

* `queuectl worker start` spawns a **manager process** (which holds the main PID) and N **worker processes** using Python's `multiprocessing` module.
* A `multiprocessing.Event` (`stop_event`) is passed to all workers.
* `queuectl worker stop` reads the manager's PID from `~/.queuectl/worker.pid` and sends it a `SIGTERM`.
* The manager catches `SIGTERM`/`SIGINT`, sets the `stop_event`, and waits (`.join()`) for all child processes to finish their current job and exit their loop. This is a **graceful shutdown**.

## ⚖️ Assumptions & Trade-offs

* **Trade-off: Shell Execution**: Jobs are run with `shell=True`. This is powerful (allows pipes, redirects) but is a security risk if untrusted users can enqueue jobs. A production system might disable this or use `shlex.split()`.
* **Assumption: Local Execution**: This system is designed for a single machine. It does not coordinate workers across a network.
* **Simplification: Worker Polling**: Workers poll the database (`time.sleep(1)`) when idle. This is simple but less efficient than a pub/sub or `LISTEN/NOTIFY` system (like PostgreSQL's).
* **Simplification: Job Output**: Job `stdout`/`stderr` is not captured, only the exit code. This was done for simplicity, but a "Bonus" feature would be to log this.

## 🧪 Testing Instructions

A simple bash script is provided to validate all core functionality.

1.  Make sure `queuectl` is installed (`pip install -e .`).
2.  Run the test script:
    ```bash
    bash tests/test_flow.sh
    ```

This script will:
1.  Clean up old runs.
2.  Set configuration.
3.  Enqueue a successful job, a failing job, and a long-running job.
4.  Start workers and let them run for 10 seconds.
5.  Stop the workers.
6.  Check `queuectl status` to verify the successful job is `completed` and the failing job is in the `dlq`.
7.  Retry the job from the DLQ and confirm it moves to `pending`.