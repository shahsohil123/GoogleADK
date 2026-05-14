# Manual Checkout Regression Runbook (BEFORE)

> This is the runbook QA followed every release before [SKILL.md](SKILL.md)
> existed. Reproduced verbatim so you can see what got automated. 30 steps,
> ~12 minutes of human attention per run, easy to skip a step under pressure.

## Pre-flight (≈2 min)

1. Confirm you're on the right branch (`git status`).
2. `cd e2e_test_skill/target_app`.
3. `python -m venv .venv && source .venv/bin/activate`.
4. `pip install -r requirements.txt`.
5. Make sure port 5005 isn't held by yesterday's stale run (`lsof -i :5005`).
   If it is, find the PID and decide whether it's safe to kill.
6. Start the app: `python app.py`. Leave the terminal open.
7. In a second terminal, `curl http://127.0.0.1:5005/health` and eyeball the
   JSON. If `status` isn't `"ok"`, go back to step 6.

## Happy path (≈5 min)

8. Reset state: `curl -X POST http://127.0.0.1:5005/admin/reset`.
9. Pick a unique test email. Write it on a sticky note — you'll need it three
   more times.
10. Sign up:
    ```
    curl -X POST http://127.0.0.1:5005/signup \
      -H 'content-type: application/json' \
      -d '{"email":"<sticky>","password":"hunter2!"}'
    ```
    Confirm HTTP 201 and copy the `user_id`.
11. Log in (same payload, different endpoint). Copy the `token`.
12. Add 2x SKU-COFFEE to cart — remember to send the `Authorization: Bearer
    <token>` header. Forgetting this is the #1 mistake.
13. Add 1x SKU-MUG to cart.
14. Eyeball the returned `total`. It should be `33.00`. If it isn't, stop and
    file a pricing bug.
15. Check out with card `4242 4242 4242 4242`. Confirm HTTP 200 and `status:
    confirmed`. Copy the `order_id`.
16. `GET /orders/<order_id>` with the bearer token. Confirm `email_sent: true`.
17. `GET /admin/outbox`. Find the row whose `to` matches your sticky-note
    email. Confirm the subject mentions the order id.

## Sad path (≈2 min)

18. Add another item to cart (SKU-BEANS).
19. Try to check out with card `111`. Confirm HTTP 402 and that NO new row
    appears in `/admin/outbox`.
20. If you got a 200 here, stop everything — this is a security regression.

## Reporting (≈3 min)

21. Open `reports/` and create a new file `run-YYYYMMDD-HHMMSS.md`.
22. Title it with PASS or FAIL.
23. Note your test email and order id.
24. Walk back through your terminal history and record the latency of each
    step (you were supposed to be timing these — most people forget).
25. List any step that returned an unexpected status.
26. Paste the failed assertion text verbatim if there was one.
27. Save the file. Commit it (or don't — team policy varies).

## Cleanup (≈1 min)

28. Kill the `python app.py` process in your first terminal.
29. Deactivate the venv.
30. Slack the report path to #release-eng.

---

## What goes wrong

In practice, on a typical week:

- **~1 in 5 runs** someone skips step 5 and hits a port-in-use error two minutes in.
- **~1 in 8 runs** someone forgets the `Authorization` header on step 12 and
  spends five minutes debugging a 401 that's their fault.
- **~1 in 4 runs** the timing column in the report is fabricated.
- **~1 in 10 runs** the bad-card check (step 19) gets skipped under deadline
  pressure. This is the single most expensive step to skip.

The skill in [SKILL.md](SKILL.md) collapses all 30 steps into one trigger
phrase ("run e2e") and removes every one of those failure modes by
construction.
