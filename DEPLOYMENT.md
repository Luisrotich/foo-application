# Production deployment

## 1. Prepare infrastructure

Provision a Linux host or Kubernetes cluster with Docker, a managed PostgreSQL 16 database, managed Redis, DNS, and TLS certificates. Use private networking for PostgreSQL and Redis; they must not be publicly reachable.

Create a non-versioned `.env` from `.env.example`. Generate a unique 64+ character `JWT_SECRET`, set a strong `POSTGRES_PASSWORD`, and obtain Daraja production credentials. Set `MPESA_CALLBACK_URL` to a public HTTPS URL ending in `/api/mpesa/callback`. Never place this file in Git, Docker images, browser code, or logs.

## 2. Create the database

For a new deployment, run `database/schema.sql` once against the production database using a deployment account. This schema has UUID keys, foreign keys, full-text meal search, and indexes for order/payment queues. Future schema changes should be committed as versioned migrations and run before releasing the application.

## 3. Release

1. Build and test the immutable image: `docker compose build api`.
2. Start the stack: `docker compose up -d`.
3. Configure Nginx with your certificate (or terminate TLS at a load balancer), redirect HTTP to HTTPS, and set `FORCE_HTTPS=true`.
4. Confirm `curl -fsS https://your-domain/health` returns `status: ok`.
5. Configure Safaricom’s callback URL, then perform one sandbox STK Push and verify its callback creates a `payment_events` record before an order becomes paid.

For multiple API replicas, place them behind a load balancer. They are stateless: JWTs and shared Redis rate-limit state allow horizontal scaling. Tune `DB_POOL_SIZE` based on the database connection limit; total pools across all replicas must remain below that limit.

## 4. Operations

Monitor `/health`, HTTP error rate, latency, PostgreSQL connections, Redis memory, M-Pesa callback failures, and payment-pending age. Ship application logs to a centralized log service. Back up PostgreSQL daily and test restores. Store images in a registry and retain the previous tested tag for rollback.

To roll back, deploy the previously working image tag; do not roll database schema backward unless that migration has an explicit, tested down migration.

## Deployment gate

The GitHub Actions workflow compiles/lints the API, audits dependencies, rejects obvious committed secrets/debug logs, builds the container, and scans its image. Before promotion also verify:

- all database migrations completed and a backup exists;
- production environment variables and HTTPS callback URL are set;
- `/health` works through the load balancer;
- Redis-backed rate limiting is active;
- login, checkout, STK callback, and restaurant acceptance pass in the target environment;
- the previous image tag remains deployable.
