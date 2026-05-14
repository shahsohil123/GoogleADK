"""End-to-end checkout test, invoked by SKILL.md step 3.

Walks the full happy path: signup -> login -> add to cart -> checkout ->
verify order -> verify confirmation email landed in the outbox. Exits non-zero
on the first failed assertion and prints a JSON summary to stdout so the skill
can pipe it into the report.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
import requests

BASE = "http://127.0.0.1:5005"


def step(name, fn):
    t0 = time.time()
    try:
        result = fn()
        return {"step": name, "ok": True, "ms": int((time.time() - t0) * 1000), "result": result}
    except AssertionError as e:
        return {"step": name, "ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)}
    except Exception as e:
        return {"step": name, "ok": False, "ms": int((time.time() - t0) * 1000), "error": f"{type(e).__name__}: {e}"}


def main():
    email = f"qa+{uuid.uuid4().hex[:8]}@example.com"
    password = "hunter2!"
    state = {}
    steps = []

    def health():
        r = requests.get(f"{BASE}/health", timeout=2)
        assert r.status_code == 200, f"health {r.status_code}"
        return r.json()

    def signup():
        r = requests.post(f"{BASE}/signup", json={"email": email, "password": password}, timeout=2)
        assert r.status_code == 201, f"signup {r.status_code} {r.text}"
        state["user_id"] = r.json()["user_id"]
        return r.json()

    def login():
        r = requests.post(f"{BASE}/login", json={"email": email, "password": password}, timeout=2)
        assert r.status_code == 200, f"login {r.status_code} {r.text}"
        state["token"] = r.json()["token"]
        return {"token": state["token"][:8] + "..."}

    def add_cart():
        h = {"Authorization": f"Bearer {state['token']}"}
        requests.post(f"{BASE}/cart/add", json={"sku": "SKU-COFFEE", "qty": 2}, headers=h, timeout=2)
        r = requests.post(f"{BASE}/cart/add", json={"sku": "SKU-MUG", "qty": 1}, headers=h, timeout=2)
        assert r.status_code == 200, f"cart_add {r.status_code}"
        body = r.json()
        assert body["total"] == 33.00, f"expected total 33.00, got {body['total']}"
        return body

    def checkout():
        h = {"Authorization": f"Bearer {state['token']}"}
        r = requests.post(f"{BASE}/checkout", json={"card": "4242424242424242"}, headers=h, timeout=2)
        assert r.status_code == 200, f"checkout {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "confirmed"
        state["order_id"] = body["order_id"]
        return body

    def verify_order():
        h = {"Authorization": f"Bearer {state['token']}"}
        r = requests.get(f"{BASE}/orders/{state['order_id']}", headers=h, timeout=2)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "confirmed"
        assert body["email_sent"] is True
        return body

    def verify_email():
        r = requests.get(f"{BASE}/admin/outbox", timeout=2)
        emails = r.json()["emails"]
        match = [e for e in emails if e["to"] == email]
        assert match, f"no confirmation email for {email}"
        return match[0]

    def reject_bad_card():
        h = {"Authorization": f"Bearer {state['token']}"}
        requests.post(f"{BASE}/cart/add", json={"sku": "SKU-BEANS", "qty": 1}, headers=h, timeout=2)
        r = requests.post(f"{BASE}/checkout", json={"card": "111"}, headers=h, timeout=2)
        assert r.status_code == 402, f"expected 402 for bad card, got {r.status_code}"
        return {"rejected": True}

    for name, fn in [
        ("health", health),
        ("signup", signup),
        ("login", login),
        ("add_to_cart", add_cart),
        ("checkout", checkout),
        ("verify_order", verify_order),
        ("verify_email", verify_email),
        ("reject_bad_card", reject_bad_card),
    ]:
        result = step(name, fn)
        steps.append(result)
        if not result["ok"]:
            break

    summary = {
        "passed": sum(1 for s in steps if s["ok"]),
        "failed": sum(1 for s in steps if not s["ok"]),
        "total_ms": sum(s["ms"] for s in steps),
        "test_user": email,
        "order_id": state.get("order_id"),
        "steps": steps,
    }
    print(json.dumps(summary, indent=2))
    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
