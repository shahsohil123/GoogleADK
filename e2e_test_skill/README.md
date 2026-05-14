# E2E Test Skill

> A worked example of how a single **SKILL.md** file collapses a
> manual-intensive regression runbook into a one-line trigger
> ("run e2e") that Claude executes end-to-end — boots the system under test,
> drives the full user journey, asserts the side-effects, and writes a
> Markdown report.

![purpose](https://img.shields.io/badge/purpose-demo-blue) ![runtime](https://img.shields.io/badge/runtime-Python%203.10+-3776AB) ![target-app](https://img.shields.io/badge/target--app-Flask-000000)

---

## What this demonstrates

- **A real SKILL.md anatomy.** Frontmatter (`name`, `description`) that
  Claude uses to decide *when* to fire the skill, plus a procedural body that
  tells Claude *how* to execute it — preconditions, ordered steps, failure
  modes, and a strict reporting contract.
- **A manual process worth automating.** [`manual_runbook.md`](manual_runbook.md)
  reproduces the 30-step regression QA used to run by hand: ~12 minutes,
  ~4 documented failure modes a week, plus a tendency to skip the security
  check under deadline pressure.
- **The automation that replaces it.** [`SKILL.md`](SKILL.md) is the
  *exact* file Claude loads — no glue code, no harness — that drives a
  signup → cart → checkout → email-verification → cleanup flow against a
  local target app and emits a Markdown verdict.

---

## Module layout

```
e2e_test_skill/
├── README.md            # you are here
├── SKILL.md             # ← the skill Codex loads (the AFTER)
├── manual_runbook.md    # the 30-step manual process (the BEFORE)
├── target_app/
│   ├── app.py           # tiny Flask shop: signup / login / cart / checkout / outbox
│   └── requirements.txt
├── scripts/
│   ├── run_e2e.py       # drives the full happy + sad path, prints JSON summary
│   └── write_report.py  # renders JSON → reports/run-<ts>.md
└── reports/             # one Markdown file per run
```

---

## Try it

From the repo root:

```bash
pip install -r e2e_test_skill/target_app/requirements.txt
```

Then, in any Claude Code session that has loaded this `SKILL.md`, simply say:

> **run e2e**

Claude will:

1. Boot `target_app/app.py` in the background.
2. Poll `/health` until ready.
3. Reset state, run [`scripts/run_e2e.py`](scripts/run_e2e.py).
4. Pipe the JSON summary into [`scripts/write_report.py`](scripts/write_report.py).
5. Stop the background app.
6. Reply with a 3-line verdict + a clickable link to the report.

If you'd rather run it without Claude (to sanity-check the plumbing):

```bash
# terminal 1
python e2e_test_skill/target_app/app.py

# terminal 2
python e2e_test_skill/scripts/run_e2e.py | python e2e_test_skill/scripts/write_report.py
```

---

## BEFORE vs. AFTER

| Dimension | Manual runbook | SKILL.md |
|---|---|---|
| Steps a human executes | 30 | 1 (utter the trigger phrase) |
| Wall time | ~12 min | ~3 sec |
| Skipped-step rate | ~1 in 4 runs | 0 |
| Auth-header mistakes | ~1 in 8 runs | 0 |
| Fabricated latencies in the report | ~1 in 4 runs | 0 (measured by the driver) |
| Security check (bad-card path) skipped | ~1 in 10 runs | 0 (asserted by the driver) |
| Output | Hand-written Markdown of variable quality | Deterministic `reports/run-<ts>.md` |

---

## Why a SKILL.md and not a shell script?

A shell script automates the *steps*. A SKILL.md also automates the
*decision to run it* — the `description:` line is what lets Claude
recognize "run the smoke test before I cut a release" or "is checkout
healthy?" as the same intent — and the *failure handling* (the "Failure
modes to recognize" section tells Claude when to stop, when to ask, and when
to file the result as a security regression rather than a pass).

The shell script is still there — it's just one of the tools the skill
orchestrates, alongside background process management, file I/O, and the
reporting contract back to the user.
