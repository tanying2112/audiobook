# Audiobook Studio - Production Runbook

## Overview
This runbook covers operational procedures for Audiobook Studio v1.0 GA in production Kubernetes.

## Architecture
- **Web API** (2+ replicas): FastAPI application, port 8000, metrics 9090
- **Celery Workers** (1+ replicas): Background job processing (export, pipeline queues)
- **PostgreSQL 16**: Primary database (20Gi PVC)
- **Redis 7**: Celery broker + result backend (5Gi PVC)
- **ChromaDB 0.4.22**: Vector database for RAG (10Gi PVC)
- **Monitoring**: Prometheus ServiceMonitors, Grafana dashboards, AlertManager

## Quick Reference

| Component | Port | Health Endpoint |
|-----------|------|-----------------|
| Web API | 8000 | /health/live, /health/ready |
| Web Metrics | 9090 | /metrics |
| PostgreSQL | 5432 | pg_isready |
| Redis | 6379 | redis-cli ping |
| ChromaDB | 8000 | /api/v1/heartbeat |

## Common Operations

### Check System Health
```bash
# All pods
kubectl get pods -n audiobook -l app.kubernetes.io/instance=audiobook-studio

# Web API health
kubectl exec -n audiobook deploy/audiobook-studio-web -- curl -sf localhost:8000/health/ready

# Worker health (check Celery)
kubectl exec -n audiobook deploy/audiobook-studio-worker -- celery -A src.audiobook_studio.celery_app inspect ping

# Database
kubectl exec -n audiobook audiobook-studio-postgresql-0 -- pg_isready -U audiobook

# Redis
kubectl exec -n audiobook audiobook-studio-redis-master-0 -- redis-cli ping

# ChromaDB
kubectl exec -n audiobook audiobook-studio-chromadb-0 -- curl -sf localhost:8000/api/v1/heartbeat
```

### View Logs
```bash
# Web API
kubectl logs -n audiobook -l component=web -f --tail=100

# Worker
kubectl logs -n audiobook -l component=worker -f --tail=100

# PostgreSQL
kubectl logs -n audiobook audiobook-studio-postgresql-0 -f --tail=100
```

### Scale Deployments
```bash
# Scale web (2-10 via HPA, manual override)
kubectl scale deployment audiobook-studio-web -n audiobook --replicas=4

# Scale worker
kubectl scale deployment audiobook-studio-worker -n audiobook --replicas=3
```

### Rolling Restart
```bash
# Web
kubectl rollout restart deployment/audiobook-studio-web -n audiobook

# Worker
kubectl rollout restart deployment/audiobook-studio-worker -n audiobook

# Check status
kubectl rollout status deployment/audiobook-studio-web -n audiobook
```

### Update Image
```bash
# Build and push new image
docker build -t audiobook-studio:v1.0.1 .
docker push registry.example.com/audiobook-studio:v1.0.1

# Update via Helm
helm upgrade audiobook-studio helm/audiobook-studio -n audiobook \
  --set web.image.tag=v1.0.1 --set worker.image.tag=v1.0.1
```

## Incident Response

### High Error Rate (Alert: HighErrorRate)
1. Check web logs: kubectl logs -n audiobook -l component=web --tail=200 | grep -i error
2. Check worker logs for pipeline failures
3. Check database connectivity
4. Check external API quotas (OpenAI, Anthropic)
5. If persistent, consider rollback: helm rollback audiobook-studio -n audiobook

### High Latency (Alert: HighLatency)
1. Check HPA status: kubectl get hpa -n audiobook
2. Check resource usage: kubectl top pods -n audiobook
3. Check database query performance
4. Consider scaling up: kubectl scale deployment audiobook-studio-web -n audiobook --replicas=5

### Pipeline Failure (Alert: PipelineFailure)
1. Check failed pipeline in web UI or API: GET /api/v1/pipelines?status=failed
2. Check worker logs for specific error
3. Common causes:
   - LLM API quota exceeded
   - TTS engine failure (Kokoro/Modal)
   - Disk space full (check PVC usage)
4. Retry failed pipeline via API or UI

### Free Tier Quota Low (Alert: FreeTierQuotaLow)
1. Check quota
2. Options:
   - Add API keys to secrets
   - Enable paid tier
   - Reduce concurrent jobs

### Database Issues
```bash
# Check connections
kubectl exec -n audiobook audiobook-studio-postgresql-0 -- psql -U audiobook -c "SELECT count(*) FROM pg_stat_activity;"

# Check locks
kubectl exec -n audiobook audiobook-studio-postgresql-0 -- psql -U audiobook -c "SELECT * FROM pg_locks WHERE NOT granted;"

# Vacuum analyze
kubectl exec -n audiobook audiobook-studio-postgresql-0 -- psql -U audiobook -c "VACUUM ANALYZE;"
```

