# Architecture Overview — AI Self-Healing CI/CD

## System Diagram

```
                           +------------------+
                           |   Developer      |
                           |   git push main  |
                           +--------+---------+
                                    |
                                    v
                    +-------------------------------+
                    |     GitHub Actions CI/CD      |
                    |-------------------------------|
                    | 1. Build & Test               |
                    | 2. Trivy Security Scan        |
                    | 3. Docker Build & Push (ACR)  |
                    | 4. Deploy to AKS / VPS        |
                    | 5. Health Check               |
                    +-------+-----------+-----------+
                            |           |
                     health OK     health FAIL
                            |           |
                            v           v
                    +----------+   +-----------------------+
                    |  Done    |   |  AI Self-Healer       |
                    |  (exit)  |   |  (scripts/ai_healer)  |
                    +----------+   +-----------+-----------+
                                               |
                              +----------------+----------------+
                              |                |                |
                              v                v                v
                        +---------+      +-----------+    +-----------+
                        |  RETRY  |      | ROLLBACK  |    | ESCALATE  |
                        | restart |      | to stable |    | alert ops |
                        +---------+      +-----------+    +-----------+
                              |                |
                              v                v
                        +--------------------------+
                        |   Post-Heal Verification |
                        +--------------------------+
                              |                |
                           success          failure
                              |                |
                              v                v
                       +----------+    +----------------+
                       | Log DORA |    | Escalate to    |
                       | + Audit  |    | human operator |
                       +----------+    +----------------+


  Monitoring Layer (always running):
  +------------------------------------------------------------+
  |  Prometheus          Grafana            OPA Gatekeeper      |
  |  (scrape /health)    (6 dashboards)     (policy enforce)    |
  |  (4 alert rules)     (auto-provision)   (labels + limits)   |
  +------------------------------------------------------------+
```

## Components

### Application (`app/`)

A Python Flask API that serves as the demo workload. It exposes a `/health`
endpoint used by Kubernetes probes, the CI/CD pipeline, and the AI healer to
determine application status. A `FAIL_MODE` environment variable can be toggled
to simulate a broken deployment.

Key endpoints:
- `GET /health` — Returns `200 healthy` or `500 unhealthy`
- `GET /` — Application info and available endpoints
- `GET /api/data` — Sample data (crashes when `FAIL_MODE=true`)
- `POST /api/process` — Processing endpoint (returns 503 when failing)

### AI Self-Healer (`scripts/ai_healer.py`)

The core intelligence of the system. When a deployment fails its health check,
this module:

1. Queries the `/health` endpoint to capture the failure state
2. Collects container logs (last 50 lines)
3. Sends both to OpenAI GPT-4o with a structured prompt
4. Receives a JSON decision: `RETRY`, `ROLLBACK`, or `ESCALATE`
5. Executes the decision automatically
6. Logs everything to the audit trail and DORA metrics tracker

Decision criteria:
- **RETRY** — Transient errors (timeouts, network blips, rate limits)
- **ROLLBACK** — Application errors (crashes, bad config, dependency failures)
- **ESCALATE** — Infrastructure issues (disk full, OOM, security, unknown errors)

### Audit Logger (`scripts/audit_log.py`)

Every AI decision is recorded in a structured JSONL file for compliance and
post-incident review. Each entry captures the full context: health status,
logs analyzed, the AI decision with confidence score, what action was taken,
and whether it succeeded. Entries can be queried by date, decision type, or
confidence threshold from the CLI.

### DORA Metrics Tracker (`scripts/dora_metrics.py`)

Tracks the four DORA metrics that measure software delivery performance:

| Metric | What It Measures | Elite Threshold |
|--------|-----------------|-----------------|
| Deployment Frequency | How often code reaches production | Multiple times per day |
| Lead Time for Changes | Commit to production deploy time | Less than 1 hour |
| Mean Time to Recovery | Time to restore service after failure | Less than 1 hour |
| Change Failure Rate | % of deploys causing incidents | Less than 5% |

Events are stored in `dora_events.json` and can be output in Prometheus
exposition format for dashboard integration.

### Blue/Green Deployments (`k8s/blue-green-deployment.yaml`)

