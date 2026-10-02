**Clean deployment runbook** for your AgentBoard EC2 deployment. This should be the document you follow whenever you make a future frontend or backend change.

# AgentBoard — EC2 Deployment Runbook

## 1. Current architecture

Your current deployment is:

```text
Local Windows PC
    │
    │ docker build
    │ docker push
    ▼
GitHub Container Registry (GHCR)
    │
    │ docker pull
    ▼
AWS EC2
    │
    ├── frontend container
    │      ├── Next.js
    │      └── port 3000
    │
    └── backend container
           ├── FastAPI / Uvicorn
           └── port 8000

Docker network:
agentboard-network

Frontend → http://backend:8000
Backend → Groq API
```

Current containers:

```text
frontend → ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
backend  → ghcr.io/mukeshkumawat0903/agentboard-backend:latest
```

---

# 2. Important rule for future changes

Whenever you change code locally:

### Frontend change

```text
Change frontend code
       ↓
Build frontend image
       ↓
Push frontend image to GHCR
       ↓
EC2: pull frontend image
       ↓
Recreate frontend container
       ↓
Verify frontend healthy
```

### Backend change

```text
Change backend code
       ↓
Build backend image
       ↓
Push backend image to GHCR
       ↓
EC2: pull backend image
       ↓
Recreate backend container
       ↓
Verify backend healthy
```

### If both change

Do both, but **update backend and frontend deliberately**, rather than rebuilding/recreating everything unnecessarily.

---

# 3. Current Docker network

Your containers use:

```text
agentboard-network
```

Check it anytime with:

```bash
docker network ls
```

You should see:

```text
agentboard-network
```

Inspect it:

```bash
docker network inspect agentboard-network
```

The important reason for this network is that frontend can reach backend using:

```text
http://backend:8000
```

**Do not change this to the EC2 public IP.**

Inside Docker:

```text
frontend
   ↓
http://backend:8000
   ↓
backend
```

---

# 4. Current frontend Dockerfile

Your final frontend runner configuration should remain like this:

```dockerfile
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV BACKEND_URL=http://backend:8000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000/ > /dev/null || exit 1

CMD ["node", "server.js"]
```

### Important settings

Do not accidentally remove:

```dockerfile
ENV HOSTNAME=0.0.0.0
```

and:

```dockerfile
HEALTHCHECK ... http://127.0.0.1:3000/
```

We specifically needed these because:

```text
localhost → ::1
```

was causing the health check to fail, while Next.js was binding to the container address.

The final working state is:

```text
Next.js
   ↓
0.0.0.0:3000
   ↓
127.0.0.1:3000 → HTTP 200
   ↓
Docker health check → healthy
```

---

# 5. Current frontend container configuration

Current frontend:

```text
Name:
frontend

Image:
ghcr.io/mukeshkumawat0903/agentboard-frontend:latest

Network:
agentboard-network

Port:
3000:3000

Restart:
unless-stopped

Environment:
NODE_ENV=production
NEXT_TELEMETRY_DISABLED=1
BACKEND_URL=http://backend:8000
```

You can inspect it anytime:

```bash
docker inspect frontend
```

Or use the shorter commands:

```bash
docker inspect frontend --format='{{json .Config.Env}}'
```

```bash
docker inspect frontend --format='{{json .HostConfig.NetworkMode}}'
```

```bash
docker inspect frontend --format='{{json .HostConfig.PortBindings}}'
```

```bash
docker inspect frontend --format='{{json .HostConfig.RestartPolicy}}'
```

---

# 6. Current backend configuration

Backend is:

```text
Image:
ghcr.io/mukeshkumawat0903/agentboard-backend:latest

Container:
backend

Network:
agentboard-network

Port:
8000:8000

Data volume:
agentboard-data → /data   (SQLite DB, LangGraph checkpoints, knowledge base, model cache)

Environment (typically from an env file):
APP_ENV=production
LLM_PROVIDER=groq
GROQ_API_KEY=...                 # the key of the active provider is required
GROQ_MODEL=llama-3.3-70b-versatile
ADMIN_API_TOKEN=...              # needed for provider switch / memory clear / KB delete in production
TRUSTED_PROXY_IPS=127.0.0.1,::1,172.16.0.0/12   # the frontend container's network, for per-user rate limits
CORS_ORIGINS=["http://13.235.128.144:3000"]   # only used if the browser calls :8000 directly
DEFAULT_DEBATE_MODE=quick        # optional; quick when not set
```

