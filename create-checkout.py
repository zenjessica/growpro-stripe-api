"""
GrowPro Stripe Checkout API — Vercel Serverless Function
Creates dynamic Stripe Checkout sessions with the exact configurator total.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import stripe

stripe.api_key = os.environ.get("STRIPE_KEY", "")

ALLOWED_ORIGINS = [
    "https://grow-pro-configurator-a9d468.webflow.io",
    "https://www.growpro.co",
    "https://growpro.co",
    "http://localhost:8080",
]


def cors_headers(origin="*"):
    """Return CORS headers allowing the request origin if whitelisted."""
    allowed = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
    return {
        "Access-Control-Allow-Origin": allowed,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "*")
        self.send_response(200)
        for k, v in cors_headers(origin).items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        origin = self.headers.get("Origin", "*")
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            line_items = body.get("line_items", [])
            email = body.get("email", "")
            success_url = body.get("success_url", "https://growpro.co")
            cancel_url = body.get("cancel_url", "https://growpro.co")
            mode = body.get("mode", "payment")  # "payment" or "subscription"

            if not line_items:
                self._respond(400, {"error": "No line items provided"}, origin)
                return

            stripe_items = []
            for item in line_items:
                price_data = {
                    "currency": "usd",
                    "product_data": {"name": item["name"]},
                    "unit_amount": int(float(item["amount"]) * 100),
                }
                if mode == "subscription":
                    if item.get("recurring", False):
                        price_data["recurring"] = {"interval": "month"}
                stripe_items.append({"price_data": price_data, "quantity": 1})

            params = {
                "payment_method_types": ["card"],
                "line_items": stripe_items,
                "mode": mode,
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
            if email:
                params["customer_email"] = email

            session = stripe.checkout.Session.create(**params)
            self._respond(200, {"url": session.url, "id": session.id}, origin)

        except stripe.error.StripeError as e:
            self._respond(500, {"error": str(e)}, origin)
        except Exception as e:
            self._respond(500, {"error": str(e)}, origin)

    def _respond(self, status, data, origin="*"):
        self.send_response(status)
        for k, v in cors_headers(origin).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