Two identical Kubernetes deployments (blue and green) run side by side. A
single service routes production traffic to the active slot. Switching is
done by patching the service selector, providing instant rollback capability.

The flow:
1. New code is deployed to the **idle** slot
2. Health checks verify the idle slot is healthy
3. The `blue_green_switch.sh` script patches the service to the new slot
4. If post-switch health fails, traffic is instantly reverted

A **preview service** always points to the idle slot, enabling pre-switch
testing without affecting production traffic.

### OPA Gatekeeper Policies (`k8s/opa-gatekeeper.yaml`)

Two admission control policies enforced at the Kubernetes API level:

1. **Required Resource Limits** — Every container must declare CPU and memory
   limits. Prevents unbounded resource consumption.
2. **Required Labels** — All workloads must have `app`, `version`, and `team`
   labels. Enables consistent monitoring, cost allocation, and ownership.

Both policies use Rego rules and are enforced in `deny` mode, meaning
non-compliant resources are rejected at admission time.

### Monitoring Stack (`k8s/monitoring.yaml`)

Built on the Prometheus + Grafana stack (deployed via Helm):

**ServiceMonitor** — Scrapes `/health` every 15 seconds.

**Alert Rules** (4):
1. `AppUnhealthy` — App unreachable for 1+ minute (critical)
2. `HighErrorRate` — 5xx rate exceeds 10% for 2+ minutes (warning)
3. `HighCPUUsage` — CPU above 80% of limit for 5+ minutes (warning)
4. `PodRestarting` — More than 3 restarts in 1 hour (critical)

**Grafana Dashboard** (6 panels):
1. App Health Status (stat: up/down)
2. Request Rate by status code (time series)
3. Error Rate percentage (time series with thresholds)
4. Pod CPU Usage as % of limit (time series)
5. Pod Memory Usage in MiB (time series)
6. Pod Restarts in 1h window (stat with thresholds)

### Infrastructure (`terraform/main.tf`)

Terraform configuration for Azure AKS:
- Resource Group, Container Registry (ACR), AKS cluster
- Key Vault for secrets management
- Log Analytics workspace for monitoring
- ACR pull permissions for AKS, node autoscaling (1-3 nodes)

### CI/CD Pipeline (`.github/workflows/deploy.yml`)

Four-stage GitHub Actions workflow:

```
Stage 1: Build, Test & Security Scan
  - Python tests, Docker build, Trivy vulnerability scan, secret scanning

Stage 2: Deploy
  - Option A: Push to ACR, deploy to AKS with kubectl
  - Option B: SCP image to VPS, docker run (demo fallback)

Stage 3: Health Check & Compliance
  - Curl /health, verify 200, run compliance checks

Stage 4: AI Self-Healing (only on failure)
  - Triggered when Stage 3 fails
  - Runs ai_healer.py with OpenAI analysis
  - Verifies recovery after healing
```

## Flow: Push to Recovery

```
Developer pushes code
  |
  +--> GitHub Actions triggers
        |
        +--> Build + Test + Security scan
        |
        +--> Deploy to Kubernetes (or VPS)
        |
        +--> Health check at /health
              |
              +--> 200 OK --> Pipeline succeeds, record DORA deployment
              |
              +--> Non-200 --> AI Self-Healer triggered
                    |
                    +--> Collect logs + health data
                    |
                    +--> GPT-4o analyzes root cause
                    |
                    +--> Decision: RETRY / ROLLBACK / ESCALATE
                    |
                    +--> Execute decision automatically
                    |
                    +--> Log audit entry + DORA metrics
                    |
                    +--> Verify recovery
                          |
                          +--> Recovered --> Pipeline succeeds
                          +--> Still failing --> Escalate to human
```

## DORA Metrics

This project tracks all four DORA metrics to measure delivery performance:

**Deployment Frequency** is calculated from the number of `deployment` events
recorded per day. Each successful pipeline run records a deployment event.

**Lead Time for Changes** measures the time between a git commit and its
arrival in production. When the pipeline records a deployment, it includes the
commit timestamp to calculate the delta.

**Mean Time to Recovery (MTTR)** is calculated from `failure` and `recovery`
event pairs. When the AI healer detects a failure, it records the timestamp.
When it successfully recovers (via retry or rollback), it records the recovery
timestamp. The difference is the MTTR for that incident.