The image already sets `DATABASE_URL`, `CHECKPOINT_DATABASE_URL`, `KNOWLEDGE_BASE_DIR`, `HF_HOME` and `XDG_CACHE_HOME` to paths under `/data`. **Mount a volume on `/data`**, otherwise everything stored there is lost each time the container is recreated. `backend/.env.example` lists every setting.

Your backend container is currently:

```text
backend → healthy
```

### Important

Never put your actual:

```text
GROQ_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY / ADMIN_API_TOKEN
```

into GitHub, Dockerfile, or `.env.example`.

The actual secret should remain on the deployment environment.

---

# 7. FRONTEND CHANGE — complete procedure

Suppose you modify:

```text
frontend/
```

### Step 1 — Test locally

First test the frontend locally:

```powershell
cd frontend
npm run verify      # lint + typecheck + unit tests
npm run e2e         # Playwright end-to-end
cd ..
```

> **CI does steps 1–2 for you.** Pushing to `main` runs the backend and frontend tests in GitHub Actions and, only if they pass, builds and pushes both images to GHCR (`latest` and `sha-…` tags). A pull request into `main` runs the same tests and builds without pushing. The manual build/push below is for when you deploy without going through `main`.

Then build the image.

From your AgentBoard project root:

```powershell
docker build -t ghcr.io/mukeshkumawat0903/agentboard-frontend:latest ./frontend
```

### Step 2 — Push to GHCR

```powershell
docker push ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
```

Wait for:

```text
latest: digest: sha256:...
```

### Step 3 — Connect to EC2

You can use your **EC2 browser terminal / Instance Connect**.

You do **not** need:

```powershell
ssh -i "YOUR_KEY.pem" ubuntu@13.235.128.144
```

if you're already using the EC2 browser terminal.

---

## 8. Update frontend on EC2

First pull the new image:

```bash
docker pull ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
```

Then stop the old frontend:

```bash
docker stop frontend
```

Remove the old container:

```bash
docker rm frontend
```

Then recreate it:

```bash
docker run -d \
  --name frontend \
  --restart unless-stopped \
  --network agentboard-network \
  -p 3000:3000 \
  -e NODE_ENV=production \
  -e NEXT_TELEMETRY_DISABLED=1 \
  -e BACKEND_URL=http://backend:8000 \
  ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
```

### Verify

```bash
docker ps
```

Expected:

```text
frontend   ... (healthy)
backend    ... (healthy)
```

---

# 9. FRONTEND verification checklist

After updating frontend:

### Check container

```bash
docker ps
```

### Check health

```bash
docker inspect --format='{{json .State.Health}}' frontend
```

### Test Next.js inside container

```bash
docker exec frontend sh -c "wget -S -O- http://127.0.0.1:3000/ 2>&1 | head -15"
```

Expected:

```text
HTTP/1.1 200 OK
```

### Check logs

```bash
docker logs frontend --tail 50
```

You want:

```text
✓ Ready
```

and ideally:

```text
Network: http://0.0.0.0:3000
```

### Browser

Open:

```text
http://13.235.128.144:3000
```

---

# 10. BACKEND CHANGE — complete procedure

Suppose you change:

```text
backend/
```

For example:

- FastAPI endpoint
- Agent logic
- LangGraph workflow
- Pydantic model
- Groq configuration
- database logic
- backend dependencies
- API response structure

### Step 1 — Test and build backend locally

Run the same gates as CI first (from `backend/`, in the venv built from `requirements-dev.lock`):

```powershell
ruff check .
mypy app
pytest -q
```

Then, from the project root:

```powershell
docker build -t ghcr.io/mukeshkumawat0903/agentboard-backend:latest ./backend
```

### Step 2 — Push

```powershell
docker push ghcr.io/mukeshkumawat0903/agentboard-backend:latest
```

### Step 3 — EC2

Pull:

```bash
docker pull ghcr.io/mukeshkumawat0903/agentboard-backend:latest
```

Before recreating it, **preserve your backend environment configuration and data**.

> **One-time check — is the data on a volume?**
> ```bash
> docker inspect backend --format='{{json .Mounts}}'
> ```
> If this prints `[]`, the database lives inside the container and would be lost with it. Copy it out first, then create the volume and copy it in after the new container starts:
> ```bash
> docker cp backend:/data ./agentboard-data-backup
> docker volume create agentboard-data
> # … after the new container (with -v agentboard-data:/data) is running:
> docker cp ./agentboard-data-backup/. backend:/data/
> docker restart backend
> ```

You can inspect the existing container:

```bash
docker inspect backend --format='{{json .Config.Env}}'
```

Then stop:

```bash
docker stop backend
```

Remove:

```bash
docker rm backend
```

Then recreate using the same backend configuration you currently use.

For example, if your actual deployment uses an env file:

```bash
docker run -d \
  --name backend \
  --restart unless-stopped \
  --network agentboard-network \
  -p 8000:8000 \
  -v agentboard-data:/data \
  --env-file /path/to/backend/.env \
  ghcr.io/mukeshkumawat0903/agentboard-backend:latest
```

**Do not copy your actual API keys or admin token into commands that you save in notes.**

On start the backend applies database migrations, deletes debates older than `DEBATE_TTL_DAYS`, prunes leftover LangGraph checkpoints, and loads the embedding model in the background (the first start downloads it into `/data/hf-cache`), so `/health` answers right away.

If your current backend uses individual `-e` values instead, preserve those exact values.

---

# 11. Backend verification

Check:

```bash
docker ps
```

Expected:

```text
backend   ... (healthy)
```

Check logs:

```bash
docker logs backend --tail 50
```

Check backend from inside the container:

```bash
docker exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

(The backend image is `python:3.11-slim`, which has no `wget`/`curl`; the image's own health check uses Python too.) You should see:

```json
{"status": "ok", "version": "2.0.0", "llm": {"provider": "groq", "model": "llama-3.3-70b-versatile", "configured": true}, "groq_configured": true}
```

`llm.configured` must be `true`; otherwise the active provider has no key.

You can also test through EC2:

```text
http://13.235.128.144:8000/health
```

---

# 12. If BOTH frontend and backend change

Follow this sequence:

### Local

```powershell
docker build -t ghcr.io/mukeshkumawat0903/agentboard-backend:latest ./backend
docker build -t ghcr.io/mukeshkumawat0903/agentboard-frontend:latest ./frontend
```

Push:

```powershell
docker push ghcr.io/mukeshkumawat0903/agentboard-backend:latest
docker push ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
```

### EC2

Pull both:

```bash
docker pull ghcr.io/mukeshkumawat0903/agentboard-backend:latest
```

```bash
docker pull ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
```

Then recreate backend and frontend.

I recommend **backend first**, then frontend:

```text
Backend
  ↓
healthy
  ↓
Frontend
  ↓
healthy
  ↓
Application test
```

---

# 13. DO NOT rebuild if only EC2 configuration changes

This distinction is important.

### You need a new image if you change:

```text
Python code
React/Next.js code
Dockerfile
package.json
package-lock.json
requirements.txt / requirements.lock
backend dependencies
frontend dependencies
application configuration baked into image
```

### You generally don't need a new image if you change:

```text
EC2 container environment variables
Docker network
port mapping
restart policy
container configuration
```

You can recreate the container with the new configuration using the **same image**.

---

# 14. If the container becomes unhealthy

Don't immediately rebuild.

First run:

```bash
docker ps
```

Then:

```bash
docker inspect --format='{{json .State.Health}}' frontend
```

or:

```bash
docker inspect --format='{{json .State.Health}}' backend
```

Then logs:

```bash
docker logs frontend --tail 100
```

or:

```bash
docker logs backend --tail 100
```

Then test the application directly.

### Frontend

```bash
docker exec frontend sh -c "wget -S -O- http://127.0.0.1:3000/ 2>&1 | head -20"
```

### Backend

```bash
docker exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

