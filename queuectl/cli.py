import click
import json
import uuid
import os
import signal
from . import __version__
from .config import (
    load_config, save_config, read_pid, remove_pid, DB_PATH
)
from .db import JobQueue
from .worker import start_workers

@click.group()
@click.version_option(version=__version__)
def cli():
    """
    queuectl: A CLI-based background job queue system.
    """
    pass


@cli.command()
@click.argument('job_json', type=str)
def enqueue(job_json):
    """
    Add a new job to the queue.
    
    JOB_JSON should be a JSON string, e.g.:
    '{"id":"job1", "command":"sleep 5"}'
    
    'id' is optional and will be auto-generated.
    """
    try:
        job_data = json.loads(job_json)
    except json.JSONDecodeError:
        click.echo("Error: Invalid JSON string.", err=True)
        return

    if "command" not in job_data:
        click.echo("Error: 'command' field is required in JSON.", err=True)
        return
        
    if "id" not in job_data:
        job_data["id"] = str(uuid.uuid4())

    config = load_config()
    queue = JobQueue(DB_PATH)
    
    try:
        job_id = queue.enqueue_job(job_data, config)
        click.echo(f"Job enqueued with ID: {job_id}")
    except Exception as e:
        click.echo(f"Error enqueuing job: {e}", err=True)



@click.group()
def worker():
    """Manage worker processes."""
    pass

@worker.command()
@click.option('--count', default=1, type=int, help='Number of worker processes to start.')
def start(count):
    """
    Start worker processes.
    
    This command runs in the foreground.
    Press Ctrl+C to stop gracefully.
    """
    if count < 1:
        click.echo("Error: Must start at least 1 worker.", err=True)
        return
    start_workers(count)

@worker.command()
def stop():
    """Stop running worker processes gracefully."""
    pid = read_pid()
    if not pid:
        click.echo("Workers not running (no PID file).")
        return
        
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to worker manager (PID: {pid}).")
    except ProcessLookupError:
        click.echo(f"Worker process (PID: {pid}) not found.")
        remove_pid() 
    except Exception as e:
        click.echo(f"Error stopping workers: {e}", err=True)

cli.add_command(worker)



@cli.command()
def status():
    """Show a summary of all job states & active workers."""
    queue = JobQueue(DB_PATH)
    stats = queue.get_status()
    
    click.echo("--- Worker Status ---")
    if stats["workers_running"]:
        click.secho(f"  Active (PID: {read_pid()})", fg="green")
    else:
        click.secho("  Stopped", fg="red")
        
    click.echo("\n--- Job Queue ---")
    total_jobs = 0
    for state in ['pending', 'processing', 'failed', 'completed']:
        count = stats["jobs"].get(state, 0)
        total_jobs += count
        click.echo(f"  {state.title()}: {count}")
    
    click.echo(f"  Total: {total_jobs}")

    click.echo("\n--- Dead Letter Queue ---")
    click.echo(f"  Dead: {stats['dlq']}")


@cli.command()
@click.option(
    '--state', 
    required=True, 
    type=click.Choice(['pending', 'processing', 'failed', 'completed'], case_sensitive=False)
)
def list(state):
    """List jobs by their state."""
    queue = JobQueue(DB_PATH)
    jobs = queue.list_jobs(state)
    
    if not jobs:
        click.echo(f"No jobs found with state: {state}")
        return
        
    for job in jobs:
        click.echo(f"ID: {job['id']} (Attempts: {job['attempts']})")
        click.echo(f"  Cmd: {job['command']}")
        click.echo(f"  Updated: {job['updated_at']}")
        click.echo("-" * 20)

@click.group()
def dlq():
    """Manage the Dead Letter Queue (DLQ)."""
    pass

@dlq.command()
def list():
    """List all jobs in the DLQ."""
    queue = JobQueue(DB_PATH)
    jobs = queue.list_dlq()
    
    if not jobs:
        click.echo("DLQ is empty.")
        return
        
    click.echo(f"--- DLQ Jobs ({len(jobs)}) ---")
    for job in jobs:
        click.echo(f"ID: {job['id']} (Failed at: {job['failed_at']})")
        click.echo(f"  Cmd: {job['command']}")
        click.echo(f"  Attempts: {job['attempts']}")
        click.echo("-" * 20)

@dlq.command()
@click.argument('job_id')
def retry(job_id):
    """Retry a specific job from the DLQ."""
    queue = JobQueue(DB_PATH)
    config = load_config()
    
    if queue.retry_dlq_job(job_id, config):
        click.echo(f"Job {job_id} moved back to queue as 'pending'.")
    else:
        click.echo(f"Error: Job {job_id} not found in DLQ.", err=True)

cli.add_command(dlq)


@click.group()
def config():
    """View or set configuration options."""
    pass

@config.command()
@click.argument('key', type=click.Choice(['max_retries', 'backoff_base']))
@click.argument('value', type=str)
def set(key, value):
    """Set a configuration value."""
    try:
        value = int(value)
    except ValueError:
        click.echo(f"Error: Value for {key} must be an integer.", err=True)
        return
        
    config = load_config()
    config[key] = value
    save_config(config)
    click.echo(f"Set {key} = {value}")

@config.command(name="show")
def show_config():
    """Show the current configuration."""
    config = load_config()
    click.echo(json.dumps(config, indent=2))

cli.add_command(config)


if __name__ == "__main__":
    cli()