**Change Failure Rate** is the ratio of failure events to deployment events.
A deployment that triggers the AI healer counts as a failure, regardless of
whether the healer successfully recovers.

Classification thresholds follow the 2023 State of DevOps Report:

| Level | Deploy Freq | Lead Time | MTTR | Failure Rate |
|-------|-------------|-----------|------|-------------|
| Elite | Multiple/day | < 1 hour | < 1 hour | < 5% |
| High | Weekly-daily | < 1 day | < 1 day | 5-10% |
| Medium | Monthly-weekly | < 1 week | < 1 week | 10-30% |
| Low | < Monthly | > 1 week | > 1 week | > 30% |

## How to Run the Demo

### Prerequisites

- Docker and Docker Compose installed
- Python 3.11+ with pip
- OpenAI API key (for AI analysis)
- kubectl configured (for Kubernetes features)

### Quick Start (Docker)

```bash
# 1. Build and run the healthy application
docker-compose up -d --build

# 2. Verify it is healthy
curl http://localhost:9090/health

# 3. Simulate a broken deployment
docker stop selfheal-app && docker rm selfheal-app
docker run -d --name selfheal-app -p 9090:9090 \
  -e FAIL_MODE=true -e APP_VERSION=broken \
  selfheal-app:latest

# 4. Verify it is unhealthy
curl http://localhost:9090/health   # Returns 500

# 5. Run the AI self-healer
export OPENAI_API_KEY="your-key-here"
python scripts/ai_healer.py

# 6. Verify recovery
curl http://localhost:9090/health   # Returns 200 after rollback
```

### View Metrics and Audit Trail

```bash
# Record a test deployment
python scripts/dora_metrics.py record-deploy --version v1.0.0 --commit abc123

# View DORA metrics summary
python scripts/dora_metrics.py summary

# View Prometheus-format metrics
python scripts/dora_metrics.py prometheus

# View recent AI decisions
python scripts/audit_log.py recent

# Search for rollback decisions
python scripts/audit_log.py search --decision ROLLBACK

# View aggregate statistics
python scripts/audit_log.py stats
```

### Kubernetes Deployment

```bash
# Deploy the full stack
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/blue-green-deployment.yaml
kubectl apply -f k8s/monitoring.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/opa-gatekeeper.yaml

# Switch blue/green
./scripts/blue_green_switch.sh green

# View monitoring
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
# Open http://localhost:3000 (admin / admin123)
```

### Infrastructure Provisioning

```bash
cd terraform
terraform init
terraform plan -var="subscription_id=YOUR_SUB_ID"
terraform apply -var="subscription_id=YOUR_SUB_ID"
```

## File Structure

```
ai-selfheal-cicd/
|-- .github/
|   +-- workflows/
|       +-- deploy.yml              # 4-stage CI/CD pipeline
|-- app/
|   |-- main.py                     # Flask application
|   +-- requirements.txt            # Python dependencies
|-- docs/
|   |-- ARCHITECTURE.md             # This file
|   +-- INTERVIEW_SCENARIO.md       # Demo scenario guide
|-- k8s/
|   |-- argocd-app.yaml             # ArgoCD GitOps application
|   |-- blue-green-deployment.yaml  # Blue/green deployments + services
|   |-- deployment.yaml             # Standard rolling deployment
|   |-- hpa.yaml                    # Horizontal pod autoscaler
|   |-- keyvault.yaml               # Azure Key Vault integration
|   |-- monitoring.yaml             # Prometheus + Grafana + alerts
|   |-- network-policy.yaml         # Network ingress/egress rules
|   +-- opa-gatekeeper.yaml         # OPA admission policies
|-- scripts/
|   |-- ai_healer.py                # AI self-healing module (GPT-4o)
|   |-- audit_log.py                # AI decision audit logger
|   |-- blue_green_switch.sh        # Blue/green traffic switch
|   +-- dora_metrics.py             # DORA metrics tracker
|-- terraform/
|   +-- main.tf                     # Azure AKS infrastructure
|-- Dockerfile                      # Application container image
|-- docker-compose.yml              # Local development setup
|-- demo.py                         # Live demo automation script
+-- README.md                       # Project overview
```
