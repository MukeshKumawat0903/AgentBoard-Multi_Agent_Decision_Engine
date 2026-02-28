# AgentBoard – How to Run

Step-by-step guide to set up and run both the **backend** (FastAPI) and **frontend** (Next.js).

---

## Prerequisites

| Tool         | Minimum version | Download                          |
| ------------ | --------------- | --------------------------------- |
| Python       | 3.11+           | https://www.python.org/downloads/ |
| Node.js      | 18+ (LTS)       | https://nodejs.org/               |
| GROQ API Key | —              | https://console.groq.com/         |

---

## 1. Clone / open the project

```bash
cd AgentBoard-Multi_Agent_Decision_Engine
```

---

## 2. Backend setup

### 2.1 Create the virtual environment

```powershell
# Windows (PowerShell)
cd backend
python -m venv venv
.\venv\Scripts\activate
```

```bash
# macOS / Linux
cd backend
python3 -m venv venv
source venv/bin/activate
```

### 2.2 Install dependencies

```bash
pip install -r requirements.txt
```

> Install dev tools (pytest etc.) as well if you want to run tests:
>
> ```bash
> pip install -r requirements-dev.txt
> ```

### 2.3 Create the environment file

Copy the example and fill in your GROQ API key:

```powershell
# Windows
copy .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

Open `.env` and set your key:

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=llama-3.3-70b-versatile
MAX_DEBATE_ROUNDS=4
CONSENSUS_THRESHOLD=0.75
LOG_LEVEL=INFO
```

> Get your free API key at https://console.groq.com/

### 2.4 Start the backend server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now running at **http://localhost:8000**

- Swagger UI (interactive docs): http://localhost:8000/docs
- ReDoc:                          http://localhost:8000/redoc
- Health check:                   http://localhost:8000/health

---

## 3. Frontend setup

Open a **new terminal window** (keep the backend running).

### 3.0 One-time: Install Node.js (skip if already installed)

**Check if Node.js is already installed:**

```powershell
node --version   # should print v18.x or higher
npm --version    # should print a version number
```

If either command says "not recognised", install Node.js:

```powershell
# Option A – winget (Windows 10/11 built-in package manager) – recommended
winget install OpenJS.NodeJS.LTS

# Option B – download the installer manually
# https://nodejs.org/  →  click "LTS" and run the .msi
```

After installation, **refresh PATH in your current terminal** (or just open a new terminal window):

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```

Verify it worked:

```powershell
node --version   # e.g. v24.x.x
npm --version    # e.g. 11.x.x
```

> You only need to do this once per machine. New terminal windows opened after installation will have `npm` available automatically.

---

### 3.1 Install Node.js dependencies

```bash
cd frontend
npm install
```

> This installs Next.js 15, React 18, Tailwind CSS, TypeScript, and all type definitions.
> Run this once; you don't need to repeat it unless `package.json` changes.

### 3.2 Configure the API URL (optional)

The file `frontend/.env.local` already points to the local backend:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Change this only if your backend runs on a different host/port.

### 3.3 Start the frontend dev server

```bash

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

cd "d:\Learnings\My_Projects\Learning_Projects\AgentBoard-Multi_Agent_Decision_Engine\frontend"

npm run dev
```

The app is now running at **http://localhost:3000**

---

## 4. Using the application

1. Open **http://localhost:3000** in your browser.
2. Type a strategic question in the debate input (minimum 10 characters).
3. Optionally adjust the **Max rounds** slider (2–8, default 4).
4. Click **Start Debate**.
5. Wait 30–90 seconds while the 5 AI agents debate:
   - 📊 **Analyst** – objective data analysis
   - 🛡️ **Risk** – adversarial risk assessment
   - ♟️ **Strategy** – actionable strategy
   - ⚖️ **Ethics** – ethical review
   - 🧭 **Moderator** – synthesis and convergence
6. View the **Final Decision**, confidence scores, risk flags, and the full debate trace.
7. Use **Download JSON** to export the complete decision for later review.

---

## 5. Running tests (backend)

```bash
# Make sure the venv is active and you're in backend/
cd backend
.\venv\Scripts\activate        # Windows
# or: source venv/bin/activate # macOS/Linux

# Run all unit tests (no GROQ API calls, fast)
pytest -v --tb=short

# Run a single test file
pytest tests/test_consensus.py -v

# Run only tests matching a keyword
pytest -k "test_agreement" -v

# Run integration tests that call the real GROQ API (slower, requires .env)
pytest -m integration -v --timeout=120

# Skip integration tests
pytest -m "not integration" -v
```

---

## 6. Environment variable reference

| Variable                | Required | Default                     | Description                                      |
| ----------------------- | -------- | --------------------------- | ------------------------------------------------ |
| `GROQ_API_KEY`        | ✅ Yes   | —                          | Your GROQ API key                                |
| `GROQ_MODEL`          | No       | `llama-3.3-70b-versatile` | LLM model name                                   |
| `MAX_DEBATE_ROUNDS`   | No       | `4`                       | Maximum debate rounds per session                |
| `CONSENSUS_THRESHOLD` | No       | `0.75`                    | Agreement score required to stop early           |
| `LOG_LEVEL`           | No       | `INFO`                    | Logging level (`DEBUG`, `INFO`, `WARNING`) |
| `NEXT_PUBLIC_API_URL` | No       | `http://localhost:8000`   | Backend URL used by the frontend                 |

---

## 7. API endpoints

| Method   | Path                      | Description                                        |
| -------- | ------------------------- | -------------------------------------------------- |
| `GET`  | `/health`               | Health check – returns version and status         |
| `POST` | `/debate/start`         | Start a debate and wait for the final decision     |
| `GET`  | `/debate/{thread_id}`   | Get live status and round history of a debate      |
| `GET`  | `/decision/{thread_id}` | Retrieve the final decision for a completed debate |

### Example: start a debate via curl

```bash
curl -X POST http://localhost:8000/debate/start \
  -H "Content-Type: application/json" \
  -d '{"query": "Should our company expand into the Asian market in Q3?", "max_rounds": 3}'
```

---

## 8. Production build (frontend)

```bash
cd frontend
npm run build      # compiles and optimises the Next.js app
npm start          # starts the production server on port 3000
```

---

## 9. Quick-start summary

```
Terminal 1 – Backend
─────────────────────────────────────────
cd backend
python -m venv venv && .\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then add GROQ_API_KEY
uvicorn app.main:app --reload --port 8000

Terminal 2 – Frontend
─────────────────────────────────────────
cd frontend
npm install
npm run dev
```

Then open **http://localhost:3000** and start debating.
