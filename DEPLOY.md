# 🏗️ AI-Estimator — Deployment Guide

Complete guide to deploy AI-Estimator as a production SaaS application.

## Architecture

```
┌─────────┐     ┌──────────┐     ┌──────────┐
│  Caddy   │────▶│  Next.js │     │ FastAPI  │
│ (Reverse │     │  Web UI  │     │   API    │
│  Proxy)  │────▶│  :3000   │────▶│  :8000   │
└─────────┘     └──────────┘     └────┬─────┘
                                       │
                              ┌────────┼────────┐
                              ▼        ▼        ▼
                          ┌──────┐ ┌──────┐ ┌──────┐
                          │ Post │ │Redis │ │ PDF  │
                          │  DB  │ │Cache │ │Files │
                          └──────┘ └──────┘ └──────┘
```

## Quick Start (Docker Compose)

The fastest way to get running locally:

```bash
# 1. Clone the repo
git clone https://github.com/Filewhy4165/Ai-Estimator.git
cd Ai-Estimator

# 2. Configure environment
cp .env.example .env
# Edit .env with your values (at minimum: JWT_SECRET, DATABASE_URL)

# 3. Deploy
./deploy.sh docker

# 4. Open in browser
# Web UI:  http://localhost:3000
# API:     http://localhost:8000
# API Docs: http://localhost:8000/docs
```

## Deployment Options

### Option 1: Fly.io (Recommended for First Deploy)

Best for: Quick launch, auto-scaling, managed Postgres, ~$5-10/mo.

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Configure
cp .env.example .env
# Edit .env with production values

