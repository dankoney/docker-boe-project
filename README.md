# BOE Project (Docker)

Demurrage Analytics: Streamlit frontend + FastAPI backend + PostgreSQL. Ready to run with Docker.

## Quick start (after clone)

1. **Copy env and set your values**
   ```bash
   cp .env.example .env
   ```
   Edit `.env`: at least `SMTP_USER`, `SMTP_PASSWORD`, and `APP_BASE_URL` (your app URL for email links).

2. **Start everything**
   ```bash
   docker compose up -d --build
   ```

3. **Open**
   - App: http://localhost:8501  
   - API docs: http://localhost:8000/docs  

4. **Stop**
   ```bash
   docker compose down
   ```

## Production (e.g. Plesk)

- Set **API_BASE_URL** for the frontend to your public API URL (e.g. `https://api.yourdomain.com`).  
  Use the override: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`  
  (Edit `docker-compose.prod.yml` and replace `api.yourdomain.com` with your domain.)

- See [DEPLOY-STREAMLIT-DOCKER-PLESK.md](DEPLOY-STREAMLIT-DOCKER-PLESK.md) in this repo for full Plesk deployment.

## What’s inside

| Service   | Port | Description        |
|----------|------|--------------------|
| frontend | 8501 | Streamlit app      |
| api      | 8000 | FastAPI (auth, reports) |
| db       | 5432 | PostgreSQL 15      |

Data is stored in a Docker volume; it persists across `docker compose down`.