### Redis Issues
```bash
# Check memory
kubectl exec -n audiobook audiobook-studio-redis-master-0 -- redis-cli INFO memory

# Check queue lengths
kubectl exec -n audiobook audiobook-studio-redis-master-0 -- redis-cli LLEN celery:queue:export
kubectl exec -n audiobook audiobook-studio-redis-master-0 -- redis-cli LLEN celery:queue:pipeline

# Flush queue (CAREFUL)
kubectl exec -n audiobook audiobook-studio-redis-master-0 -- redis-cli FLUSHDB
```

### Disk Space Issues
```bash
# Check PVC usage
kubectl exec -n audiobook -l component=web -- df -h /app/output /app/storage /app/checkpoints /app/models_cache /app/logs

# Clean old outputs (retention policy)
kubectl exec -n audiobook -l component=web -- find /app/output -type f -mtime +30 -delete
kubectl exec -n audiobook -l component=web -- find /app/checkpoints -type f -mtime +7 -delete
```

## Backup & Restore

### Scheduled Backup (CronJob)
```yaml
# Apply backup cronjob
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: CronJob
metadata:
  name: audiobook-studio-backup
  namespace: audiobook
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: audiobook-studio
          containers:
          - name: backup
            image: bitnami/kubectl:latest
            command: ["/bin/bash", "-c"]
            args: ["curl -sSL https://raw.githubusercontent.com/.../backup.sh | bash -s audiobook audiobook-studio /backups/$(date +%Y%m%d-%H%M%S)"]
            volumeMounts:
            - name: backup-storage
              mountPath: /backups
          volumes:
          - name: backup-storage
            persistentVolumeClaim:
              claimName: audiobook-studio-backup-pvc
          restartPolicy: OnFailure
EOF
```

### Manual Backup
```bash
./scripts/disaster-recovery/backup.sh audiobook audiobook-studio /backups/$(date +%Y%m%d-%H%M%S)
```

### Manual Restore
```bash
./scripts/disaster-recovery/restore.sh audiobook audiobook-studio /backups/20240824-020000
```

## Disaster Recovery Procedures

### Complete Cluster Loss
1. Provision new Kubernetes cluster
2. Install cert-manager, ingress-nginx, Prometheus Operator
3. Create namespace: kubectl create namespace audiobook
4. Create secrets from backup or vault
5. Install Helm chart: helm install audiobook-studio helm/audiobook-studio -n audiobook -f helm-values.yaml
6. Restore data: ./restore.sh audiobook audiobook-studio /backups/latest
7. Verify all health endpoints
8. Update DNS to point to new ingress

### Regional Failover
- Pre-provision DR cluster in alternate region
- Replicate PVCs via CSI snapshot replication (cloud provider)
- Automate failover with ArgoCD or Flux

## Security Procedures

### Rotate Secrets
```bash
# Generate new JWT secret
NEW_JWT=$(openssl rand -base64 32)
kubectl create secret generic audiobook-secrets -n audiobook \
  --from-literal=jwt-secret="$NEW_JWT" \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart pods to pick up new secret
kubectl rollout restart deployment -n audiobook -l app.kubernetes.io/instance=audiobook-studio
```

### Certificate Renewal
- cert-manager handles Let's Encrypt renewal automatically
- Monitor: kubectl get certificaterequests -n audiobook

## Monitoring & Alerting

### Grafana Dashboards
- Audiobook Studio: Main dashboard (import from helm/audiobook-studio/values.yaml)
- Kubernetes: Cluster overview
- PostgreSQL: Database metrics
- Redis: Cache metrics

### Key Metrics to Watch
| Metric | Normal Range | Alert Threshold |
|--------|--------------|-----------------|
| HTTP p95 latency | < 500ms | > 5000ms |
| Error rate | < 1% | > 5% |
| Pipeline success rate | > 99% | < 95% |
| Free tier quota | > 50% | < 10% |
| Disk usage | < 70% | > 85% |
| Memory usage | < 70% | > 85% |
| CPU usage | < 60% | > 80% |

### Alert Contacts
- Critical: PagerDuty / OpsGenie
- Warning: Slack #audiobook-alerts

## Maintenance Windows
- Weekly: Sunday 03:00-05:00 UTC (automated updates)
- Monthly: First Sunday 02:00-06:00 UTC (OS patches, DB maintenance)
- Quarterly: DR drill, backup restore test

## Version Upgrade Procedure
1. Review release notes and CHANGELOG
2. Test in staging environment
3. Backup production: ./backup.sh
4. Upgrade Helm chart: helm upgrade audiobook-studio helm/audiobook-studio -n audiobook -f values.yaml
5. Monitor rollout: kubectl rollout status deployment/audiobook-studio-web -n audiobook --timeout=600s
6. Run smoke tests: ./scripts/smoke_test.sh
7. Update documentation

## Contacts
- Platform Team: platform@company.com
- Development Team: dev@company.com
- On-Call: Check PagerDuty schedule

## Related Documents
- Deployment Guide (deployment.md)
- Architecture (architecture.md)
- API Reference (api_reference.md)
- Helm Chart Values (helm/audiobook-studio/values.yaml)
