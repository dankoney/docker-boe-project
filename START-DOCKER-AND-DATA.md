# Start Docker and ensure data is loaded

## 1. Start the stack

From the project root (`boe-project`):

```powershell
cd c:\Users\hI\plesk\boe-project
docker compose up -d --build
```

- **First run:** Builds images and starts `db`, `api`, `frontend`. The database runs the scripts in `docker/init/` (schema + extensions) automatically.
- **Later runs:** Starts existing containers. Rebuild with `--build` only when you change Dockerfiles or code.

Check that everything is up:

```powershell
docker compose ps
```

You should see `db` (healthy), `api`, and `frontend` running. Then open:

- **App:** http://localhost:8501  
- **API docs:** http://localhost:8000/docs  

---

## 2. Ensure data reflects

What “data” means depends on what you use:

### A. Schema and empty tables

- The **schema** (including `boe_header`, `boe_records`, `users`, etc.) is applied when the **db** container is created for the first time (from `docker/init/01-schema.sql`).
- If the DB volume already existed, init scripts do **not** run again. To reapply schema from scratch you’d need to remove the volume and recreate the container (see “Reset database” below).

### B. `boe_records` (from `boe_data` dump)

If you have the `boe_data` file in the project root:

```powershell
cd c:\Users\hI\plesk\boe-project
.\scripts\load-boe-data.ps1
```

This loads the COPY block into `boe_records` inside the running Postgres container. Run it after `docker compose up -d`.

### C. `boe_header` (from XML loader)

The **BOE Analytics** page and demurrage report use the `boe_header` table. That table is filled by the **BOE header XML loader**, not by `boe_data`.

1. Put XML files in:
   `api\other_uploaded_json\boe_header_xml\boe_header_load\`
2. With Docker stack running (so Postgres is on `localhost:5432`), run:

```powershell
cd c:\Users\hI\plesk\boe-project
$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"
$env:DB_NAME = "postgres"
$env:DB_USER = "postgres"
$env:DB_PASS = "postgres"
.\scripts\run-boe-header-loader.ps1
```

If Python is not in PATH, the script can run the loader via Docker (see script output).

After this, **BOE Analytics** and demurrage will reflect the loaded `boe_header` data.

---

## 3. Quick reference

| Goal | Command / step |
|------|------------------|
| Start app | `docker compose up -d --build` |
| Stop app | `docker compose down` |
| View logs | `docker compose logs -d` or `docker compose logs -f frontend` |
| Load `boe_records` from dump | `.\scripts\load-boe-data.ps1` |
| Load `boe_header` from XML | Put XML in `boe_header_load\`, then `.\scripts\run-boe-header-loader.ps1` |
| Rebuild after code change | `docker compose up -d --build` |

---

## 4. Reset database (optional)

To wipe the database and reapply the init scripts (schema + extensions):

```powershell
docker compose down
docker volume rm boe-project_postgres_data
docker compose up -d
```

Then run `load-boe-data.ps1` and/or the header loader again if you need that data.
