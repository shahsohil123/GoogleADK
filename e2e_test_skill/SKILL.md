---
name: checkout-e2e
description: Run the full end-to-end checkout regression test against the local target app. Use whenever the user says "run e2e", "test the checkout flow", "smoke test the shop", or before tagging a release of the shop service. Boots the target app if needed, drives the full signup-to-confirmation flow, asserts a known-good total, verifies the confirmation email landed in the outbox, exercises the bad-card rejection path, and writes a Markdown run report to reports/.
---

# checkout-e2e

A SKILL.md that replaces the 30-step manual checkout regression runbook
([manual_runbook.md](manual_runbook.md)) with a single instruction Claude can
follow end-to-end.

## When to use

Trigger this skill any time the user asks to:
- run the e2e / smoke / regression test for the shop
- verify the checkout flow before a release
- reproduce or debug a checkout-path bug

Do NOT use this skill for unit tests, load tests, or anything that needs to
hit a non-local environment — this drives the in-process Flask app on
`127.0.0.1:5005` only.

## Preconditions

- Python 3.10+ on PATH.
- Working directory is the repo root or `e2e_test_skill/`.
- Port 5005 is free. If it's bound by a stale run of this skill, stop the
  background job rather than killing arbitrary processes.

## Procedure

Execute the steps in order. Stop on the first failure and surface the report
path; do not retry silently.

### 1. Install dependencies (idempotent)

```bash
pip install -q -r e2e_test_skill/target_app/requirements.txt
```

### 2. Start the target app in the background

```bash
python e2e_test_skill/target_app/app.py
```

Run this with `run_in_background: true`. Then poll `GET /health` until it
returns 200 (max 10 tries, 0.5s apart). If it never comes up, read the
background output and report the error — do not proceed.

### 3. Reset state and run the E2E driver

```bash
curl -s -X POST http://127.0.0.1:5005/admin/reset > /dev/null
python e2e_test_skill/scripts/run_e2e.py > /tmp/e2e_summary.json
```

The driver exits non-zero on any failed assertion. Capture the exit code —
you'll need it for the verdict line.

### 4. Render the Markdown report

```bash
python e2e_test_skill/scripts/write_report.py < /tmp/e2e_summary.json
```

This prints a relative path like `reports/run-20260513-101530.md`. Read that
file and quote the verdict line plus any failed step rows back to the user.

### 5. Stop the background app

Kill the background bash shell started in step 2. Do not leave it running
after the skill completes.

## Reporting back

Reply to the user with exactly three things:

1. **Verdict** — `PASS` or `FAIL` and the pass/fail counts.
2. **Report path** — clickable link to the file written in step 4.
3. **First failure detail** (FAIL only) — step name and the assertion error.

Keep it under 6 lines. The user will open the report for the rest.

## Failure modes to recognize

- **Port 5005 in use** → A previous run leaked. Tell the user; don't `kill -9`.
- **`expected total 33.00, got X`** → Pricing regression in `target_app/app.py`.
  Surface the diff, don't auto-fix.
- **`no confirmation email for ...`** → The order persisted but the email
  side-effect didn't fire. Most likely cause is a regression in the
  `/checkout` handler — flag for human review.
- **`expected 402 for bad card, got 200`** → Card validation broke. Treat
  this as a security regression and stop; do not write a "passing" report.
