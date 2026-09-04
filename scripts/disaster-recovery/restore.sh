#!/usr/bin/env bash
# Audiobook Studio - Disaster Recovery Restore Script
# Usage: ./restore.sh [namespace] [release-name] [backup-dir]
# Example: ./restore.sh audiobook audiobook-studio /backups/20240824-120000

set -euo pipefail

NAMESPACE="${1:-audiobook}"
RELEASE="${2:-audiobook-studio}"
BACKUP_DIR="${3:-}"

if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  echo "Error: Backup directory required and must exist"
  echo "Usage: $0 [namespace] [release-name] [backup-dir]"
  exit 1
fi

echo "=== Audiobook Studio Restore ==="
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE"
echo "Backup Dir: $BACKUP_DIR"
echo ""

# Verify backup exists
if [[ ! -f "$BACKUP_DIR/MANIFEST.txt" ]]; then
  echo "Error: Invalid backup directory (no MANIFEST.txt)"
  exit 1
fi

cat "$BACKUP_DIR/MANIFEST.txt"
echo ""

read -p "This will OVERWRITE existing data. Continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Aborted."
  exit 1
fi

# 1. Scale down deployments
echo ">>> Scaling down deployments..."
kubectl scale deployment -n "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE" --replicas=0
sleep 10

# 2. Restore PostgreSQL
echo ">>> Restoring PostgreSQL..."
if [[ -f "$BACKUP_DIR/postgresql-dump.sql" ]]; then
  kubectl exec -i -n "$NAMESPACE" "${RELEASE}-postgresql-0" -- \
    psql -U audiobook -d audiobook < "$BACKUP_DIR/postgresql-dump.sql"
  echo "PostgreSQL restore complete"
else
  echo "Warning: No PostgreSQL dump found"
fi

# 3. Restore Redis
echo ">>> Restoring Redis..."
if [[ -f "$BACKUP_DIR/redis-dump.rdb" ]]; then
  kubectl cp "$BACKUP_DIR/redis-dump.rdb" "$NAMESPACE/${RELEASE}-redis-master-0:/data/dump.rdb"
  kubectl exec -n "$NAMESPACE" "${RELEASE}-redis-master-0" -- redis-cli SHUTDOWN NOSAVE
  sleep 5
  echo "Redis restore complete (pod will restart with new data)"
else
  echo "Warning: No Redis dump found"
fi

# 4. Restore ChromaDB
echo ">>> Restoring ChromaDB..."
if [[ -f "$BACKUP_DIR/chromadb-data.tar.gz" ]]; then
  kubectl exec -n "$NAMESPACE" "${RELEASE}-chromadb-0" -- \
    tar xzf - -C / < "$BACKUP_DIR/chromadb-data.tar.gz"
  echo "ChromaDB restore complete"
else
  echo "Warning: No ChromaDB backup found"
fi

# 5. Restore PVCs
echo ">>> Restoring Persistent Volumes..."
for PVC in models-cache output checkpoints storage logs; do
  TAR_FILE="$BACKUP_DIR/pvc-${PVC}.tar"
  if [[ -f "$TAR_FILE" ]]; then
    echo "  Restoring PVC: $PVC"
    kubectl cp "$TAR_FILE" "$NAMESPACE/${RELEASE}-web-0:/app/$(echo $PVC | tr '-' '_')" 2>/dev/null || true
  fi
done
echo "PVC restores complete"

# 6. Restore Kubernetes Resources (optional - usually managed by Helm)
echo ">>> Kubernetes resources managed by Helm - skipping direct restore"
echo "    To fully restore, re-run: helm upgrade --install -f $BACKUP_DIR/helm-values.yaml $RELEASE helm/audiobook-studio -n $NAMESPACE"

# 7. Scale up deployments
echo ">>> Scaling up deployments..."
kubectl scale deployment -n "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE" --replicas=2

echo ""
echo "=== Restore Complete ==="
echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l "app.kubernetes.io/instance=$RELEASE" -n "$NAMESPACE" --timeout=300s
echo "All pods ready!"
