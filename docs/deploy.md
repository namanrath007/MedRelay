# Deploying MedRelay (free)

## Option A - Streamlit Community Cloud (recommended)

Streamlit Cloud runs `dashboard/app.py`. On first load the dashboard sets everything else up itself:
it rebuilds the synthetic data if missing and starts the mock portal API (:8001) and FHIR API (:8002)
in the background. Visitors only ever see the dashboard.

### 1. Prepare (on your laptop, inside the project folder)

```bash
python scripts/simulate_drift.py --reset     # drift demo back to its start
python scripts/smoke_test.py                 # 6 x PASS
ls outputs generated                         # your real results - these MUST be committed
git status                                   # .env must NOT be listed
```

### 2. Push to a GitHub repository

The free tier deploys public repos (one private app is allowed). The data is synthetic, so public is fine.

```bash
git add .
git commit -m "MedRelay: deployable version"
git push
```

(No repo yet? Create an empty one on github.com named `medrelay`, then
`git remote add origin https://github.com/<you>/medrelay.git && git branch -M main && git push -u origin main`.)

### 3. Deploy

1. Go to **share.streamlit.io** → sign in with GitHub → **Create app** → deploy from GitHub.
2. Repository: `<you>/medrelay` · Branch: `main` · Main file path: **`dashboard/app.py`**.
3. **Advanced settings** → Python version **3.11** (or 3.12) → **Secrets**, paste:

```toml
GEMINI_API_KEY = "your-gemini-key"
ADMIN_PASSWORD = "your-team-password"
DEMO_MODE = "1"
GEMINI_MODEL = "gemini-3.5-flash-lite"
```

4. **Deploy**. The first load takes a minute or two (installing packages, then "Starting MedRelay services").

Your link looks like `https://<something>.streamlit.app` - put it on slide 6 ("Final product / deployed link").

### Demo mode (DEMO_MODE=1)
Visitors can browse every page, use Patient 360, run the drift demo and ask the assistant 5 questions.
Running agents, approving and saving need the team password in the sidebar - so strangers can't use up
your Gemini quota or change your results.

### Good to know
- **Updating:** `git push` - the app redeploys automatically.
- **Sleeping:** apps sleep after many hours without visitors; open the link before judging to wake it.
- **Resets:** changes made in the demo (approvals, drift) reset when the app restarts.

## Option B - Render (Docker, free tier)

Uses the included `Dockerfile` + `start.sh`. On render.com: **New → Web Service** → connect the GitHub repo
→ Runtime **Docker** → instance type **Free** → add the same values under **Environment** → Deploy.
Free instances are small (512 MB) and sleep after 15 minutes idle, taking about a minute to wake.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Pages say "Not built yet" | `outputs/` or `generated/` weren't pushed - commit them and push |
| Assistant says quota used up | Gemini free quota; change `GEMINI_API_KEY` in Secrets or wait for the reset |
| "Starting services" never finishes / pipeline can't reach :8001 | check the app logs (Manage app → logs); reboot the app from the menu |
| ModuleNotFoundError | `requirements.txt` must be in the repo root; reboot after fixing |
