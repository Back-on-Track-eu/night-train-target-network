# Energy Model — Contributor Onboarding Guide

Welcome to the energy model workstream for the Back-on-Track Night Train Target Network project!

This guide gets you set up and oriented in under an hour.
You do not need any knowledge of the broader backend — just Python and a curiosity about trains.

---

## What is this project?

Back-on-Track is building an open-source tool to evaluate the economics of night train
routes across Europe. One key input is how much electricity a night train consumes —
that's what this workstream is about.

Your job: figure out how much energy a night train uses per kilometre, depending on
how heavy it is, how fast it goes, and how hilly the terrain is.

---

## What you will be working on

The energy model lives in `backend/models/energy/`. Right now it uses a rough
placeholder (a flat 28 kWh/km regardless of conditions).

Your task — from first principles — is:

1. **Find the right formula.** We have a hypothesis (see `README.md`) but you should
   verify it through data exploration. What variables actually predict energy consumption?
   Is the relationship linear? Are there interaction effects?

2. **Calibrate the coefficients.** Once you have a formula, fit it against real train
   energy data from the Deutsche Bahn Trassenfinder API and derive the numerical values
   for each factor.

3. **Validate and document.** How well does the model fit? What are the limitations?
   Write up your findings in a notebook and the decisions log in `README.md`.

The inputs available to the model are: train weight (tonnes), distance (km),
average speed (km/h), and terrain score (a country-level difficulty index).
The output is energy consumption in kWh.

Everything else — how you structure the formula, which variables matter most,
how you collect and clean the training data — is yours to figure out.
That's the interesting part.

See `README.md` in this folder for more technical detail and a step-by-step task list.

---

## Before we meet — getting your machine ready

Hey, welcome to the team! Before we meet, there are a few things to set up on your
machine. None of this is hard, but it's important to do it beforehand so we can hit
the ground running rather than spending the time on installations.

If anything below is confusing or doesn't work — don't stress, just message me and
we'll sort it out.

---

### Step 1 — Create a GitHub account

GitHub is where our code lives. Think of it as Google Drive, but for code — with a
superpower: it tracks every change ever made, by whom, and why.

👉 Go to [github.com](https://github.com/) and create a free account.

Once you have one, send me your GitHub username so I can give you access to the
repository.

---

### Step 2 — Install Git

Git is the tool that actually talks to GitHub from your computer. You need both.

- **Windows:** Download and install from [git-scm.com](https://git-scm.com/). Accept
  all the defaults during installation.
- **Mac:** Open the Terminal app and run `git --version`. If Git isn't installed yet,
  macOS will prompt you to install it automatically.
- **Linux:** Run `sudo apt install git` (Ubuntu/Debian) or the equivalent for your distro.

Verify it works — open a terminal (on Windows: search for "Git Bash" or "Command Prompt")
and run:

```
git --version
```

You should see something like `git version 2.x.x`. If you do — ✅ you're good.

---

### Step 3 — Install Python

We need Python 3.11 or higher.

- **Windows:** Download from [python.org/downloads](https://www.python.org/downloads/).
  During installation, make sure to tick **"Add Python to PATH"** — this is easy to miss
  and important.
- **Mac/Linux:** Python may already be installed. Check with:

```
python3 --version
```

If it shows 3.11 or higher — ✅ you're good. If not, download from
[python.org](https://www.python.org/downloads/).

---

### Step 4 — Install uv

`uv` is a modern Python package manager — it handles installing all the project's
dependencies for you automatically. Think of it as the tool that makes sure everyone
on the team has exactly the same Python setup.

Run this in your terminal:

- **Mac/Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- **Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installation, close and reopen your terminal, then verify:

```
uv --version
```

You should see a version number. ✅

---

### Step 5 — Install PyCharm

PyCharm is the code editor we use. The free Community Edition is all you need.

👉 Download from [jetbrains.com/pycharm/download](https://www.jetbrains.com/pycharm/download/)
— scroll down to **Community Edition** (the free one).

Install it and open it once just to make sure it launches fine. You don't need to
configure anything yet — we'll do that together.

---

### Quick checklist

Run through this — if all five are ticked, you're fully prepared:

- [ ] GitHub account created and username sent to David
- [ ] `git --version` works in a terminal
- [ ] `python --version` (or `python3 --version`) shows 3.11+
- [ ] `uv --version` works in a terminal
- [ ] PyCharm installed and opens without errors

---

### One thing to read (optional but useful)

If you have 10 minutes to spare, this short visual explainer is a great intro to how
Git and GitHub work conceptually:

👉 [guides.github.com/introduction/git-handbook](https://guides.github.com/introduction/git-handbook/)

Don't worry about understanding everything — just getting a feel for the vocabulary
(repository, branch, commit, pull request) will make our first session much smoother.

---

## Setting up your environment

Once the above checklist is done, you're ready to clone the repo and start working.

**1. Clone the repository**

```bash
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network/backend
```

**2. Install dependencies**

```bash
uv sync --extra dev
```

This installs everything — pandas, scikit-learn, statsmodels, JupyterLab, and the
backend library itself (importable as `models`).

**3. Start JupyterLab**

```bash
uv run jupyter lab --notebook-dir models/energy/notebooks
```

The `--notebook-dir` flag sets the root directory of JupyterLab to the notebooks
folder — so when it opens in your browser you land directly in the right place
rather than the full project tree.

If the browser doesn't open automatically, copy the URL from the terminal output
(it looks like `http://localhost:8888/lab?token=...`) and paste it into your browser.

---

## Your first steps

**Step 1 — Read the formula**

Open `README.md` in this folder. Read the formula section and the parameter table.
Make sure you understand what each variable means physically.

**Step 2 — Look at the dummy implementation**

Open `calc_energy_consumption.py`. It's short — read through it.
Notice what it does (flat factor) and what it should do (use the formula).

**Step 3 — Explore the Trassenfinder API**

Open a new Jupyter notebook and make a test request to the Trassenfinder API.
The goal is just to understand the response structure.

```python
import requests

# Example: Berlin Hbf (UIC 8011160) to Wien Hbf (UIC 8101003)
# Check the Trassenfinder docs for the exact endpoint and parameters
response = requests.get("https://trassenfinder.de/api/...")
print(response.json())
```

Find out which field in the response gives energy consumption.
Document it in your notebook.

**Step 4 — Check the task list**

Read through the task checklist in `README.md`. Pick the first unchecked task and start.

---

## How to contribute

**Branch workflow:**

```bash
# Always start from a fresh main
git checkout main
git pull

# Create your branch
git checkout -b energy/trassenfinder-collector
```

**Commit often** with short, descriptive messages:
```bash
git commit -m "energy: add trassenfinder collector skeleton"
git commit -m "energy: collect 50 sample routes"
```

**Open a PR** when a task from the checklist is complete.
Tag David Wedekind (`david@backontrack.eu`) for review.

**Coordinate before starting** — send a short message on Signal or email
before picking up a task so we avoid duplicate work.

---

## Useful background reading

- [OpenRailRouting](https://openrailrouting.org) — the routing engine we use
- [Deutsche Bahn Trassenfinder](https://trassenfinder.de) — our calibration data source
- [GTFS specification](https://gtfs.org/schedule/reference/) — the transit data format we export to
- Back-on-Track website: https://back-on-track.eu

---

## Questions?

Join our Signal group for questions, updates, and coordination:

👉 https://signal.group/#CjQKID4SnWmddEW6VXyJ7zbqngLWtuDu2Caey_yw6tOUEEw2EhC4scdb6HtEFZt_Of-pIu5_

There are no stupid questions — the onboarding guide itself improves from your feedback.