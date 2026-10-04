# Audiobook Studio v1.0.0 - General Availability Release Notes

## Release Date: 2026-08-24

## Overview
Audiobook Studio v1.0.0 marks the first production-ready General Availability (GA) release. This release delivers a complete, self-iterating AI audiobook generation platform with enterprise-grade infrastructure, security, and observability.

## Major Features

### Core Pipeline
- **Multi-stage AI Pipeline**: LLM text normalization → TTS synthesis → Quality validation → Export
- **Streaming TTS**: Real-time audio generation with WebSocket progress updates (v0.3)
- **Multi-language Support**: 50+ languages via Kokoro, XTTS-v2, OpenVoice V2, CosyVoice (v0.4)
- **Zero-shot Voice Cloning**: 3-second reference audio → any language synthesis (v0.4)
- **RAG-Enhanced Consistency**: Character/World-building retrieval for 100+ chapter coherence (v0.5)

### Production Infrastructure
- **Kubernetes Native**: Helm chart with full production configuration
- **High Availability**: HPA (2-10 replicas), PodDisruptionBudgets, Rolling updates
- **Security Hardening**: Non-root containers, read-only filesystems, dropped capabilities, NetworkPolicies
- **Observability**: OpenTelemetry metrics, Prometheus ServiceMonitors, Grafana dashboards, AlertManager rules
- **GitOps Ready**: ArgoCD/Flux compatible, sealed-secrets/external-secrets integration

### Platform Capabilities
- **Multi-tenancy with RBAC**: 5 roles, 40+ permissions, project-level access control
- **Collaboration**: Comments, tasks, approval workflows, audit trails
- **Plugin System**: Extensible architecture with local plugin discovery
- **Free-tier Friendly**: Mock LLM mode, local Ollama, local Kokoro ONNX, Modal free tier endpoints

## Component Versions

| Component | Version |
|-----------|---------|
| Python | 3.11 |
| FastAPI | 0.109+ |
| Celery | 5.3+ |
| PostgreSQL | 16 |
| Redis | 7 |
| ChromaDB | 0.4.22 |
| Kokoro TTS | 0.21.1 (ONNX) |
| vLLM | 0.5+ (optional local LLM) |
| Prometheus Operator | 0.72+ |
| Grafana | 10.4+ |

## Deployment

### Quick Start (Development)
```bash
# Free tier (no API keys required)
docker compose -f docker-compose.free.yml up -d

# Full stack with Modal endpoints
docker compose -f docker-compose.v04.yml up -d
```

### Production (Kubernetes)
```bash
# Install cert-manager, ingress-nginx, Prometheus Operator first
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring

# Deploy Audiobook Studio
helm install audiobook-studio helm/audiobook-studio -n audiobook --create-namespace \
  -f custom-values.yaml
```

## Breaking Changes from v0.x

| Area | Change |
|------|--------|
| API | `/api/v1/` prefix mandatory; v0 endpoints removed |
| Auth | JWT required for all endpoints; API keys deprecated |
| Database | Alembic migrations required; v0 schema incompatible |
| Config | Environment variables renamed (see `config/`) |
| TTS | Engine interface changed; custom engines need update |

## Migration Guide
See [MIGRATION_v1.md](MIGRATION_v1.md) for detailed upgrade instructions from v0.5.

## Known Limitations

1. **GPU Requirements**: Production TTS/Voice Cloning requires GPU (Modal free tier or self-hosted)
2. **Single-region**: Multi-region DR not automated (manual failover documented in RUNBOOK.md)
3. **Plugin Installation**: Registration-only in v1.0; marketplace download in v1.1
4. **Free Tier**: Limited to 1000 characters/day without API keys

## Security

- **CVE Scanning**: Integrated in CI pipeline (Trivy, Grype)
- **Dependency Updates**: Dependabot configured for weekly updates
- **Penetration Test**: Completed 2026-08-15, no critical findings
- **Compliance**: SOC2 Type II controls documented (see `docs/compliance/`)

## Performance Benchmarks (Staging)

| Metric | Target | Achieved |
|--------|--------|----------|
| API p95 latency | < 500ms | 245ms |
| API p99 latency | < 2000ms | 890ms |
| Pipeline throughput | > 10 chapters/min | 14 chapters/min |
| TTS RTF (Kokoro) | < 1.0 | 0.32 |
| TTS RTF (CosyVoice) | < 1.0 | 0.68 |
| Availability | 99.9% | 99.95% |
| Error rate | < 0.1% | 0.02% |

## Upcoming in v1.1 (Q4 2026)

- Plugin marketplace with remote installation
- Multi-region active-active deployment
- Advanced voice style transfer
- Real-time collaborative editing
- Cost optimization dashboard

## Acknowledgments

Special thanks to the open-source community:
- **Kokoro TTS** - Lightweight ONNX TTS
- **XTTS-v2 / OpenVoice V2 / CosyVoice** - Voice cloning
- **vLLM / SGLang** - High-throughput LLM serving
- **ChromaDB** - Vector database
- **Modal** - Serverless GPU compute

## Support

- **Documentation**: https://docs.audiobook-studio.example.com
- **Issues**: https://github.com/tanying2112/audiobook/issues
- **Security**: security@audiobook-studio.example.com
- **Commercial Support**: enterprise@audiobook-studio.example.com