# Deploy
./deploy.sh fly
```

**What you need:**
- Fly.io account (free to create)
- Domain name (optional — get a `.fly.dev` subdomain free)
- Stripe account for payments

**Fly setup steps:**
1. `fly apps create ai-estimator`
2. `fly postgres create --name ai-estimator-db`
3. `fly postgres attach ai-estimator-db`
4. `fly secrets set JWT_SECRET=$(openssl rand -hex 32)`
5. `fly secrets set STRIPE_SECRET_KEY=sk_live_...`
6. `fly deploy`

### Option 2: Railway

Best for: Git-push deploys, easy scaling.

```bash
npm i -g @railway/cli
railway login
railway init
./deploy.sh railway
```

### Option 3: Docker Compose (VPS)

Best for: Full control, any VPS provider.

```bash
# On your VPS
git clone https://github.com/Filewhy4165/Ai-Estimator.git
cd Ai-Estimator
cp .env.example .env
# Edit .env
./deploy.sh docker
```

### Option 4: AWS / GCP

Use the Dockerfile + docker-compose.yml with:
- ECS Fargate or Cloud Run for the API
- RDS for PostgreSQL
- ElastiCache for Redis
- S3 for PDF uploads (update UPLOAD_DIR)
- CloudFront for CDN

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `JWT_SECRET` | Yes | — | Secret for JWT signing (generate with `openssl rand -hex 32`) |
| `JWT_ALGORITHM` | No | HS256 | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | No | 60 | Access token expiry |
| `REDIS_URL` | No | redis://localhost:6379/0 | Redis for rate limiting + caching |
| `STRIPE_SECRET_KEY` | No | — | Stripe API key (live or test) |
| `STRIPE_WEBHOOK_SECRET` | No | — | Stripe webhook signing secret |
| `STRIPE_PRICE_PRO` | No | — | Stripe Price ID for Pro plan |
| `STRIPE_PRICE_ENTERPRISE` | No | — | Stripe Price ID for Enterprise plan |
| `CORS_ORIGINS` | No | localhost:3000,localhost:8000 | Comma-separated allowed origins |
| `UPLOAD_MAX_FILES` | No | 50 | Max PDFs per upload |
| `UPLOAD_MAX_SIZE_MB` | No | 100 | Max total upload size |
| `RATE_LIMIT_PER_MINUTE` | No | 60 | API rate limit per IP |
| `LOG_LEVEL` | No | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `APP_NAME` | No | AI-Estimator | Application name |
| `APP_VERSION` | No | 0.1.0 | Application version |
| `NEXT_PUBLIC_API_URL` | No | http://localhost:8000 | API URL for web frontend |

## Stripe Setup

1. Create a [Stripe account](https://stripe.com)
2. Create two products in the Stripe Dashboard:
   - **Pro Plan**: $49/month recurring
   - **Enterprise Plan**: Custom pricing
3. Copy the Price IDs (`price_...`) into `STRIPE_PRICE_PRO` and `STRIPE_PRICE_ENTERPRISE`
4. Create a webhook endpoint pointing to `https://yourdomain.com/billing/webhook`
   - Events to listen for: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`, `customer.created`
5. Copy the webhook signing secret to `STRIPE_WEBHOOK_SECRET`

## Subscription Plans

| Plan | Price | Jobs/month | Pages/job | Features |
|------|-------|-----------|-----------|----------|
| Free | $0 | 5 | 50 | Basic takeoff, CSV export |
| Pro | $49/mo | Unlimited | 500 | Priority processing, cost mapping, spec compliance |
| Enterprise | Custom | Unlimited | Unlimited | SSO, custom models, dedicated support, API access |

## API Endpoints

### Auth
- `POST /auth/register` — Create account
- `POST /auth/login` — Login
- `POST /auth/refresh` — Refresh token
- `GET /auth/me` — Get profile
- `PUT /auth/me` — Update profile
- `POST /auth/api-keys` — Generate API key
- `GET /auth/api-keys` — List API keys
- `DELETE /auth/api-keys/{id}` — Revoke API key

### Billing
- `POST /billing/checkout` — Start Stripe checkout
- `POST /billing/portal` — Open Stripe portal
- `POST /billing/webhook` — Stripe webhook
- `GET /billing/subscription` — Current subscription
- `GET /billing/usage` — Usage statistics

### Analysis
- `POST /v1/analyze` — Upload PDFs and run analysis
- `POST /v1/jobs` — Create async job
- `GET /v1/jobs` — List jobs
- `GET /v1/jobs/{id}` — Job detail
- `GET /v1/jobs/{id}/takeoff` — Takeoff results
- `GET /v1/jobs/{id}/takeoff-line-items` — Line items
- `GET /v1/jobs/{id}/report.html` — HTML report
- `POST /v1/jobs/{id}/export` — Export CSV
- `GET /v1/jobs/{id}/handoff.zip` — Handoff package
- `GET /v1/jobs/{id}/spec-compliance` — Spec compliance
- `GET /v1/jobs/{id}/trade-recommendation` — Trade recommendations
- `GET /v1/jobs/{id}/trade-coverage` — Trade coverage
- `GET /v1/jobs/{id}/visual-evidence` — Visual evidence
- `GET /v1/jobs/{id}/visual-review` — Visual review page
- `GET /v1/jobs/metrics` — Job metrics

### System
- `GET /health` — Health check
- `GET /docs` — API documentation (Swagger)

## Monitoring

The application includes:
- **Structured JSON logging** — every request logged with request_id, user_id, duration
- **Health endpoint** — `GET /health` returns version, uptime, DB status
- **Job metrics** — `GET /v1/jobs/metrics` for operational stats
- **Rate limiting** — 60 req/min default, configurable

For production monitoring, add:
- **Uptime checks** — Ping `/health` every 30s
- **Log aggregation** — Send JSON logs to Datadog/CloudWatch/Loki
- **Alerts** — On error rate > 1% or p99 latency > 5s

## Scaling

Current architecture handles:
- ~100 concurrent users on a single Fly.io VM (512MB)
- ~10 concurrent PDF analysis jobs (BoundedSemaphore)

To scale further:
1. **Horizontal scaling** — Add API replicas behind a load balancer
2. **Worker queue** — Move PDF processing to Celery + Redis workers
3. **Object storage** — Move PDF uploads to S3/GCS
4. **Database** — Upgrade Postgres plan, add read replicas
5. **CDN** — Add CloudFront/Cloudflare for static assets

## Security Checklist

- [x] JWT authentication with refresh tokens
- [x] Password hashing with bcrypt
- [x] API key authentication for programmatic access
- [x] CORS configured per environment
- [x] Rate limiting (60 req/min default)
- [x] Non-root Docker containers
- [x] Structured audit logging
- [x] Tenant isolation per user
- [ ] TLS/HTTPS (handled by Caddy/Fly)
- [ ] CSRF protection (not needed for API-only)
- [ ] Penetration testing (before public launch)
- [ ] SOC 2 compliance (for Enterprise customers)

## Troubleshooting

### API won't start
- Check `DATABASE_URL` is correct and Postgres is running
- Check `JWT_SECRET` is set
- Check logs: `docker compose logs api`

### Web UI shows blank
- Check `NEXT_PUBLIC_API_URL` points to your API
- Check CORS origins include the web UI URL
- Check browser console for errors

### Stripe webhooks not working
- Verify webhook endpoint URL is publicly accessible
- Verify `STRIPE_WEBHOOK_SECRET` matches the endpoint
- Check Stripe Dashboard → Webhooks → Attempts

### PDF uploads failing
- Check `UPLOAD_MAX_SIZE_MB` is large enough
- Check disk space on the server
- Check file permissions on upload directory

## Support

- GitHub Issues: https://github.com/Filewhy4165/Ai-Estimator/issues
- API Documentation: https://yourdomain.com/docs
