# Resource-Aware Deployment Protocol
**Created**: 2025-10-11
**Status**: MANDATORY for all droplet deployments
**Incident Reference**: Feature 011 resource exhaustion (CPU 100%, Load 150+, Memory 100%)

## 🚨 Never Repeat: What Went Wrong

**Date**: 2025-10-11, 15:30-17:30 UTC
**Incident**: Feature 011 backend deployment
**Image Size**: 6GB (torch, transformers, haystack-ai)
**Operation**: `docker build` + `docker save | nerdctl load`
**Result**: Droplet crash (CPU 100%, Load 150+, Memory exhausted, SSH timeout)

---

## ✅ Pre-Deployment Checklist (MANDATORY)

### 1. Resource Check (ALWAYS RUN FIRST)
```bash
ssh root@161.35.44.166 "
  echo '=== CURRENT RESOURCES ===' &&
  free -h | awk 'NR==2{printf \"Memory: %s/%s (%.0f%% used)\n\", \$3,\$2,(\$3/\$2)*100}' &&
  df -h / | awk 'NR==2{printf \"Disk: %s/%s (%s used)\n\", \$3,\$2,\$5}' &&
  uptime | awk '{print \"Load Average:\", \$(NF-2), \$(NF-1), \$NF}' &&
  echo '=== THRESHOLDS ===' &&
  echo 'SAFE: Memory <70%, Disk <70%, Load <2.0' &&
  echo 'RISKY: Memory 70-85%, Disk 70-85%, Load 2.0-5.0' &&
  echo 'STOP: Memory >85%, Disk >85%, Load >5.0'
"
```

**Decision Matrix**:
- **GREEN** (Safe): Proceed with deployment
- **YELLOW** (Risky): Defer or use minimal build
- **RED** (Stop): Clean up resources first, never deploy

### 2. Estimate Image Size
```bash
# For new Dockerfiles, build locally first:
cd /path/to/backend-source
docker build -t test-build .
docker images test-build --format "{{.Size}}"

# Classification:
# Small: <500MB → Build on droplet
# Medium: 500MB-2GB → Build with limits
# Large: >2GB → Build locally + transfer
```

---

## 🏗️ Build Strategies by Image Size

### Small Images (<500MB)
**Examples**: Simple FastAPI apps, static frontends
**Strategy**: Build directly on droplet
```bash
ssh root@161.35.44.166 "
  cd /opt/app &&
  nerdctl build -t app:tag .
"
```

### Medium Images (500MB-2GB)
**Examples**: Web apps with moderate dependencies
**Strategy**: Build with resource limits
```bash
ssh root@161.35.44.166 "
  cd /opt/app &&
  nerdctl build -t app:tag \
    --memory 2g \
    --cpus 2 \
    --ulimit nofile=1024:1024 .
"
```

### Large Images (>2GB)
**Examples**: ML apps (torch, transformers), data processing
**Strategy**: Build locally OR use multi-stage Dockerfile

#### Option A: Local Build + Transfer
```bash
# LOCAL MACHINE:
cd /Volumes/TerrysPOV/project
docker build -t app:tag -f Dockerfile.optimized .
docker save app:tag | gzip > app.tar.gz

# Transfer (compressed)
scp app.tar.gz root@161.35.44.166:/tmp/

# DROPLET:
ssh root@161.35.44.166 "
  gunzip -c /tmp/app.tar.gz | nerdctl load &&
  rm /tmp/app.tar.gz
"
```

#### Option B: Multi-Stage Build (RECOMMENDED)
See `Dockerfile.optimized` for Feature 011 example.
**Benefits**: 6GB → 1.2GB reduction, faster transfers

---

## 📊 Resource Monitoring During Deployment

### Start Background Monitor
```bash
ssh root@161.35.44.166 "
  watch -n 2 'echo === RESOURCES === && \
    free -h | head -2 && \
    df -h / | tail -1 && \
    uptime | tail -1' > /tmp/deploy-monitor.log 2>&1 &
  echo 'Monitor PID: '\$!
"
```

### Deploy with Limits
```bash
ssh root@161.35.44.166 "
  nerdctl run -d \
    --name app-container \
    --memory 2g \
    --memory-swap 2g \
    --cpus 2 \
    --restart on-failure:3 \
    app:tag
"
```

### Check Monitor Log
```bash
ssh root@161.35.44.166 "tail -20 /tmp/deploy-monitor.log"
```

---

## 🧹 Cleanup Before Large Deployments

### Check Reclaimable Space
```bash
ssh root@161.35.44.166 "
  echo '=== Docker/Nerdctl Cleanup ===' &&
  docker system df &&
  nerdctl system df
"
```

### Clean Up
```bash
ssh root@161.35.44.166 "
  # Remove unused Docker resources
  docker system prune -af --volumes &&

  # Remove unused nerdctl resources
  nerdctl system prune -af --volumes &&

  # Clear build cache
  docker builder prune -af &&

  # Verify space freed
  df -h /
"
```

---

## 🎯 Feature 011 Specific Recovery

### Current Status
- ✅ Redis deployed (feature-011-redis, port 6379)
- ❌ Backend failed (6GB image exhaustion)
- ❌ Celery workers not deployed

### Corrected Deployment
```bash
# 1. Build optimized image locally
cd /Volumes/TerrysPOV/gov_content_ai/backend-source
docker build -t gov-ai-backend:feature-011 -f Dockerfile.optimized .

# 2. Compress and transfer
docker save gov-ai-backend:feature-011 | gzip > feature-011.tar.gz
scp feature-011.tar.gz root@161.35.44.166:/tmp/

# 3. Load on droplet
ssh root@161.35.44.166 "gunzip -c /tmp/feature-011.tar.gz | nerdctl load"

# 4. Deploy with limits
ssh root@161.35.44.166 "
  nerdctl run -d \
    --name feature-011-backend \
    --network feature-011-network \
    --add-host host.docker.internal:host-gateway \
    -p 8001:8000 \
    --memory 2g --cpus 2 \
    --env-file /opt/gov-ai-feature-011/.env \
    -e PYTHONPATH='/app/src' \
    -e DATABASE_URL='postgresql+asyncpg://postgres:gov_secure_db_2024!@host.docker.internal:5432/gov_ai_db' \
    -e REDIS_URL='redis://feature-011-redis:6379/0' \
    --restart always \
    gov-ai-backend:feature-011
"
```

---

## 📝 Lessons Learned

1. **Never build >2GB images on production droplets**
2. **Always check resources BEFORE deployment**
3. **Use multi-stage builds for ML/data apps**
4. **Monitor resources DURING deployment**
5. **Set memory/CPU limits on containers**
6. **Keep 30%+ free memory for system stability**
7. **Compressed transfers (gzip) save 70% bandwidth**
8. **Docker save/load >1GB = HIGH RISK of crash**

---

## 🔐 Emergency Recovery

If droplet becomes unresponsive:

1. **DigitalOcean Console** → Droplet → **Power Cycle** (NOT destroy)
2. Wait 5-10 minutes for boot
3. SSH and check: `uptime && free -h && df -h`
4. Clean up failed resources
5. Re-deploy with corrected strategy

---

**Last Updated**: 2025-10-11
**Maintainer**: Claude Code
**Review Cycle**: After every incident or quarterly
