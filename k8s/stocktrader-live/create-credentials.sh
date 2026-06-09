#!/usr/bin/env bash
# LIVE T212 credentials — niet de demo-keys van papertrader gebruiken.

kubectl create secret generic stocktrader-credentials \
  --namespace stocktrader \
  --from-literal=FINAZON_API_KEY="VERVANG_MET_JOUW_FINAZON_KEY" \
  --from-literal=T212_API_KEY="VERVANG_MET_JOUW_T212_LIVE_KEY" \
  --from-literal=T212_API_SECRET="VERVANG_MET_JOUW_T212_LIVE_SECRET" \
  --from-literal=TELEGRAM_BOT_TOKEN="VERVANG_MET_JOUW_TELEGRAM_TOKEN" \
  --save-config \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Daarna: kubectl scale deployment/stocktrader-dashboard -n stocktrader --replicas=1"
