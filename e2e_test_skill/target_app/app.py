"""Tiny e-commerce target app used as the system-under-test.

Endpoints:
  POST /signup        {email, password}              -> {user_id}
  POST /login         {email, password}              -> {token}
  POST /cart/add      header: token, {sku, qty}      -> {cart_id, total}
  POST /checkout      header: token, {card}          -> {order_id, status}
  GET  /orders/<id>   header: token                  -> {order_id, status, total, email_sent}
  POST /admin/reset                                  -> wipe in-memory state

Deliberately stateful in-memory so the E2E test can poke at it end-to-end:
signup -> login -> add to cart -> checkout -> verify order -> verify email -> cleanup.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from flask import Flask, jsonify, request

app = Flask(__name__)

PRICES = {"SKU-COFFEE": 12.50, "SKU-MUG": 8.00, "SKU-BEANS": 18.75}


@dataclass
class User:
    user_id: str
    email: str
    password: str
    token: str | None = None
    cart: dict[str, int] = field(default_factory=dict)
    orders: list[dict] = field(default_factory=list)


USERS: dict[str, User] = {}
TOKENS: dict[str, str] = {}
EMAIL_OUTBOX: list[dict] = []


def _user_from_token() -> User | None:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = TOKENS.get(token)
    return USERS.get(user_id) if user_id else None


@app.post("/signup")
def signup():
    body = request.get_json() or {}
    email, password = body.get("email"), body.get("password")
    if not email or not password:
        return jsonify(error="email and password required"), 400
    if any(u.email == email for u in USERS.values()):
        return jsonify(error="email taken"), 409
    user_id = f"u_{secrets.token_hex(4)}"
    USERS[user_id] = User(user_id=user_id, email=email, password=password)
    return jsonify(user_id=user_id), 201


@app.post("/login")
def login():
    body = request.get_json() or {}
    user = next((u for u in USERS.values() if u.email == body.get("email")), None)
    if not user or user.password != body.get("password"):
        return jsonify(error="invalid credentials"), 401
    token = secrets.token_hex(16)
    user.token = token
    TOKENS[token] = user.user_id
    return jsonify(token=token)


@app.post("/cart/add")
def cart_add():
    user = _user_from_token()
    if not user:
        return jsonify(error="unauthorized"), 401
    body = request.get_json() or {}
    sku, qty = body.get("sku"), int(body.get("qty", 1))
    if sku not in PRICES:
        return jsonify(error=f"unknown sku {sku}"), 400
    user.cart[sku] = user.cart.get(sku, 0) + qty
    total = round(sum(PRICES[s] * q for s, q in user.cart.items()), 2)
    return jsonify(cart_id=user.user_id, items=user.cart, total=total)


@app.post("/checkout")
def checkout():
    user = _user_from_token()
    if not user:
        return jsonify(error="unauthorized"), 401
    if not user.cart:
        return jsonify(error="cart empty"), 400
    card = (request.get_json() or {}).get("card", "")
    if not card or len(card.replace(" ", "")) != 16:
        return jsonify(error="invalid card"), 402
    total = round(sum(PRICES[s] * q for s, q in user.cart.items()), 2)
    order_id = f"o_{secrets.token_hex(5)}"
    order = {
        "order_id": order_id,
        "status": "confirmed",
        "total": total,
        "items": dict(user.cart),
        "created_at": time.time(),
        "email_sent": True,
    }
    user.orders.append(order)
    EMAIL_OUTBOX.append({"to": user.email, "subject": f"Order {order_id} confirmed", "total": total})
    user.cart.clear()
    return jsonify(order_id=order_id, status="confirmed", total=total)


@app.get("/orders/<order_id>")
def get_order(order_id):
    user = _user_from_token()
    if not user:
        return jsonify(error="unauthorized"), 401
    order = next((o for o in user.orders if o["order_id"] == order_id), None)
    if not order:
        return jsonify(error="not found"), 404
    return jsonify(order)


@app.get("/admin/outbox")
def outbox():
    return jsonify(emails=EMAIL_OUTBOX)


@app.post("/admin/reset")
def reset():
    USERS.clear()
    TOKENS.clear()
    EMAIL_OUTBOX.clear()
    return jsonify(ok=True)


@app.get("/health")
def health():
    return jsonify(status="ok", users=len(USERS), orders=sum(len(u.orders) for u in USERS.values()))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5005, debug=False)
