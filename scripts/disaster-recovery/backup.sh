#!/usr/bin/env bash
# Audiobook Studio - Disaster Recovery Backup Script
# Usage: ./backup.sh [namespace] [release-name] [backup-dir]
# Example: ./backup.sh audiobook audiobook-studio /backups/$(date +%Y%m%d-%H%M%S)

set -euo pipefail

NAMESPACE="${1:-audiobook}"
RELEASE="${2:-audiobook-studio}"
BACKUP_DIR="${3:-/backups/$(date +%Y%m%d-%H%M%S)}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

echo "=== Audiobook Studio Backup ==="
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE"
echo "Backup Dir: $BACKUP_DIR"
echo "Timestamp: $TIMESTAMP"
echo ""

mkdir -p "$BACKUP_DIR"

# 1. Backup PostgreSQL
echo ">>> Backing up PostgreSQL..."
kubectl exec -n "$NAMESPACE" "${RELEASE}-postgresql-0" -- \
  pg_dump -U audiobook -d audiobook --no-owner --no-privileges > "$BACKUP_DIR/postgresql-dump.sql"
echo "PostgreSQL backup complete: $BACKUP_DIR/postgresql-dump.sql"

# 2. Backup Redis
echo ">>> Backing up Redis..."
kubectl exec -n "$NAMESPACE" "${RELEASE}-redis-master-0" -- \
  redis-cli --rdb - > "$BACKUP_DIR/redis-dump.rdb"
echo "Redis backup complete: $BACKUP_DIR/redis-dump.rdb"

# 3. Backup ChromaDB
echo ">>> Backing up ChromaDB..."
kubectl exec -n "$NAMESPACE" "${RELEASE}-chromadb-0" -- \
  tar czf - /chroma/chroma > "$BACKUP_DIR/chromadb-data.tar.gz"
echo "ChromaDB backup complete: $BACKUP_DIR/chromadb-data.tar.gz"

# 4. Backup Persistent Volumes (models, output, checkpoints, storage, logs)
echo ">>> Backing up Persistent Volumes..."
for PVC in models-cache output checkpoints storage logs; do
  PVC_NAME="${RELEASE}-${PVC}"
  echo "  Backing up PVC: $PVC_NAME"
  kubectl cp -n "$NAMESPACE" \
    "${RELEASE}-web-0:/app/$(echo $PVC | tr '-' '_')" \
    "$BACKUP_DIR/pvc-${PVC}.tar" 2>/dev/null || true
done
echo "PVC backups complete"

# 5. Backup Kubernetes Resources
echo ">>> Backing up Kubernetes resources..."
kubectl get -n "$NAMESPACE" all,configmap,secret,pvc,ingress,networkpolicy,hpa,pdb,servicemonitor,prometheusrule,role,rolebinding,serviceaccount -o yaml \
  -l "app.kubernetes.io/instance=$RELEASE" > "$BACKUP_DIR/k8s-resources.yaml"
echo "Kubernetes resources backup complete: $BACKUP_DIR/k8s-resources.yaml"

# 6. Backup Helm Values
echo ">>> Backing up Helm values..."
helm get values -n "$NAMESPACE" "$RELEASE" > "$BACKUP_DIR/helm-values.yaml"
echo "Helm values backup complete: $BACKUP_DIR/helm-values.yaml"

# 7. Create manifest
cat > "$BACKUP_DIR/MANIFEST.txt" <<MANIFEST
Audiobook Studio Backup Manifest
=================================
Timestamp: $TIMESTAMP
Namespace: $NAMESPACE
Release: $RELEASE
Kubernetes Version: $(kubectl version -o json | jq -r '.serverVersion.gitVersion' 2>/dev/null || echo "unknown")
Helm Version: $(helm version -o json | jq -r '.version' 2>/dev/null || echo "unknown")

Files:
- postgresql-dump.sql       : PostgreSQL database dump
- redis-dump.rdb            : Redis RDB snapshot
- chromadb-data.tar.gz      : ChromaDB vector database
- pvc-*.tar                 : Persistent volume contents
- k8s-resources.yaml        : All Kubernetes resources
- helm-values.yaml          : Helm release values
MANIFEST

echo ""
echo "=== Backup Complete ==="
echo "Backup directory: $BACKUP_DIR"
echo "Manifest: $BACKUP_DIR/MANIFEST.txt"
echo ""
echo "To restore, run: ./restore.sh $NAMESPACE $RELEASE $BACKUP_DIR"
