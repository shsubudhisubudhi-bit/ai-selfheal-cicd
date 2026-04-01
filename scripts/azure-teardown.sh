#!/bin/bash
echo "============================================="
echo "  AI Self-Healing CI/CD - Azure Teardown"
echo "============================================="
echo ""
echo "This will DELETE everything in ai-selfheal-rg"
echo ""
read -p "Are you sure? (y/n): " confirm
if [ "$confirm" != "y" ]; then
  echo "Cancelled."
  exit 0
fi
echo ""
echo "Deleting resource group (takes 5-10 minutes)..."
az group delete --name ai-selfheal-rg --yes --no-wait
echo "✅ Deletion started. Check Azure Portal for progress."
echo ""
echo "To verify deletion is complete:"
echo "  az group exists --name ai-selfheal-rg"
echo "  (should return 'false')"
