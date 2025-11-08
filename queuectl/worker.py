import subprocess
import time
import signal
import multiprocessing
import os
from datetime import datetime, timedelta
from .db import JobQueue
from .config import load_config

class Worker:
    """A single worker instance that processes one job at a time."""
    
    def __init__(self, queue, config):
        self.queue = queue
        self.config = config

    def execute_job(self, job):
        """
        Executes a job's command and handles its success or failure.
        """
        job_id = job['id']
        print(f"[Worker] Executing job {job_id}: {job['command']}")
        
        try:
            
            result = subprocess.run(
                job['command'], 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=300 
            )

            if result.returncode == 0:
                
                self.queue.complete_job(job_id)
                print(f"[Worker] Job {job_id} completed successfully.")
            else:
                
                print(f"[Worker] Job {job_id} failed with exit code {result.returncode}.")
                self.handle_failure(job)

        except subprocess.TimeoutExpired:
            print(f"[Worker] Job {job_id} timed out.")
            self.handle_failure(job)
        except Exception as e:
            
            print(f"[Worker] Job {job_id} raised an exception: {e}")
            self.handle_failure(job)

    def handle_failure(self, job):
        """
        Handles a failed job by either scheduling a retry
        or moving it to the DLQ.
        """
        current_attempts = job['attempts'] + 1
        max_retries = job.get('max_retries', self.config['max_retries'])

        if current_attempts >= max_retries:
            
            job['attempts'] = current_attempts
            self.queue.move_to_dlq(job)
            print(f"[Worker] Job {job['id']} failed permanently, moved to DLQ.")
        else:
            
            base = self.config.get('backoff_base', 2)
            delay_seconds = base ** current_attempts
            next_run_at = datetime.now() + timedelta(seconds=delay_seconds)
            
            self.queue.schedule_retry(job['id'], current_attempts, next_run_at)
            print(f"[Worker] Job {job['id']} failed (attempt {current_attempts}), retrying in {delay_seconds}s.")


def run_worker_loop(db_path, config, stop_event, worker_id):
    """
    The main loop for a single worker process.
    It creates its own DB connection.
    """
    
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    
    print(f"[Worker-{worker_id}] Started.")
    queue = JobQueue(db_path)
    worker = Worker(queue, config)
    
    while not stop_event.is_set():
        job = queue.fetch_job()
        
        if job:
            worker.execute_job(job)
        else:
            
            stop_event.wait(timeout=1.0) 
            
    print(f"[Worker-{worker_id}] Stopping.")

def start_workers(count):
    """
    The main blocking function to start and manage worker processes.
    Handles SIGINT/SIGTERM for graceful shutdown.
    """
    from .config import DB_PATH, write_pid, remove_pid, is_worker_running
    
    if is_worker_running():
        print("Workers already running (PID file exists).")
        return

    write_pid()
    config = load_config()
    db_path = DB_PATH
    
    print(f"Starting {count} workers (Manager PID: {os.getpid()})...")
    print("Press Ctrl+C to stop.")

    
    stop_event = multiprocessing.Event()
    processes = []

    
    def signal_handler(sig, frame):
        print("\n[Manager] Shutdown signal received. Stopping workers...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    for i in range(count):
        p = multiprocessing.Process(
            target=run_worker_loop,
            args=(db_path, config, stop_event, i)
        )
        p.start()
        processes.append(p)

    
    for p in processes:
        p.join()

    
    remove_pid()
    print("[Manager] All workers have stopped. Exiting.")