# AgroNexus — Backend

Django 5.1 + GraphQL API for the AgroNexus smart agrinexus-farm management platform.

## Tech Stack

- **Framework:** Django 5.1 + graphene-django
- **Database:** PostgreSQL (production) / SQLite (development)
- **Task Queue:** Celery + Redis
- **Auth:** GraphQL JWT
- **Storage:** Google Cloud Storage (production) / local filesystem (dev)
- **Deployment:** GKE (Kubernetes) + Cloud SQL + Workload Identity

## Local Development

```bash
# 1. Create & activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env file
cp .env.example .env         # then edit .env as needed

# 4. Run migrations
python manage.py migrate

# 5. Create superuser
python manage.py createsuperuser

# 6. Start dev server
python manage.py runserver 8000
```

GraphQL playground: http://localhost:8000/graphql/

## Apps

| App | Description |
|-----|-------------|
| `accounts` | Custom user model, JWT auth, organizations |
| `enterprises` | Farm enterprise types (poultry, piggery, fish…) |
| `production` | Batch lifecycle management |
| `inventory` | Feed & stock tracking |
| `sales` | Customer orders & revenue |
| `financials` | P&L, expenses, budgets |
| `labor` | Staff & HR records |
| `biosecurity` | Vaccination schedules, disease alerts |
| `intelligence` | AI recommendations engine |
| `automation` | Rule-based farm automations |
| `notifications` | In-app notification system |
| `weather` | Weather data & NDVI |
| `irrigation` | Smart irrigation scheduling |
| `equipment` | Fleet & asset tracking |
| `kpis` | KPI dashboards |
| `market` | Commodity price feeds |
| `sustainability` | Environmental metrics |
| `vision` | AI image analysis |
| `tracking` | Animal GPS tracking |
| `greenhouse` | Greenhouse environment control |
| `devices` | IoT sensor integration |

## Deployment

See [`../deploy.sh`](../deploy.sh) for first-time GCP/GKE setup and [`../k8s/`](../k8s/) for Kubernetes manifests.

```bash
# Quick deploy (Cloud Build CI/CD)
gcloud builds submit --config ../cloudbuild.yaml
```

## Environment Variables

See `.env.example` for all required variables.
