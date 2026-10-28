# Fix Tournament

**Give it a failing test. Eight Nemotron agents race to fix it. The test suite picks the winner.**

Most coding agents are a single loop that you have to trust. Fix Tournament turns bug-fixing into a
race with an objective referee: many differently-prompted contestants patch the same bug in parallel,
every patch is judged by the project's own tests, and only a verified, minimal, non-cheating fix
becomes a pull request.

Built for the Nebius x NVIDIA Global AI Hackathon, Coding and Agentic Engineering track. MIT licensed.

## How a run works

| Phase | What happens | Model |
|---|---|---|
| 1. Reproduce | Run the suite on the untouched repo and record exactly which tests fail. If nothing fails, stop. | none |
| 2. Diagnose | Reads the issue, failure output and sources; writes down what a correct fix must guarantee. | **Nemotron Ultra** |
| 3. Race | Up to 8 contestants (Nano and Super x four strategies: minimal, root cause, defensive, refactor) patch in parallel. Each gets up to 3 turns and sees its own test failures between turns. | **Nemotron Nano / Super** |
| 4. Verify | Best patch is re-run 3 times to reject flaky passes. Runner checks the suite still collects every original test. | none |
| 5. Review | Risk rating, root cause, follow-ups, a static blast-radius report (who calls the changed functions) and a PR description. | **Nemotron Ultra** |

### What makes the result trustworthy

- **Tests are the judge, not the model.** Pass/fail comes from junit XML, per test.
- **No cheating.** Editing tests, `conftest.py` or pytest config is an immediate disqualification. A contestant that makes tests disappear fails the collected-test-count check.
- **Flake check.** A winner must be green on three consecutive re-runs.
- **Scoring (100):** 60 correctness, 25 minimal diff, 10 speed, 5 cost. Scores are relative to the best passing contestant, which is why a winner often shows 100.
- **Cost story.** The UI compares tiered routing (Ultra only for diagnosis and review) with running every call on Ultra. Prices are illustrative placeholders: set `FT_PRICE_*` to real ones.

## Run it

```bash
pip install -r requirements.txt
python -m fixtournament serve            # http://127.0.0.1:8000
```

With no API key the app runs in **Replay** mode: the sandbox, tests, scoring, verification and
blast-radius analysis are all real, but contestant and Ultra replies come from recorded scripts
(`fixtournament/cases/*/replay.py`). The UI badge always says `REPLAY` or `LIVE`, never pretends.

**Live mode** (real Nemotron on Nebius Token Factory):

```bash
export NEBIUS_API_KEY=...
export FT_MODEL_NANO=... FT_MODEL_SUPER=... FT_MODEL_ULTRA=...   # ids from your Token Factory catalogue
python -m fixtournament serve
```

Terminal only: `python -m fixtournament run --case slugger --patch fix.patch`

Tests: `python -m pytest -q` (24 tests; includes whole races and the Token Factory client against a mocked endpoint).

## Nebius and NVIDIA usage

- **Nemotron Ultra** diagnoses the bug and reviews the winning patch. **Nano and Super** are the contestants.
- **Token Factory** is called through its OpenAI-compatible chat completions API (`fixtournament/llm.py`). Parallel contestants are what make fast inference matter: eight agents x up to three turns hit the endpoint concurrently.
- **Serverless Jobs:** `FT_RUNNER=job` runs every candidate's test suite through `FT_JOB_SUBMIT_CMD`, one job per candidate. The job runs `python -m fixtournament.worker` from this repo's `Dockerfile` image; the stdin/stdout protocol is in `fixtournament/runners.py`. You supply the command that submits a job with your Nebius account.
- **Serverless Endpoints:** deploy the `Dockerfile` image as the web app (port 8000).

## Bring your own repo

`FT_ALLOW_CUSTOM=1` enables a form that clones a public GitHub repo, optionally pulls an issue, and
runs the race on it (Python and pytest only). **This executes that repository's code on the server.**
Only enable it inside a container or job sandbox. With `FT_GITHUB_TOKEN` it can push a branch and open a PR.

## Honest status

| Verified in the build environment | Not verified |
|---|---|
| Whole races on both demo bugs, both modes (sprint/qualify) | Live calls to the real Token Factory with real Nemotron (no key available); only tested against a mocked endpoint |
| Sandbox, timeouts, tamper detection, flake check, junit parsing | Exact Nemotron model ids and prices: set them yourself |
| Job runner protocol (run locally via `fixtournament.worker`) | An actual Nebius Serverless Job submission |
| UI in headless Chromium: full run, no console errors | Docker image build, GitHub PR opening, custom-repo cloning |

Process isolation is a throwaway copy, rlimits and a scrubbed environment, **not** a network sandbox.
Use the job runner or a container for untrusted code.

## Layout

```
fixtournament/   tournament.py (orchestrator) agent.py (contestant loop) sandbox.py patching.py
                 analysis.py llm.py runners.py worker.py server.py service.py cases/
web/             index.html app.css app.js assets/    (no build step)
tests/           engine and live-client tests
docs/            SUBMISSION.md (Devpost text, video script, feedback log)
```
