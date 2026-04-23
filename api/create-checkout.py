"""
GrowPro Stripe Checkout API — Vercel Serverless Function
Creates dynamic Stripe Checkout sessions with the exact configurator total.
Supports: pay-in-full, payment plans (down payment + installments).
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import stripe

stripe.api_key = os.environ.get("STRIPE_KEY", "")

ALLOWED_ORIGINS = [
    "https://grow-pro-configurator-a9d468.webflow.io",
    "https://launch.kickstartsocial.co",
    "https://www.growpro.co",
    "https://growpro.co",
    "http://localhost:8080",
]


def cors_headers(origin="*"):
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
            mode = body.get("mode", "payment")
            metadata = body.get("metadata", {})
            description = body.get("description", "")
            payment_plan = body.get("payment_plan", None)

            # --- PAYMENT PLAN MODE ---
            if payment_plan and isinstance(payment_plan, dict):
                down_cents = int(payment_plan["down_payment_cents"])
                inst_cents = int(payment_plan["installment_cents"])
                inst_count = int(payment_plan.get("installment_count", 2))
                interval_days = int(payment_plan.get("interval_days", 28))
                plan_label = payment_plan.get("plan_label", "Payment Plan")

                stripe_items = []

                # One-time down payment line item
                stripe_items.append({
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": f"Down Payment \u2014 {plan_label}"},
                        "unit_amount": down_cents,
                    },
                    "quantity": 1,
                })

                # Recurring installment line item with trial to delay first charge
                stripe_items.append({
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": f"Installment \u2014 {plan_label} ({inst_count} payments)"},
                        "unit_amount": inst_cents,
                        "recurring": {"interval": "day", "interval_count": interval_days},
                    },
                    "quantity": 1,
                })

                params = {
                    "payment_method_types": ["card"],
                    "line_items": stripe_items,
                    "mode": "subscription",
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "allow_promotion_codes": True,
                    "subscription_data": {
                        "trial_period_days": interval_days,
                        "metadata": metadata,
                    },
                }
                if email:
                    params["customer_email"] = email
                if metadata:
                    params["metadata"] = metadata

                session = stripe.checkout.Session.create(**params)
                self._respond(200, {"url": session.url, "id": session.id}, origin)
                return

            if not line_items:
                self._respond(400, {"error": "No line items provided"}, origin)
                return

            # --- STANDARD MODE (pay-in-full or subscription) ---
            stripe_items = []
            for item in line_items:
                if "amount_cents" in item:
                    unit_amount = int(item["amount_cents"])
                else:
                    unit_amount = int(float(item["amount"]) * 100)
                price_data = {
                    "currency": "usd",
                    "product_data": {"name": item["name"]},
                    "unit_amount": unit_amount,
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
                "allow_promotion_codes": True,
            }
            if email:
                params["customer_email"] = email
            if metadata:
                params["metadata"] = metadata
            if description:
                params["payment_intent_data"] = {"description": description} if mode == "payment" else {}

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
