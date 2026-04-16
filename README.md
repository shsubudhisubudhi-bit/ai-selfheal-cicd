# AI Self-Healing CI/CD Pipeline

An intelligent CI/CD pipeline that uses GPT-4o to automatically detect, analyze, and recover from deployment failures. Built with Kubernetes (AKS), Terraform, GitHub Actions, and DevSecOps best practices.
New account configured S49340134  new acr selfheal042006 fix by Fabian the acr point to this acr.

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────┐
│  Developer   │────▶│         GitHub Actions                │
│  git push    │     │                                      │
└─────────────┘     │  ┌────────┐  ┌────────┐  ┌────────┐ │
                    │  │ Build  │─▶│Security│─▶│ Push   │ │
                    │  │ & Test │  │ Scan   │  │ to ACR │ │
                    │  └────────┘  └────────┘  └───┬────┘ │
                    └──────────────────────────────┬──────┘
                                                   │
                    ┌──────────────────────────────▼──────┐
                    │           Azure AKS Cluster          │
                    │                                      │
                    │     ┌──────────────┐                │
                    │     │ LoadBalancer │  ◄── Internet  │
                    │     │   Service    │                │
                    │     └──────┬───────┘                │
                    │            │ routes traffic to       │
                    │       ┌────┴─────┐                  │
                    │       ▼          ▼                  │
                    │  ┌─────────┐  ┌─────────┐           │
                    │  │ Pod 1   │  │ Pod 2   │  (HPA)    │
                    │  │ :9090   │  │ :9090   │  2-5 pods │
                    │  └─────────┘  └─────────┘           │
                    └──────────────────────────────────────┘
                                   │
                          ┌────────┴────────┐
                          │  Health Check   │
                          └────────┬────────┘
                                   │
                       ┌───────────┴───────────┐
                       │                       │
                    ✅ Pass               ❌ Fail
                       │                       │
                       ▼                       ▼
                ┌────────────┐        ┌──────────────┐
                │  Success!  │        │  AI Healer   │
                │  Pipeline  │        │  (GPT-4o)    │
                │  Complete  │        └──────┬───────┘
                └────────────┘               │
                                   ┌─────────┼─────────┐
                                   ▼         ▼         ▼
                               RETRY    ROLLBACK   ESCALATE
```

## Project Structure

```
.
├── app/
│   ├── main.py              # Flask API (health, data, process endpoints)
│   └── requirements.txt     # Python dependencies
├── k8s/
│   ├── deployment.yaml      # K8s Deployment + Service + Ingress
│   ├── hpa.yaml             # Horizontal Pod Autoscaler (2-5 replicas)
│   └── network-policy.yaml  # Zero-trust network policies
├── terraform/
│   └── main.tf              # Azure AKS + ACR + Log Analytics
├── scripts/
│   └── ai_healer.py         # AI self-healing module (GPT-4o)
├── docs/
│   └── INTERVIEW_SCENARIO.md # Demo walkthrough for interviews
├── .github/workflows/
│   └── deploy.yml           # 4-stage CI/CD pipeline
├── Dockerfile               # Multi-stage container build
├── docker-compose.yml       # Local development
└── README.md
```

## Pipeline Stages

| Stage | What It Does | Tools |
|-------|-------------|-------|
| **1. Build & Security** | Build image, run tests, Trivy scan, secret detection | Docker, Trivy, pytest |
| **2. Deploy** | Push to ACR, deploy to AKS with rolling update | kubectl, AKS |
| **3. Health & Compliance** | Verify health endpoint, compliance checks | curl, custom checks |
| **4. AI Self-Heal** | If failure: analyze logs with GPT-4o, auto-recover | OpenAI, Python |

## DevSecOps Features

- **Container scanning**: Trivy checks for CVEs (CRITICAL/HIGH) before deploy
- **Secret scanning**: Detects hardcoded passwords/keys in source code
- **Network policies**: Restricts pod communication (zero-trust)
- **Resource limits**: CPU/memory limits prevent resource exhaustion
- **Rolling updates**: Zero-downtime deployments with rollback capability
- **Health probes**: Liveness + readiness probes for pod health

## Quick Start

```bash
# Local development
cd app && pip install -r requirements.txt
python main.py

# Docker
docker-compose up --build

# Test health
curl http://localhost:9090/health

# Simulate failure
FAIL_MODE=true docker-compose up --build
```

## Azure Deployment

```bash
# 1. Deploy infrastructure
cd terraform
terraform init
terraform apply -var="subscription_id=YOUR_SUB_ID"

# 2. Get AKS credentials
az aks get-credentials --resource-group ai-selfheal-rg --name ai-selfheal-aks

# 3. Deploy application
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/network-policy.yaml
```

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Server IP (for VPS fallback) |
| `DEPLOY_PASSWORD` | Server SSH password |
| `OPENAI_API_KEY` | OpenAI API key for AI healer |
| `AZURE_CREDENTIALS` | Azure service principal (for AKS) |

## AI Self-Healing Decisions

| Decision | When | Example |
|----------|------|---------|
| **RETRY** | Transient errors | Network timeout, rate limit |
| **ROLLBACK** | Application errors | Code crash, config error |
| **ESCALATE** | Infrastructure issues | Disk full, out of memory |
# Pipeline test Sat Apr  4 09:34:30 ESAST 2026
