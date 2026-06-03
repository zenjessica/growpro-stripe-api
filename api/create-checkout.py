from http.server import BaseHTTPRequestHandler
import json
import os
import stripe

stripe.api_key = os.environ.get("STRIPE_KEY", "")

ALLOWED_ORIGINS = [
    "https://launch.kickstartsocial.co",
    "https://zenjessica.github.io",
    "https://growpro.co",
]


def cors_headers(origin="*"):
    if origin in ALLOWED_ORIGINS:
        allow_origin = origin
    else:
        allow_origin = "*"
    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def clean(value):
    return str(value or "").strip()


def enrich_customer_fields(body):
    metadata = body.get("metadata") or {}
    email = clean(body.get("email") or body.get("customer_email") or metadata.get("email") or metadata.get("customer_email"))
    first = clean(body.get("first_name") or metadata.get("first_name"))
    last = clean(body.get("last_name") or metadata.get("last_name"))
    customer_name = clean(
        body.get("customer_name")
        or body.get("client_name")
        or metadata.get("customer_name")
        or metadata.get("client_name")
        or " ".join([part for part in [first, last] if part])
    )
    phone = clean(body.get("phone") or metadata.get("phone"))
    business_name = clean(body.get("business_name") or metadata.get("business_name"))

    enriched = dict(metadata)
    if email:
        enriched["email"] = email
        enriched["customer_email"] = email
    if customer_name:
        enriched["customer_name"] = customer_name
        enriched["client_name"] = customer_name
    if phone:
        enriched["phone"] = phone
    if business_name:
        enriched["business_name"] = business_name

    return email, customer_name, phone, business_name, enriched


def create_customer(email, customer_name, phone, metadata):
    params = {}
    if email:
        params["email"] = email
    if customer_name:
        params["name"] = customer_name
    if phone:
        params["phone"] = phone
    if metadata:
        params["metadata"] = metadata
    if not params:
        return None
    return stripe.Customer.create(**params).id


def attach_customer(params, email, customer_name, phone, metadata):
    customer_id = create_customer(email, customer_name, phone, metadata)
    if customer_id:
        params["customer"] = customer_id
    elif email:
        params["customer_email"] = email


def transform_line_items(raw_items):
    transformed = []
    for item in raw_items:
        if "price_data" in item or "price" in item:
            transformed.append(item)
            continue
        price_data = {
            "currency": "usd",
            "unit_amount": int(item["amount_cents"]),
            "product_data": {"name": str(item.get("name", ""))},
        }
        if item.get("recurring"):
            price_data["recurring"] = {"interval": "month"}
        transformed.append({"price_data": price_data, "quantity": 1})
    return transformed


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "*")
        self.send_response(204)
        for k, v in cors_headers(origin).items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        origin = self.headers.get("Origin", "*")
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            line_items = body.get("line_items", [])
            email, customer_name, phone, business_name, metadata = enrich_customer_fields(body)
            success_url = body.get("success_url", "https://launch.kickstartsocial.co/?success=true")
            cancel_url = body.get("cancel_url", "https://launch.kickstartsocial.co/")
            mode = body.get("mode", "payment")
            description = body.get("description", "")
            payment_plan = body.get("payment_plan", None)

            if not stripe.api_key:
                raise ValueError("Missing STRIPE_KEY environment variable")

            if not line_items and not payment_plan:
                raise ValueError("Missing line_items")

            if payment_plan:
                amount = int(payment_plan.get("amount_cents", 0))
                name = payment_plan.get("name", "GrowPro Payment Plan")
                interval = payment_plan.get("interval", "month")
                installments = int(payment_plan.get("installments", 1))
                params = {
                    "mode": "subscription",
                    "line_items": [{
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": name},
                            "unit_amount": amount,
                            "recurring": {"interval": interval},
                        },
                        "quantity": 1,
                    }],
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "metadata": {**metadata, "installments": str(installments), "payment_plan": name},
                    "subscription_data": {
                        "metadata": {**metadata, "installments": str(installments), "payment_plan": name}
                    },
                }
                attach_customer(params, email, customer_name, phone, metadata)
                session = stripe.checkout.Session.create(**params)
            else:
                params = {
                    "mode": mode,
                    "line_items": transform_line_items(line_items),
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                }
                attach_customer(params, email, customer_name, phone, metadata)
                if metadata:
                    params["metadata"] = metadata
                if mode == "payment":
                    payment_intent_data = {}
                    if description:
                        payment_intent_data["description"] = description
                    if metadata:
                        payment_intent_data["metadata"] = metadata
                    if email:
                        payment_intent_data["receipt_email"] = email
                    if payment_intent_data:
                        params["payment_intent_data"] = payment_intent_data
                elif mode == "subscription" and metadata:
                    params["subscription_data"] = {"metadata": metadata}
                session = stripe.checkout.Session.create(**params)

            self.send_response(200)
            for k, v in cors_headers(origin).items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"url": session.url}).encode("utf-8"))

        except Exception as e:
            self.send_response(400)
            for k, v in cors_headers(origin).items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
