from http.server import BaseHTTPRequestHandler
import json
import os
import stripe
import urllib.request
import urllib.error

stripe.api_key = os.environ.get("STRIPE_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_LUMI_WEBHOOK_SECRET", "")

LUMI_SUCCESS_URL = "https://services.leadconnectorhq.com/hooks/[PLACEHOLDER_LUMI_WEBHOOK_SUCCESS]"
LUMI_FAILURE_URL = "https://services.leadconnectorhq.com/hooks/[PLACEHOLDER_LUMI_WEBHOOK_FAILURE]"


def post_to_lumi(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else str(e)
        return e.code, body
    except Exception as e:
        return 0, str(e)


def extract_contact(pi):
    meta = pi.get("metadata") or {}
    email = (
        meta.get("email")
        or meta.get("customer_email")
        or pi.get("receipt_email")
        or ""
    )
    first_name = meta.get("first_name") or ""
    last_name = meta.get("last_name") or ""
    if not first_name and not last_name:
        full = meta.get("customer_name") or meta.get("client_name") or ""
        parts = full.strip().split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
    return {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "phone": meta.get("phone") or "",
        "business_name": meta.get("business_name") or "",
        "amount_dollars": (pi.get("amount") or 0) / 100.0,
        "currency": pi.get("currency") or "usd",
        "payment_intent_id": pi.get("id") or "",
        "description": meta.get("description") or "",
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            sig = self.headers.get("Stripe-Signature", "")

            try:
                if WEBHOOK_SECRET:
                    event = stripe.Webhook.construct_event(raw, sig, WEBHOOK_SECRET)
                else:
                    event = json.loads(raw)
            except (ValueError, stripe.error.SignatureVerificationError) as e:
                self._respond(400, {"error": f"Invalid signature: {e}"})
                return

            event_type = event["type"] if isinstance(event, dict) else event.type
            pi = event["data"]["object"] if isinstance(event, dict) else event.data.object

            if event_type == "payment_intent.succeeded":
                contact = extract_contact(pi)
                lumi_status, _ = post_to_lumi(LUMI_SUCCESS_URL, contact)
                self._respond(200, {"received": event_type, "lumi_status": lumi_status})

            elif event_type == "payment_intent.payment_failed":
                contact = extract_contact(pi)
                last_error = pi.get("last_payment_error") or {}
                contact["failure_code"] = last_error.get("code") or ""
                contact["failure_message"] = last_error.get("message") or ""
                lumi_status, _ = post_to_lumi(LUMI_FAILURE_URL, contact)
                self._respond(200, {"received": event_type, "lumi_status": lumi_status})

            else:
                self._respond(200, {"ignored": event_type})

        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
