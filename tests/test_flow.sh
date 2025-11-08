#!/bin/bash
set -e 

if [ ! -f "setup.py" ]; then
    echo "Please run this script from the project root directory."
    exit 1
fi

echo "--- 1. Cleaning up previous runs ---"

if command -v deactivate &> /dev/null; then
    deactivate
fi


pip install -e . > /dev/null
echo "Installed/Updated queuectl."


rm -f ~/.queuectl/queue.db ~/.queuectl/config.json ~/.queuectl/worker.pid
echo "Cleaned up old files."

echo "--- 2. Setting config ---"
queuectl config set max_retries 2
queuectl config set backoff_base 1 
queuectl config show

echo "--- 3. Enqueuing jobs ---"
queuectl enqueue '{"id":"job1", "command":"echo job1 complete && touch job1.txt"}'
queuectl enqueue '{"id":"job2", "command":"sleep 1 && echo job2 complete && touch job2.txt"}'
queuectl enqueue '{"id":"job-fail", "command":"exit 1"}' 
queuectl enqueue '{"id":"job-bad-cmd", "command":"command_not_found_test"}' 
rm -f job1.txt job2.txt 

echo "--- 4. Initial Status Check ---"
queuectl status


echo "--- 5. Starting 2 workers in background ---"
queuectl worker start --count 2 &
WORKER_PID=$!
echo "Workers started with manager PID $WORKER_PID. Waiting 8s for processing..."
sleep 8 

echo "--- 6. Stopping workers ---"
queuectl worker stop
wait $WORKER_PID 
echo "Workers stopped."

echo "--- 7. Final Status Check ---"
queuectl status


echo "--- 8. Verifying job execution ---"
if [ ! -f "job1.txt" ] || [ ! -f "job2.txt" ]; then
    echo "TEST FAILED: Output files (job1.txt, job2.txt) not created."
    exit 1
else
    echo "Job output files verified."
    rm job1.txt job2.txt
fi

echo "--- 9. Verifying DLQ ---"
queuectl dlq list

echo "--- 10. Retrying a DLQ job ---"
queuectl dlq retry job-fail

echo "--- 11. Status after DLQ retry ---"
queuectl status


echo "--- 12. Starting workers again to process retried job ---"
queuectl worker start --count 1 &
WORKER_PID=$!
sleep 4 
queuectl worker stop
wait $WORKER_PID
echo "Workers stopped."

echo "--- 13. Final DLQ check ---"
queuectl status

queuectl dlq list

echo ""
echo " --- TEST COMPLETE --- "
echo "All core flows (enqueue, work, retry, dlq, config) seem operational."