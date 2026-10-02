from prometheus_client import Counter, Histogram

# Time to submit a training Job to the K8s API (not the job's actual run time -
job_creation_latency_seconds = Histogram(
    "training_job_creation_latency_seconds",
    "Time to create a training Job via the K8s API",
)

# Labeled by outcome so submission failures are visible without parsing logs.
jobs_submitted_total = Counter(
    "training_jobs_submitted_total",
    "Training jobs submitted, by outcome",
    ["status", "gpu"],
)