This gives us a structured troubleshooting process instead of repeatedly rebuilding.

---

# 15. If EC2 was stopped/restarted

This is important because you've already experienced this.

After EC2 starts:

```bash
docker ps
```

Check:

```bash
docker ps -a
```

Because you configured:

```text
--restart unless-stopped
```

Docker should automatically restart your containers.

Then check:

```bash
docker ps
```

You want:

```text
frontend   healthy
backend    healthy
```

If something is unhealthy:

```bash
docker logs frontend --tail 100
```

and:

```bash
docker logs backend --tail 100
```

---

# 16. If the EC2 public IP changes

This can happen when an EC2 instance is stopped and started if you are not using an Elastic IP.

For example, your previous public IP was:

```text
13.235.128.144
```

If it changes, your browser URL becomes:

```text
http://NEW_PUBLIC_IP:3000
```

The **Docker containers don't need to change** just because the public IP changed.

Check the current public IP in the AWS console.

---

# 17. Quick deployment cheat sheet

## FRONTEND ONLY

### Local

```powershell
docker build -t ghcr.io/mukeshkumawat0903/agentboard-frontend:latest ./frontend
docker push ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
```

### EC2

```bash
docker pull ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
docker stop frontend
docker rm frontend
```

```bash
docker run -d \
  --name frontend \
  --restart unless-stopped \
  --network agentboard-network \
  -p 3000:3000 \
  -e NODE_ENV=production \
  -e NEXT_TELEMETRY_DISABLED=1 \
  -e BACKEND_URL=http://backend:8000 \
  ghcr.io/mukeshkumawat0903/agentboard-frontend:latest
```

Verify:

```bash
docker ps
docker logs frontend --tail 50
docker inspect --format='{{json .State.Health}}' frontend
```

---

# 18. BACKEND ONLY

### Local

```powershell
docker build -t ghcr.io/mukeshkumawat0903/agentboard-backend:latest ./backend
docker push ghcr.io/mukeshkumawat0903/agentboard-backend:latest
```

### EC2

```bash
docker pull ghcr.io/mukeshkumawat0903/agentboard-backend:latest
```

Then recreate the backend using its **existing environment configuration** and the `-v agentboard-data:/data` volume (see section 10).

Verify:

```bash
docker ps
```

```bash
docker logs backend --tail 50
```

```bash
docker inspect --format='{{json .State.Health}}' backend
```

---

# 19. Final production check

After any deployment, run:

```bash
docker ps
```

You want:

```text
frontend   Up ... (healthy)
backend    Up ... (healthy)
```

Then:

```bash
docker exec frontend sh -c "wget -qO- http://127.0.0.1:3000/ > /dev/null && echo 'Frontend OK'"
```

And:

```bash
docker exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

Then open:

```text
http://YOUR_EC2_PUBLIC_IP:3000
```

Finally run **one real AgentBoard debate**.

---

## The workflow to remember

You can reduce the whole deployment process to this:

```text
┌──────────────────────┐
│ Change code locally  │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ Test locally         │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ docker build         │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ docker push → GHCR   │
└──────────┬───────────┘
           ↓
       EC2 browser
           ↓
┌──────────────────────┐
│ docker pull          │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ stop old container   │
│ rm old container     │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ docker run new       │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ docker ps            │
│ health check         │
│ docker logs          │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ Browser test         │
│ Real AgentBoard test │
└──────────────────────┘
```

### Most important rule

**If you change only frontend code → update frontend only.**

**If you change only backend code → update backend only.**

**If you change both → update both.**

You don't need to rebuild or recreate the other container unnecessarily.

This is now your **baseline deployment procedure** for AgentBoard.