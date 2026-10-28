# Submission kit

## Devpost: project description (paste and edit)

**Fix Tournament** turns bug-fixing into a race with an objective referee.

**What it does.** You give it a failing test suite and an issue. It reproduces the failure, has
Nemotron Ultra diagnose it, then launches up to eight competing fix attempts in parallel (Nemotron
Nano and Super, each with a different strategy). Every attempt is judged by the project's own tests.
The winner must be green three times in a row, must not have touched tests or test config, and is
ranked by a transparent score (correctness, minimal diff, speed, cost). Ultra then reviews the
winning patch, a static analysis reports its blast radius, and the app drafts the pull request.

**Why.** A single agent loop asks you to trust one answer. A tournament gives you evidence: eight
independent attempts, one objective judge, and an audit trail of how each contestant failed,
including which ones tried to cheat.

**How we use Nemotron and Nebius.** Ultra for planning and review, Nano and Super for the fast,
numerous patch attempts, all through Token Factory's OpenAI-compatible API. Each candidate's test
run can execute as its own Serverless Job (`FT_RUNNER=job`); the web app ships as one container for
Serverless Endpoints. Tiered routing is visible in the verdict as a cost comparison against
all-Ultra.

**Challenges.** Making contestants unable to win by cheating (protected paths, collected-test-count
check), making runs repeatable (junit parsing, flake re-runs), and keeping the live view honest
(a persistent REPLAY/LIVE badge).

**What's next.** More languages than Python, SWE-bench-style evaluation, and learning which tier
and strategy wins for which kind of bug.

## 3-minute video script

| Time | Show | Say |
|---|---|---|
| 0:00-0:15 | Idle screen, slugger case | "Coding agents ask you to trust one answer. Fix Tournament makes eight of them race, and lets the test suite decide." |
| 0:15-0:40 | Click Start. Reproduce, then Ultra's diagnosis | "First it proves the bug: four of thirteen tests fail. Nemotron Ultra writes the diagnosis." |
| 0:40-1:30 | Race. Cars move, lanes re-order | "Nano and Super contestants patch in parallel. Watch this one fail its first attempt, read the test output, and fix it on turn two." |
| 1:30-1:50 | Disqualified lane, click it | "This one edited a test to make it pass. Disqualified automatically." |
| 1:50-2:20 | Verify, then verdict | "The winner is re-run three times, then Ultra reviews it. Smallest correct diff wins." |
| 2:20-2:45 | Cost bars, blast radius, PR draft | "Using Ultra only where reasoning matters cuts cost by more than half. The PR is drafted with evidence." |
| 2:45-3:00 | Switch to the intervals case, LIVE badge | "Same engine, different bug. Powered by Nemotron on Nebius Token Factory." |

Record in LIVE mode if your key works; if you show REPLAY, say so in the video.
Do not use copyrighted music.

## Feedback log (required by the rules): fill in as you build

Keep specifics: what you tried, what happened, what you expected, the fix you'd suggest.

**Token Factory**
- Model ids available and how you found them:
- Rate limits hit with 8 parallel contestants:
- Latency per tier (Nano / Super / Ultra), tokens per patch attempt:
- Reasoning ("think") output: did it appear in `content`? Did stripping it work?
- Docs gaps:

**Nemotron models**
- Which tier followed the SEARCH/REPLACE format reliably:
- Where Nano fell short, where Super was enough, where Ultra was needed:

**Nebius Serverless Jobs / Endpoints**
- Cold start time, job submission ergonomics, log access:
- What would make one-job-per-candidate easier:
