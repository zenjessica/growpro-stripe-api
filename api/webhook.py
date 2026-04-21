"""
GrowPro Stripe Webhook Handler — Vercel Serverless Function
===========================================================
Receives Stripe events (checkout.session.completed) and:
  1. Creates a ClickUp task in the GrowPro Purchases list
  2. Emails Jessica at hello@kickstartsocial.co (via Resend)
  3. SMS Jessica at +13109038546 (via Twilio)

REQUIRED Vercel environment variables:
  STRIPE_KEY              - Stripe secret key (already set, used by checkout)
  STRIPE_WEBHOOK_SECRET   - Signing secret from Stripe webhook config
  CLICKUP_API_TOKEN       - ClickUp Personal API token (pk_...)
  CLICKUP_LIST_ID         - Numeric ID of target ClickUp list
  RESEND_API_KEY          - Resend API key for email (re_...)
  TWILIO_SID              - Twilio Account SID (AC...)
  TWILIO_TOKEN            - Twilio Auth Token
  TWILIO_FROM             - Twilio sending phone number (E.164, e.g. +18885551234)

OPTIONAL:
  NOTIFY_EMAIL            - Override notification email (default hello@kickstartsocial.co)
  NOTIFY_PHONE            - Override notification SMS (default +13109038546)
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error
import base64

import stripe

stripe.api_key = os.environ.get("STRIPE_KEY", "")

WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
CLICKUP_TOKEN = os.environ.get("CLICKUP_API_TOKEN", "")
CLICKUP_LIST_ID = os.environ.get("CLICKUP_LIST_ID", "")
RESEND_KEY = os.environ.get("RESEND_API_KEY", "")
TWILIO_SID = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM", "")

NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "hello@kickstartsocial.co")
NOTIFY_PHONE = os.environ.get("NOTIFY_PHONE", "+13109038546")


# ---------------------------------------------------------------------------
# Helper: HTTP requests via stdlib (no extra dependencies)
# ---------------------------------------------------------------------------
def http_request(url, method="GET", headers=None, data=None, timeout=15):
    headers = headers or {}
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else str(e)
        return e.code, body
    except Exception as e:
        return 0, str(e)


# ---------------------------------------------------------------------------
# Action: create ClickUp task
# ---------------------------------------------------------------------------
def create_clickup_task(session, metadata):
    if not CLICKUP_TOKEN or not CLICKUP_LIST_ID:
        return None, "ClickUp not configured"

    business_name = metadata.get("business_name", "Unknown Brand")
    customer_name = metadata.get("customer_name", "Unknown")
    phone = metadata.get("phone", "")
    source = metadata.get("source", "")
    payment_plan = metadata.get("payment_plan", "Pay in Full")
    promo_codes = metadata.get("promo_codes", "none")
    build_total = metadata.get("build_total", "")
    email = (session.get("customer_details") or {}).get("email") or session.get("customer_email") or ""

    amount_total = (session.get("amount_total") or 0) / 100.0
    currency = (session.get("currency") or "usd").upper()
    session_id = session.get("id", "")
    description = session.get("metadata", {}).get("description") or "GrowPro Purchase"

    # Determine which configurator (launch / marketing / operator) from description prefix
    funnel = "Launch"
    desc_lower = description.lower()
    if "marketing" in desc_lower:
        funnel = "Marketing"
    elif "operator" in desc_lower or "growth partner" in desc_lower:
        funnel = "Operator"

    task_name = f"[{funnel}] {business_name} — ${amount_total:,.0f} — {customer_name}"

    body_md = f"""## New GrowPro Purchase

**Funnel:** {funnel}
**Business:** {business_name}
**Customer:** {customer_name}
**Email:** {email}
**Phone:** {phone}
**Heard about us via:** {source}

---

### Purchase
- **Description:** {description}
- **Total Build:** ${build_total}
- **Amount Charged:** ${amount_total:,.2f} {currency}
- **Payment Plan:** {payment_plan}
- **Promo Codes:** {promo_codes}
- **Stripe Session:** `{session_id}`
- **Stripe Dashboard:** https://dashboard.stripe.com/payments/{session.get('payment_intent', '')}

---

