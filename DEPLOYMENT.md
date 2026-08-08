# AgroNexus — Deployment Guide

Full step-by-step guide to deploy AgroNexus on Google Cloud Platform.

- **GCP Project:** `agrinexus-farm`
- **Domain Registrar:** Spaceship
- **Backend:** Django + Gunicorn on GKE (separate deployment)
- **Frontend:** React/Nginx on GKE (separate deployment)
- **Mobile:** Code-only — not deployed (EAS Build when ready)

---

## Architecture

```
Spaceship DNS (A record → Static IP)
        ↓
GKE Ingress (HTTPS — GKE ManagedCertificate auto-provisions SSL)
        ↓                              ↓
agronexus-frontend (nginx)     agronexus-backend (Django/gunicorn)
                                       ↓                    ↓
                               Cloud SQL Proxy        GCS Media Bucket
                               (PostgreSQL 15)        (agronexus-media)
                                       ↑
                             Celery Worker + Beat
                                       ↑
                                 Redis (in-cluster)
```

---

## Prerequisites

```bash
# 1. Google Cloud SDK — https://cloud.google.com/sdk/docs/install
gcloud --version

# 2. kubectl
gcloud components install kubectl gke-gcloud-auth-plugin

# 3. Docker Desktop — https://www.docker.com/products/docker-desktop
docker --version
```

---

## Step 1 — Create the GCP Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click **New Project**
3. Set **Project name** = `agrinexus-farm`, **Project ID** = `agrinexus-farm`
4. Enable billing on the project
5. Authenticate locally:

```bash
gcloud auth login
gcloud config set project agrinexus-farm
```

---

## Step 2 — Edit deploy.sh

Open `deploy.sh`. The PROJECT_ID is already set to `agrinexus-farm`. Update:

```bash
DOMAIN="agrinexus.com"           # already set
API_DOMAIN="api.agrinexus.com"   # already set
```

---

## Step 3 — Run the First-Time Deploy Script

```bash
chmod +x deploy.sh
./deploy.sh
```

This takes **10–15 minutes** and does:

| Step | What happens |
|------|-------------|
| 1 | Enables GCP APIs (GKE, Cloud SQL, Artifact Registry, Cloud Build, GCS) |
| 2 | Creates Artifact Registry Docker repo `agronexus` |
| 3 | Provisions Cloud SQL PostgreSQL 15 (db-g1-small, 20 GB SSD, 7-day backups) |
| 4 | Creates GCS media bucket `agronexus-media-prod` |
| 5 | Creates GCP service account with Cloud SQL + GCS IAM roles |
| 6 | Creates GKE Standard cluster (e2-standard-2, 1–4 nodes, Workload Identity) + reserves static IP |
| 7 | Builds & pushes backend + frontend Docker images |
| 8 | Substitutes real values into all k8s YAML files |
| 9 | Applies all Kubernetes manifests + creates K8s secrets |
| 10 | Runs Django migrations inside the backend pod |

> ⚠️ **Save the `DB_PASSWORD`** the script prints — it's generated once and never shown again.

---

## Step 4 — Set DNS Records on Spaceship

After Step 3, get your static IP:

```bash
gcloud compute addresses describe agronexus-ip --global --format="get(address)"
```

