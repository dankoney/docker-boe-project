# Deploy BOE Project (Streamlit + FastAPI + PostgreSQL) to Plesk

This guide walks you through deploying the **boe-project** (Demurrage Analytics) to a Plesk VPS using Docker.

---

## What you’re deploying

| Service   | Role              | Port (internal) | Public URL (example)     |
|----------|-------------------|------------------|---------------------------|
| **db**   | PostgreSQL 15     | 5432            | — (internal only)        |
| **api**  | FastAPI (auth, reports) | 8000      | `https://api.yourdomain.com` |
| **frontend** | Streamlit app | 8501        | `https://app.yourdomain.com`  |

The browser loads the Streamlit app and calls the API; the API talks to PostgreSQL. Email (Gmail SMTP) is used for verification and password reset.

---

## Prerequisites

- **Plesk** on a VPS (with SSH access).
- **Docker** and **Docker Compose** on the server (install via Plesk “Docker” extension or manually).
- A **domain** (e.g. `yourdomain.com`) with DNS pointing to the server.
- **.env** prepared with production values (see below).

---

## Step 1: Prepare the server

### 1.1 Install Docker (if not already)

- In Plesk: **Extensions → Docker** (install if needed).
- Or via SSH:
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER
  # Log out and back in, then:
  sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
  ```

### 1.2 Create app directory on the server

```bash
sudo mkdir -p /var/www/boe-project
sudo chown $USER:$USER /var/www/boe-project
cd /var/www/boe-project
```

---

## Step 2: Get the code and add production .env

### 2.1 Clone the repository

```bash
cd /var/www/boe-project
git clone https://github.com/YOUR_USERNAME/docker-boe-project.git .
```

(Replace `YOUR_USERNAME` with your GitHub username. If the repo is private, use a Personal Access Token when prompted.)

### 2.2 Create production `.env` in the project root

```bash
cp .env.example .env
nano .env   # or vim
```

Set at least:

- **DB:** If using Docker Postgres (default), keep `DB_HOST=db` etc. in `docker-compose`; no need to repeat in `.env` unless you override.
- **APP_BASE_URL** — Public URL of the Streamlit app (used in email links):
  ```env
  APP_BASE_URL=https://app.yourdomain.com
  ```
- **SMTP_USER** / **SMTP_PASSWORD** — Gmail (or other) SMTP for verification/reset emails.
- **COOKIES_PASSWORD** — Strong random secret for cookie encryption (e.g. `openssl rand -hex 32`).
- **ALLOWED_EMAIL_DOMAIN** — e.g. `shippers.org.gh` if you restrict registration.

Example (minimal production snippet):

```env
APP_BASE_URL=https://app.yourdomain.com
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_LABEL=Demurrage Analytics
COOKIES_PASSWORD=<generate-a-strong-secret>
ALLOWED_EMAIL_DOMAIN=shippers.org.gh
```

Do **not** commit `.env`; keep it only on the server.

---

## Step 3: Production URLs for the frontend (API_BASE_URL)

The Streamlit app runs in the **browser** and calls the API by URL. That URL must be the **public** API URL, not the internal Docker hostname.

**Option A – Use a production override file (recommended)**

Edit `docker-compose.prod.yml` in the project root: set `API_BASE_URL` to your public API URL (e.g. `https://api.yourdomain.com`). Then run:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

**Option B – Set env on the server**

Export before starting:

```bash
export API_BASE_URL=https://api.yourdomain.com
docker compose up -d --build
```

---

## Step 4: Build and run with Docker Compose

From the project root on the server:

```bash
cd /var/www/boe-project

# Build and start (use prod override)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Or without override (then set API_BASE_URL some other way):
docker compose up -d --build
```

Check that all three containers are up:

```bash
docker compose ps
```

- **db** (healthy)  
- **api** (port 8000)  
- **frontend** (port 8501)

PostgreSQL data is stored in a Docker volume (`postgres_data`); it persists across restarts.

---

## Step 5: Expose the app with Plesk (reverse proxy + HTTPS)

You want:

- `https://app.yourdomain.com` → Streamlit (port 8501)  
- `https://api.yourdomain.com` → API (port 8000)  

### 5.1 Create two (sub)domains in Plesk

1. **Domains → Add Domain** (or subdomain):
   - **app.yourdomain.com** (or `yourdomain.com`) — for the Streamlit app  
   - **api.yourdomain.com** — for the API  

2. For each domain, ensure **SSL/TLS** is enabled (Let’s Encrypt is fine).

### 5.2 Reverse proxy from Plesk to Docker

**Using Plesk “Proxy Mode” (Apache as reverse proxy):**

1. For **app.yourdomain.com**: Enable **Proxy mode** and set **Proxy to:** `http://127.0.0.1:8501`.
2. For **api.yourdomain.com**: Proxy to `http://127.0.0.1:8000` with the same kind of settings (Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto).

**Using nginx directives** (if Plesk uses nginx in front), for the app domain:

```nginx
location / {
    proxy_pass http://127.0.0.1:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### 5.3 Ensure HTTPS and correct URLs

- Turn on **SSL/TLS** for both hostnames (Let’s Encrypt in Plesk).
- In `.env` and in the frontend env, use **https**:
  - `APP_BASE_URL=https://app.yourdomain.com`
  - `API_BASE_URL=https://api.yourdomain.com` (for the frontend container).

---

## Step 6: Post-deploy checks

1. **App:** Open `https://app.yourdomain.com` — Streamlit login page should load.  
2. **API:** Open `https://api.yourdomain.com/docs` — FastAPI Swagger UI.  
3. **Register / Login:** Create an account (if allowed for your domain), then check email verification and login.  
4. **Password reset:** Use “Forgot password?” and confirm the email link uses `https://app.yourdomain.com`.

If the app shows “Connection error” when logging in, the browser cannot reach the API: double-check **API_BASE_URL** (must be the public `https://api.yourdomain.com`) and that the API is reachable at that URL.

---

## Useful commands on the server

```bash
cd /var/www/boe-project

# View logs
docker compose logs -f

# Restart after code or .env change
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Stop
docker compose down
```

---

## Checklist

- [ ] Docker and Docker Compose installed on the server  
- [ ] Repo cloned (`docker-boe-project`) into e.g. `/var/www/boe-project`  
- [ ] `.env` created with `APP_BASE_URL`, `SMTP_*`, `COOKIES_PASSWORD`, `ALLOWED_EMAIL_DOMAIN`  
- [ ] `docker-compose.prod.yml` updated with your API domain  
- [ ] `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`  
- [ ] Plesk reverse proxy: app subdomain → 8501, API subdomain → 8000  
- [ ] SSL enabled for both hostnames  
- [ ] Login, registration, and password reset tested with the production URLs  
