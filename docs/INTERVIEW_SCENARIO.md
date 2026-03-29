# Interview Demo Scenario: AI Self-Healing CI/CD Pipeline

## The Story You Tell

> "I built an AI-powered CI/CD pipeline that automatically detects deployment failures,
> analyzes the root cause using GPT-4o, and decides whether to retry, rollback, or
> escalate to a human. Here's a live demo."

## Demo Flow (5 minutes)

### Step 1: Show the Architecture (1 min)
- Open the README.md and show the architecture diagram
- Explain: "Push code → GitHub Actions builds → deploys to AKS → health check → AI monitors"

### Step 2: Happy Path (1 min)
- Show the app running: `curl http://<IP>:9090/health` → returns healthy
- Show GitHub Actions: last successful pipeline run with all 4 stages green

### Step 3: Break It (2 min)
- "Now I'll push a bad deployment"
- Change `FAIL_MODE=true` in deployment.yaml
- Push to main → GitHub Actions triggers
- Build passes ✅
- Deploy succeeds ✅
- Health check FAILS ❌
- **AI Self-Healing triggers automatically**

### Step 4: AI Recovery (1 min)
- Show the AI healer output:
  - "AI analyzed the logs and health check response"
  - "Decision: ROLLBACK (90% confidence)"
  - "Reason: Application is returning 500 errors"
  - "Suggested fix: Review recent configuration changes"
- Show the app recovered: `curl http://<IP>:9090/health` → healthy again
- "The pipeline self-healed without any human intervention"

## Key Talking Points

### When Asked "Why AI instead of simple retry logic?"
> "Traditional retry logic is binary - it either retries or fails. Our AI analyzes
> the actual error context: log patterns, error types, historical behavior. It can
> distinguish between a network blip (retry) and a code bug (rollback). It also
> provides suggested fixes for the development team."

### When Asked "What about security?"
> "Security is built into the pipeline:
> - Trivy scans every container image for CVEs before deployment
> - Secret scanning prevents hardcoded credentials
> - Network policies restrict pod-to-pod communication
> - The AI healer runs in a separate stage with minimal permissions"

### When Asked "How does this scale?"
> "The Kubernetes deployment uses HPA (Horizontal Pod Autoscaler) that scales
> from 2 to 5 replicas based on CPU/memory. The AKS cluster itself auto-scales
> from 1 to 3 nodes. The AI healer is stateless and runs as a GitHub Actions job."

### When Asked "What's the cost?"
> "For this demo: ~$20-30/month on Azure free tier. In production, AKS with
> 2 B2s nodes costs about $60-80/month. The AI analysis uses GPT-4o at
> approximately $0.01 per incident - negligible compared to downtime costs."

## Technical Details to Mention

| Component | Technology | Why |
|-----------|-----------|-----|
| Container | Docker | Industry standard, portable |
| Orchestration | AKS (Kubernetes) | Enterprise-grade, auto-scaling |
| CI/CD | GitHub Actions | GitOps, event-driven |
| IaC | Terraform | Multi-cloud, declarative |
| Security | Trivy + NetworkPolicies | Shift-left security |
| AI | OpenAI GPT-4o | Best reasoning for log analysis |
| Monitoring | Azure Log Analytics | Native AKS integration |

## Files to Show During Interview

1. `terraform/main.tf` - "Infrastructure as Code - one command deploys everything"
2. `.github/workflows/deploy.yml` - "4-stage pipeline with security scanning"
3. `k8s/deployment.yaml` - "Kubernetes manifests with health probes and resource limits"
4. `k8s/hpa.yaml` - "Auto-scaling configuration"
5. `k8s/network-policy.yaml` - "Zero-trust network security"
6. `scripts/ai_healer.py` - "The AI brain - analyzes logs and makes decisions"
