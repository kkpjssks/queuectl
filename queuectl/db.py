import sqlite3
import uuid
import json
from datetime import datetime
from .config import DB_PATH, is_worker_running

class JobQueue:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._create_schema()

    def _get_conn(self):
        """
        Establishes a connection to the SQLite database.
        Sets up for foreign keys, row factory, and WAL mode for
        better concurrency.
        """
        conn = sqlite3.connect(
            self.db_path, 
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=10 
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _create_schema(self):
        """Creates the 'jobs' and 'dlq' tables if they don't exist."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    run_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dlq (
                    id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    state TEXT DEFAULT 'dead',
                    attempts INTEGER,
                    max_retries INTEGER,
                    created_at TIMESTAMP,
                    failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def enqueue_job(self, job_data, config):
        """Adds a new job to the queue."""
        job_id = job_data.get("id", str(uuid.uuid4()))
        now = datetime.now()
        
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, command, max_retries, run_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_data["command"],
                    job_data.get("max_retries", config["max_retries"]),
                    now, 
                    now,
                    now
                )
            )
        return job_id

    def fetch_job(self):
        """
        Atomically fetches the next available job ('pending' or 'failed'
        and past its 'run_at' time) and sets its state to 'processing'.
        This is the critical concurrency-safe operation.
        """
        with self._get_conn() as conn:
            
            try:
                conn.execute("BEGIN IMMEDIATE")
                
                cursor = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE (state = 'pending' OR state = 'failed')
                      AND run_at <= ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (datetime.now(),)
                )
                job = cursor.fetchone()

                if job:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET state = 'processing', updated_at = ?
                        WHERE id = ?
                        """,
                        (datetime.now(), job['id'])
                    )
                    conn.commit()
                    return dict(job)
                else:
                    conn.commit() 
                    return None
                    
            except sqlite3.OperationalError as e:
                
                conn.rollback()
                return None

    def complete_job(self, job_id):
        """Marks a job as 'completed'."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET state = 'completed', updated_at = ?
                WHERE id = ?
                """,
                (datetime.now(), job_id)
            )

    def schedule_retry(self, job_id, attempts, next_run_at):
        """Marks a job as 'failed' and sets its next retry time."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET state = 'failed', attempts = ?, run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (attempts, next_run_at, datetime.now(), job_id)
            )

    def move_to_dlq(self, job):
        """Atomically moves a job from the main queue to the DLQ."""
        with self._get_conn() as conn:
            with conn: 
                conn.execute(
                    """
                    INSERT INTO dlq (id, command, attempts, max_retries, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (job['id'], job['command'], job['attempts'], job['max_retries'], job['created_at'])
                )
                conn.execute("DELETE FROM jobs WHERE id = ?", (job['id'],))

    def retry_dlq_job(self, job_id, config):
        """Atomically moves a job from the DLQ back to the main queue."""
        with self._get_conn() as conn:
            with conn: 
                cursor = conn.execute("SELECT * FROM dlq WHERE id = ?", (job_id,))
                job = cursor.fetchone()
                
                if not job:
                    return False 
                
                conn.execute(
                    """
                    INSERT INTO jobs (id, command, max_retries, run_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job['id'],
                        job['command'],
                        config["max_retries"], 
                        datetime.now(),       
                        job['created_at'],
                        datetime.now()        
                    )
                )
                conn.execute("DELETE FROM dlq WHERE id = ?", (job['id'],))
            return True

    def get_status(self):
        """Gets a summary of job states and worker status."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT state, COUNT(*) as count
                FROM jobs
                GROUP BY state
            """)
            job_stats = {row['state']: row['count'] for row in cursor.fetchall()}
            
            cursor = conn.execute("SELECT COUNT(*) as count FROM dlq")
            dlq_count = cursor.fetchone()['count']
            
        return {
            "workers_running": is_worker_running(),
            "jobs": job_stats,
            "dlq": dlq_count
        }

    def list_jobs(self, state):
        """Lists all jobs with a specific state."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at", (state,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_dlq(self):
        """Lists all jobs in the Dead Letter Queue."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM dlq ORDER BY failed_at")
            return [dict(row) for row in cursor.fetchall()]