**Log in to [spaceship.com](https://www.spaceship.com) → Domains → your domain → DNS**

Add these two records:

| Type | Host / Name | Value | TTL |
|------|------------|-------|-----|
| A | `@` (root — agrinexus.com) | `<STATIC_IP>` | 300 |
| CNAME | `www` | `agrinexus.com` | 300 |
| A | `api` | `<STATIC_IP>` | 300 |

> DNS propagation takes **5–30 minutes**. GKE's ManagedCertificate then auto-provisions SSL — allow **10–15 more minutes** for HTTPS to become active.

Check SSL status:
```bash
kubectl describe managedcertificate agronexus-cert -n agronexus
# Status should eventually show: Active
```

---

## Step 5 — Update API Keys in the K8s Secret

The deploy script puts placeholder values for Anthropic and email. Replace them:

```bash
# Anthropic API key (for the AI intelligence engine)
kubectl patch secret agronexus-secrets -n agronexus \
  -p '{"data":{"ANTHROPIC_API_KEY":"'$(echo -n "sk-ant-YOUR_KEY_HERE" | base64 -w0)'"}}'

# SendGrid API key (for email notifications)
kubectl patch secret agronexus-secrets -n agronexus \
  -p '{"data":{"EMAIL_HOST_PASSWORD":"'$(echo -n "SG.YOUR_KEY_HERE" | base64 -w0)'"}}'
```

---

## Step 6 — Create the Platform Admin Account

Edit the superuser job with your real credentials:

```bash
# Open the job file and find DJANGO_SUPERUSER_* env vars
nano k8s/jobs/migrate.yaml
# Set DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_FULL_NAME, DJANGO_SUPERUSER_PASSWORD

# Run it
kubectl delete job agronexus-createsuperuser -n agronexus --ignore-not-found
kubectl apply -f k8s/jobs/migrate.yaml
kubectl logs -f job/agronexus-createsuperuser -n agronexus
```

---

## Step 7 — Set Up GitHub Actions CI/CD

Every push to `main` auto-deploys. You need to add secrets to **each GitHub repo**.

### Required Secrets

Add these in **GitHub → repo → Settings → Secrets and variables → Actions**:

#### farm_backend repo secrets
| Secret | Value |
|--------|-------|
| `GCP_PROJECT_ID` | `agrinexus-farm` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | (see WIF setup below) |
| `GCP_SERVICE_ACCOUNT` | `github-deploy@agrinexus-farm.iam.gserviceaccount.com` |

#### farm_frontend repo secrets
| Secret | Value |
|--------|-------|
| `GCP_PROJECT_ID` | `agrinexus-farm` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | (same as above) |
| `GCP_SERVICE_ACCOUNT` | `github-deploy@agrinexus-farm.iam.gserviceaccount.com` |
| `VITE_API_URL` | `https://api.agrinexus.com/graphql/` |

### Set up Workload Identity Federation (keyless auth — no JSON keys)

Run this once to let GitHub Actions authenticate to GCP without storing credentials:

```bash
PROJECT_ID="agrinexus-farm"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="get(projectNumber)")

# 1. Create WIF pool
gcloud iam workload-identity-pools create "github-pool" \
  --project=$PROJECT_ID --location="global" \
  --display-name="GitHub Actions Pool"

# 2. Create OIDC provider
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project=$PROJECT_ID --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# 3. Create a deploy service account
gcloud iam service-accounts create github-deploy \
  --project=$PROJECT_ID --display-name="GitHub Actions Deploy SA"

# 4. Grant it GKE and Artifact Registry permissions
for ROLE in roles/container.developer roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=$ROLE --quiet
done

# 5. Allow backend repo to use this SA
gcloud iam service-accounts add-iam-policy-binding \
  "github-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/mule720/farm_backend" \
  --project=$PROJECT_ID

# 6. Allow frontend repo to use this SA
gcloud iam service-accounts add-iam-policy-binding \
  "github-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/mule720/farm_frontend" \
  --project=$PROJECT_ID

# 7. Print the provider value to paste into GitHub secrets
echo ""
echo "GCP_WORKLOAD_IDENTITY_PROVIDER value (paste into BOTH repos):"
echo "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
```

---

## Useful Commands

```bash
# Check all pods
kubectl get pods -n agronexus

# View backend logs
kubectl logs -f deployment/agronexus-backend -n agronexus

# Run a Django management command in the cluster
kubectl exec -it deployment/agronexus-backend -n agronexus -c backend \
  -- python manage.py shell

# Re-run migrations manually
kubectl delete job agronexus-migrate -n agronexus --ignore-not-found
kubectl apply -f k8s/jobs/migrate.yaml
kubectl wait job/agronexus-migrate --for=condition=complete --timeout=180s -n agronexus

# Scale backend
kubectl scale deployment agronexus-backend --replicas=3 -n agronexus

# Check SSL certificate status
kubectl describe managedcertificate agronexus-cert -n agronexus

# Check HPA (auto-scaling)
kubectl get hpa -n agronexus

# Get the external IP
kubectl get ingress agronexus-ingress -n agronexus
```

---

## Cost Estimate (10 heavy users, ~$320/month on GCP `agrinexus-farm` project)

| Service | Config | Est. Monthly |
|---------|--------|-------------|
| GKE cluster | 2× e2-standard-2 (auto-scales 1–4) | ~$100 |
| Cloud SQL | PostgreSQL 15, db-g1-small, 20 GB SSD | ~$30 |
| Cloud Load Balancer | Global HTTPS | ~$20 |
| Artifact Registry | ~5 GB Docker images | ~$5 |
| GCS (media bucket) | 10 GB uploads | ~$2 |
| Cloud Build | ~30 builds/month | ~$5 |
| Networking / egress | | ~$10 |
| Buffer | | ~$148 |
| **Total** | | **~$320/mo** |

---

## Repository Overview

| Repo | Deploys to | CI/CD |
|------|-----------|-------|
| [farm_backend](https://github.com/mule720/farm_backend) | GKE `agronexus-backend` + Celery | GitHub Actions → push image → rollout |
| [farm_frontend](https://github.com/mule720/farm_frontend) | GKE `agronexus-frontend` | GitHub Actions → push image → rollout |
| [farm_mobile](https://github.com/mule720/farm_mobile) | Not deployed (EAS Build when ready) | TypeScript check only |
