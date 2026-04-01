#!/bin/bash
set -e

echo "============================================="
echo "  AI Self-Healing CI/CD - Azure Full Setup"
echo "============================================="

# Configuration
RESOURCE_GROUP="ai-selfheal-rg"
LOCATION="eastus"
AKS_CLUSTER="selfheal-aks"
ACR_NAME="selfhealacr2026"
NODE_COUNT=1
NODE_SIZE="Standard_B2s"

echo ""
echo "[1/8] Creating Resource Group..."
az group create --name $RESOURCE_GROUP --location $LOCATION -o none
echo "  ✅ Resource group created"

echo ""
echo "[2/8] Creating Container Registry (ACR)..."
az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic -o none
echo "  ✅ ACR created"

echo ""
echo "[3/8] Creating AKS Cluster (this takes 5-10 minutes)..."
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $AKS_CLUSTER \
  --node-count $NODE_COUNT \
  --node-vm-size $NODE_SIZE \
  --attach-acr $ACR_NAME \
  --generate-ssh-keys \
  --enable-managed-identity \
  -o none
echo "  ✅ AKS cluster created"

echo ""
echo "[4/8] Getting cluster credentials..."
az aks get-credentials --resource-group $RESOURCE_GROUP --name $AKS_CLUSTER --overwrite-existing
echo "  ✅ kubectl configured"

echo ""
echo "[5/8] Building and pushing app image to ACR..."
az acr build --registry $ACR_NAME --image selfheal-app:v1 --file Dockerfile .
echo "  ✅ App image pushed to ACR"

echo ""
echo "[6/8] Deploying app to AKS..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
echo "  Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=selfheal-app -n selfheal --timeout=120s
echo "  ✅ App deployed with 2 replicas"

echo ""
echo "[7/8] Installing ArgoCD..."
kubectl create namespace argocd 2>/dev/null || true
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
echo "  Waiting for ArgoCD to be ready..."
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s
kubectl patch svc argocd-server -n argocd -p '{"spec": {"type": "LoadBalancer"}}'
kubectl apply -f k8s/argocd-app.yaml
ARGOCD_PASS=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
echo "  ✅ ArgoCD installed"

echo ""
echo "[8/8] Installing Prometheus & Grafana..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set grafana.adminPassword=admin123 \
  --set grafana.service.type=LoadBalancer \
  --set prometheus.service.type=LoadBalancer \
  --wait --timeout 5m
echo "  ✅ Prometheus & Grafana installed"

echo ""
echo "============================================="
echo "  SETUP COMPLETE! Getting all URLs..."
echo "============================================="
echo ""

# Wait for LoadBalancers
sleep 30

APP_IP=$(kubectl get svc selfheal-app -n selfheal -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
ARGOCD_IP=$(kubectl get svc argocd-server -n argocd -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
GRAFANA_IP=$(kubectl get svc prometheus-grafana -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
PROM_IP=$(kubectl get svc prometheus-kube-prometheus-prometheus -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

echo "  APP:        http://$APP_IP"
echo "  APP HEALTH: http://$APP_IP/health"
echo "  APP DATA:   http://$APP_IP/api/data"
echo ""
echo "  ARGOCD:     https://$ARGOCD_IP"
echo "  ARGOCD USER: admin"
echo "  ARGOCD PASS: $ARGOCD_PASS"
echo ""
echo "  GRAFANA:    http://$GRAFANA_IP"
echo "  GRAFANA USER: admin"
echo "  GRAFANA PASS: admin123"
echo ""
echo "  PROMETHEUS: http://$PROM_IP:9090"
echo ""
echo "  AZURE PORTAL: https://portal.azure.com"
echo ""
echo "============================================="
echo "  All done! If any IP shows 'pending',"
echo "  wait 2 min and run:"
echo "  kubectl get svc --all-namespaces"
echo "============================================="
