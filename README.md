# AI Self-Healing CI/CD Pipeline

An intelligent CI/CD pipeline that uses GPT-4o to automatically detect, analyze, and recover from deployment failures.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Developer   │────▶│   GitHub     │────▶│   Docker    │
│  git push    │     │   Actions    │     │   Build     │
└─────────────┘     └──────┬───────┘     └──────┬──────┘
                           │                     │
                           ▼                     ▼
                    ┌──────────────┐     ┌─────────────┐
                    │   Deploy     │────▶│   Health    │
                    │   to Host    │     │   Check     │
                    └──────────────┘     └──────┬──────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │                       │
                                 ✅ Pass               ❌ Fail
                                    │                       │
                                    ▼                       ▼
                             ┌────────────┐        ┌──────────────┐
                             │  Success!  │        │  AI Healer   │
                             │  Deploy    │        │  (GPT-4o)    │
                             │  Complete  │        └──────┬───────┘
                             └────────────┘               │
                                                ┌─────────┼─────────┐
                                                ▼         ▼         ▼
                                            RETRY    ROLLBACK   ESCALATE
                                              │         │          │
                                              ▼         ▼          ▼
                                          Restart   Previous    Alert
                                          Container  Version    Team
```

## Components

| Component | Description |
|-----------|-------------|
| `app/main.py` | Flask API with health endpoint and failure modes |
| `Dockerfile` | Container definition |
| `scripts/ai_healer.py` | AI self-healing module (GPT-4o analysis) |
| `.github/workflows/deploy.yml` | CI/CD pipeline with 4 stages |
| `terraform/main.tf` | Azure infrastructure as code |

## How It Works

1. **Push code** → GitHub Actions triggers
2. **Build** → Docker image created and tested
3. **Deploy** → Image pushed to server, container started
4. **Health Check** → Verify app is running
5. **If failure** → AI analyzes logs and decides:
   - **RETRY** → Restart container (transient errors)
   - **ROLLBACK** → Revert to previous stable version
   - **ESCALATE** → Alert human (critical errors)

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

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Server IP address |
| `DEPLOY_PASSWORD` | Server SSH password |
| `OPENAI_API_KEY` | OpenAI API key for AI analysis |

## Azure Deployment

```bash
cd terraform
terraform init
terraform apply -var="subscription_id=YOUR_SUB_ID"
```

## Demo Flow

1. Push working code → Pipeline succeeds ✅
2. Push broken code (FAIL_MODE=true) → Health check fails ❌
3. AI Self-Healing triggers → Analyzes error with GPT-4o
4. AI decides ROLLBACK → Reverts to stable version ✅
5. App recovers automatically 🎉
