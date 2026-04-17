# Quick Start Guide — End-to-End Deployment

Complete deployment in 5 steps. Run each block in sequence on **Azure Cloud Shell**.

---

## Step 1 — Create Infrastructure (5-10 min)

```bash
# Login (only if cloud shell prompts)
az login --use-device-code

# Delete existing resource group if present
az group delete --name ai-selfheal-rg --yes 2>/dev/null
sleep 60

# Create all infra
az group create --name ai-selfheal-rg --location westus2

az acr create \
  --resource-group ai-selfheal-rg \
  --name selfhealacr042026 \
  --sku Basic \
  --admin-enabled true

az aks create \
  --resource-group ai-selfheal-rg \
  --name selfheal-aks \
  --node-count 2 \
  --node-vm-size Standard_D2s_v3 \
  --generate-ssh-keys \
  --enable-managed-identity \
  -o none

az aks get-credentials \
  --resource-group ai-selfheal-rg \
  --name selfheal-aks \
  --overwrite-existing

az aks update \
  -g ai-selfheal-rg \
  -n selfheal-aks \
  --attach-acr selfhealacr042026
```

---

## Step 2 — Trigger the CI/CD Pipeline

The pipeline builds the Docker image and deploys the app. The easiest way to trigger it:

**Option A — edit a file on GitHub UI:**
1. Go to https://github.com/shsubudhisubudhi-bit/ai-selfheal-cicd
2. Open `README.md`, click pencil, add a space
3. Commit to master

**Option B — from your laptop (if git is configured):**
```bash
git clone https://github.com/shsubudhisubudhi-bit/ai-selfheal-cicd.git
cd ai-selfheal-cicd
echo "" >> README.md
git add . && git commit -m "trigger pipeline" && git push origin master
```

Watch the pipeline: https://github.com/shsubudhisubudhi-bit/ai-selfheal-cicd/actions

It takes ~3-4 minutes. Pipeline does:
1. Build Docker image
2. Run Trivy security scan
3. Push to your ACR
4. Deploy to AKS (creates acr-secret automatically now)
5. Health check
6. AI Self-Healing (only if health check fails)

---

## Step 3 — Install ArgoCD

```bash
kubectl create namespace argocd 2>/dev/null
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml 2>/dev/null || true

kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s

kubectl patch svc argocd-server -n argocd -p '{"spec": {"type": "LoadBalancer"}}'

# Apply the Argo application so it watches the GitHub repo
kubectl apply -f https://raw.githubusercontent.com/shsubudhisubudhi-bit/ai-selfheal-cicd/master/k8s/argocd-app.yaml
```

---

## Step 4 — Install Monitoring (Prometheus + Grafana)

Free Azure accounts limit Public IPs, so use **ClusterIP** for monitoring and access via port-forward.

```bash
helm uninstall prometheus -n monitoring 2>/dev/null

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null
helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin123 \
  --set grafana.service.type=ClusterIP \
  --set prometheus.service.type=ClusterIP \
  --wait --timeout 15m
```

Wait for all monitoring pods to be Running:
```bash
kubectl get pods -n monitoring
```

---

## Step 5 — Get All URLs and Credentials

```bash
# Wait 60s for LoadBalancer IPs to be assigned
sleep 60

echo "============================================="
echo "APP:"
echo "  http://$(kubectl get svc selfheal-app -n selfheal -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
echo "  /health - app health check"
echo "  /api/data - sample data endpoint"
echo ""
echo "ARGOCD:"
echo "  URL: https://$(kubectl get svc argocd-server -n argocd -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
echo "  User: admin"
echo "  Pass: $(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
echo ""
echo "GRAFANA (access via port-forward):"
echo "  Run: kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80"
echo "  Open http://localhost:3000 (or use Cloud Shell Web Preview port 3000)"
echo "  User: admin"
echo "  Pass: admin123"
echo ""
echo "PROMETHEUS (access via port-forward):"
echo "  Run: kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090"
echo "  Open http://localhost:9090 (or use Cloud Shell Web Preview port 9090)"
echo "============================================="
```

---

## Testing AI Self-Healing

To demo the AI self-healing feature:

1. Edit `k8s/deployment.yaml` line 33: change `FAIL_MODE: "false"` to `FAIL_MODE: "true"`
2. Commit and push to master
3. Pipeline will run: build → deploy → health check FAILS (intentional) → AI Self-Healing triggers
4. GPT-4o analyzes logs, decides ROLLBACK with ~90% confidence
5. `kubectl rollout undo` executes automatically
6. App recovers

Watch it live in the pipeline logs at GitHub Actions.

---

## Teardown

To delete everything:
```bash
az group delete --name ai-selfheal-rg --yes
```

Takes ~5-10 minutes.

---

## Troubleshooting

**Pipeline times out on "Deploy to AKS":**
- Pods may take longer than 300s if the image is large. Already bumped timeout from 120s to 300s.

**"acr-secret not found" warning:**
- Fixed: pipeline now creates the secret automatically on every deploy.

**Grafana/Prometheus LoadBalancer stuck in `<pending>`:**
- Azure free tier limits Public IPs. We now use ClusterIP + port-forward. See Step 5.

**ArgoCD password empty in script output:**
- Use the command in Step 5 directly. Don't rely on shell variables across multiple commands.

**"Context deadline exceeded" on helm install:**
- Cluster undersized. Scale to 2 nodes (already in Step 1) and use `--timeout 15m`.
