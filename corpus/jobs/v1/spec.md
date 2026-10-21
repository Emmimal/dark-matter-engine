# Job Queue

## Enqueue
Producers call enqueue(job_id, payload). Enqueueing a job_id that already exists is ignored, so a producer can safely resend.

## Processing
A worker claims one job at a time and sends a heartbeat every 10 seconds while it runs the job.

## Failed jobs
If a job raises an error the worker reports the failure and the queue retries the job after a delay of 30 seconds, doubling on each attempt up to 5 attempts. After the fifth failure the job moves to the dead-letter list.