### Next Steps
1. Send onboarding email + welcome packet
2. Schedule kickoff call
3. Trigger LegitScript application
4. Set up project channel
"""

    payload = {
        "name": task_name,
        "description": body_md,
        "tags": [funnel.lower(), "new-purchase"],
        "priority": 2,  # 1=urgent, 2=high, 3=normal, 4=low
        "status": "to do",
    }

    url = f"https://api.clickup.com/api/v2/list/{CLICKUP_LIST_ID}/task"
    status, body = http_request(
        url,
        method="POST",
        headers={"Authorization": CLICKUP_TOKEN},
        data=payload,
    )
    if status >= 200 and status < 300:
        try:
            task_id = json.loads(body).get("id", "")
            task_url = json.loads(body).get("url", "")
            return task_url or task_id, None
        except Exception:
            return body, None
    return None, f"ClickUp error {status}: {body[:300]}"


# ---------------------------------------------------------------------------
# Action: send email via Resend
# ---------------------------------------------------------------------------
def send_email(session, metadata, clickup_url):
    if not RESEND_KEY:
        return None, "Resend not configured"

    business_name = metadata.get("business_name", "Unknown")
    customer_name = metadata.get("customer_name", "Unknown")
    phone = metadata.get("phone", "")
    source = metadata.get("source", "")
    payment_plan = metadata.get("payment_plan", "Pay in Full")
    build_total = metadata.get("build_total", "")
    email_addr = (session.get("customer_details") or {}).get("email") or ""
    amount = (session.get("amount_total") or 0) / 100.0
    desc = session.get("metadata", {}).get("description") or "GrowPro Purchase"

    subject = f"💰 New GrowPro Purchase: {business_name} — ${amount:,.0f}"
    html = f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:auto;padding:24px;background:#0F1A2E;color:#fff;border-radius:12px">
<h2 style="margin-top:0;color:#A78BFA">💰 New GrowPro Purchase</h2>
<table style="width:100%;border-collapse:collapse;color:#fff">
<tr><td style="padding:8px 0;color:#94A3B8">Business</td><td style="padding:8px 0"><strong>{business_name}</strong></td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Customer</td><td style="padding:8px 0">{customer_name}</td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Email</td><td style="padding:8px 0">{email_addr}</td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Phone</td><td style="padding:8px 0">{phone}</td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Source</td><td style="padding:8px 0">{source}</td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Build</td><td style="padding:8px 0">{desc}</td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Total Build</td><td style="padding:8px 0">${build_total}</td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Amount Charged</td><td style="padding:8px 0"><strong style="color:#10B981">${amount:,.2f}</strong></td></tr>
<tr><td style="padding:8px 0;color:#94A3B8">Payment Plan</td><td style="padding:8px 0">{payment_plan}</td></tr>
</table>
{'<p style="margin-top:24px"><a href="' + clickup_url + '" style="display:inline-block;padding:12px 24px;background:#A78BFA;color:#0F1A2E;text-decoration:none;border-radius:8px;font-weight:600">Open ClickUp Task →</a></p>' if clickup_url else ''}
<p style="margin-top:16px;color:#64748B;font-size:12px">Stripe Session: {session.get('id','')}</p>
</div>"""

    payload = {
        "from": "GrowPro <hello@kickstartsocial.co>",
        "to": [NOTIFY_EMAIL],
        "subject": subject,
        "html": html,
    }
    status, body = http_request(
        "https://api.resend.com/emails",
        method="POST",
        headers={"Authorization": f"Bearer {RESEND_KEY}"},
        data=payload,
    )
    if status >= 200 and status < 300:
        return True, None
    return None, f"Resend error {status}: {body[:300]}"


# ---------------------------------------------------------------------------
# Action: send SMS via Twilio
# ---------------------------------------------------------------------------
def send_sms(session, metadata):
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        return None, "Twilio not configured"

    business_name = metadata.get("business_name", "Unknown")
    amount = (session.get("amount_total") or 0) / 100.0
    payment_plan = metadata.get("payment_plan", "PIF")
    customer_name = metadata.get("customer_name", "")

    msg = (
        f"💰 GrowPro Sale!\n"
        f"{business_name} ({customer_name})\n"
        f"${amount:,.0f} — {payment_plan}\n"
        f"Check email for ClickUp link."
    )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    creds = base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()
    data = urllib.parse.urlencode({
        "From": TWILIO_FROM,
        "To": NOTIFY_PHONE,
        "Body": msg,
    }).encode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, None
    except urllib.error.HTTPError as e:
        return None, f"Twilio error {e.code}: {e.read().decode('utf-8')[:300]}"
    except Exception as e:
        return None, f"Twilio error: {e}"


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Health check / status
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "service": "growpro-webhook",
            "configured": {
                "stripe_signing": bool(WEBHOOK_SECRET),
                "clickup": bool(CLICKUP_TOKEN and CLICKUP_LIST_ID),
                "email": bool(RESEND_KEY),
                "sms": bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM),
            },
        }).encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = self.rfile.read(length) if length else b""
            sig_header = self.headers.get("Stripe-Signature", "")

            # Verify signature
            try:
                if WEBHOOK_SECRET:
                    event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
                else:
                    # Allow unsigned in dev only
                    event = json.loads(payload)
            except (ValueError, stripe.error.SignatureVerificationError) as e:
                self._respond(400, {"error": f"Invalid signature: {e}"})
                return

            event_type = event.get("type") if isinstance(event, dict) else event["type"]

            # Only act on completed checkout sessions
            if event_type != "checkout.session.completed":
                self._respond(200, {"ignored": event_type})
                return

            session = (event.get("data") or {}).get("object") if isinstance(event, dict) else event["data"]["object"]
            metadata = session.get("metadata") or {}

            # Run actions (fail-soft: each action's failure doesn't kill the others)
            clickup_url, clickup_err = create_clickup_task(session, metadata)
            email_ok, email_err = send_email(session, metadata, clickup_url or "")
            sms_ok, sms_err = send_sms(session, metadata)

            self._respond(200, {
                "ok": True,
                "clickup": {"url": clickup_url, "error": clickup_err},
                "email": {"sent": bool(email_ok), "error": email_err},
                "sms": {"sent": bool(sms_ok), "error": sms_err},
            })

        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
