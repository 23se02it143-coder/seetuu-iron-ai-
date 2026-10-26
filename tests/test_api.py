import hashlib
import hmac
import json
import re
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import EmailOutbox

from .conftest import PASSWORD


def mail(to: str) -> str:
    with SessionLocal() as db:
        rows = db.scalars(select(EmailOutbox).where(EmailOutbox.to_address == to).order_by(EmailOutbox.id)).all()
        return "\n".join(r.body_text for r in rows)


def email() -> str:
    return f"t-{uuid.uuid4().hex[:8]}@example.com"


def hmac_hex(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ----------------------------------------------------------------- public
def test_public_catalogue(client):
    assert client.get("/api/health").json()["status"] == "ok"
    plans = client.get("/api/plans").json()["plans"]
    assert [p["slug"] for p in plans] == ["starter", "pro", "elite"]
    assert len(client.get("/api/programs").json()["programs"]) == 4
    assert client.get("/api/programs/nope").status_code == 404
    assert len(client.get("/api/faqs").json()["faqs"]) >= 5


def test_events_are_anonymous(client):
    r = client.post("/api/events", json={"name": "page_view", "path": "/?x=1", "referrer": "https://example.org/a/b?c=d"})
    assert r.status_code == 204
    assert client.post("/api/events", json={"name": "bogus"}).status_code == 422


def test_pages_render(client):
    for path in ("/", "/account", "/admin", "/terms", "/privacy", "/checkout/abc", "/robots.txt", "/sitemap.xml"):
        assert client.get(path).status_code == 200, path
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "text/html" in r.headers["content-type"]
    assert client.get("/api/no-such").json()["error"]["code"] == "not_found"
    home = client.get("/")
    assert "unsafe-inline" not in home.headers["content-security-policy"]
    assert "FAQPage" in home.text


# --------------------------------------------------------------- waitlist
def test_waitlist_join_referral_and_honeypot(client):
    a = client.post("/api/waitlist", json={"email": email()}).json()
    assert a["status"] == "joined" and a["position"] >= 1 and a["referral_code"]
    b = client.post("/api/waitlist", json={"email": email(), "ref": a["referral_code"]}).json()
    status = client.get(f"/api/waitlist/status/{a['referral_code']}").json()
    assert status["referrals"] == 1 and b["position"] > 0
    dup_email = email()
    client.post("/api/waitlist", json={"email": dup_email})
    assert client.post("/api/waitlist", json={"email": dup_email}).json()["status"] == "exists"
    assert client.post("/api/waitlist", json={"email": email(), "website": "spam"}).json()["position"] is None
    r = client.post("/api/waitlist", json={"email": "not-an-email"})
    assert r.status_code == 422 and "email" in r.json()["error"]["fields"]


def test_waitlist_unsubscribe(client):
    e = email()
    client.post("/api/waitlist", json={"email": e})
    token = re.search(r"unsubscribe\?token=([\w-]+)", mail(e)).group(1)
    r = client.get(f"/api/waitlist/unsubscribe?token={token}", follow_redirects=False)
    assert r.status_code == 303 and "unsubscribed" in r.headers["location"]


# ---------------------------------------------------------------- contact
def test_contact(client):
    r = client.post("/api/contact", json={"name": "Ann", "email": email(), "message": "Hello, I run a gym and want a quote."})
    assert r.status_code == 201
    assert client.post("/api/contact", json={"name": "Ann", "email": email(), "message": "short"}).status_code == 422


# ------------------------------------------------------------- assessment
BASE = {"goal": "strength", "experience": "intermediate", "days_per_week": 4, "sleep": "7_8"}


def test_assessment_scoring_and_privacy(client):
    ok = client.post("/api/assessments", json=BASE).json()
    assert ok["saved"] is False and ok["result"]["status"] == "ok" and ok["result"]["program"]["slug"] == "ai-training"
    hurt = client.post("/api/assessments", json={**BASE, "pain_areas": ["knee", "hip"], "recent_injury": True, "sleep": "under_5"}).json()
    assert hurt["result"]["program_slug"] == "return-to-training" and hurt["result"]["readiness"]["score"] < ok["result"]["readiness"]["score"]
    flag = client.post("/api/assessments", json={**BASE, "red_flags": True}).json()["result"]
    assert flag["status"] == "medical_review" and flag["program_slug"] is None


def test_assessment_save_requires_consent(client):
    r = client.post("/api/assessments", json={**BASE, "save": True, "email": email()})
    assert r.status_code == 422 and "consent" in r.json()["error"]["fields"]
    e = email()
    r = client.post("/api/assessments", json={**BASE, "save": True, "email": e, "consent": True}).json()
    assert r["saved"] is True and "readiness" in mail(e).lower()


# -------------------------------------------------------------- assistant
def ask(client, text):
    return client.post("/api/assistant/message", json={"messages": [{"role": "user", "content": text}]}).json()


def test_assistant_safety_layer_wins(client):
    assert ask(client, "I get chest pain when I squat")["flagged"] == "red_flag"
    crisis = ask(client, "I want to die")
    assert crisis["flagged"] == "crisis" and crisis["source"] == "rules"
    normal = ask(client, "how do I warm up before squats")
    assert normal["flagged"] is None and normal["reply"]
    assert "499" in ask(client, "what does pro cost")["reply"]
    bad = client.post("/api/assistant/message", json={"messages": [{"role": "assistant", "content": "hi"}]})
    assert bad.status_code == 422


# ------------------------------------------------------------------- auth
def test_register_login_logout(client, user):
    assert client.get("/api/auth/session").json()["user"]["email"] == user["email"]
    client.post("/api/auth/logout")
    assert client.get("/api/auth/session").json()["user"] is None
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "wrong-password-1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]}).status_code == 200


def test_weak_passwords_rejected(client):
    for pw in ("short", "password1234", "aaaaaaaaaaaa"):
        r = client.post("/api/auth/register", json={"name": "X", "email": email(), "password": pw})
        assert r.status_code == 422, pw


def test_duplicate_email_is_rejected(client, user):
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={"name": "Dup", "email": user["email"], "password": PASSWORD})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"  # documented trade-off: sign-up must explain why


def test_password_change_revokes_other_sessions(client, user):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="http://testserver") as other:
        other.post("/api/auth/login", json=user)
        assert other.get("/api/auth/me").status_code == 200
        r = client.post("/api/auth/password", json={"current_password": user["password"], "new_password": "Another-Strong-Pass-77"})
        assert r.status_code == 200
        assert other.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me").status_code == 200


def test_forgot_and_reset(client, user):
    client.post("/api/auth/logout")
    generic = client.post("/api/auth/forgot", json={"email": user["email"]}).json()
    unknown = client.post("/api/auth/forgot", json={"email": email()}).json()
    assert generic["message"] == unknown["message"]
    token = re.search(r"reset=([\w-]+)", mail(user["email"])).group(1)
    assert client.post("/api/auth/reset", json={"token": token, "password": "Brand-New-Passphrase-5"}).status_code == 200
    reuse = client.post("/api/auth/reset", json={"token": token, "password": "Brand-New-Passphrase-6"})
    assert reuse.status_code == 400 and reuse.json()["error"]["code"] == "invalid_token"
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "Brand-New-Passphrase-5"}).status_code == 200


def test_export_and_delete(client, user):
    data = client.get("/api/auth/export").json()
    assert data["account"]["email"] == user["email"]
    assert set(data) >= {"account", "subscriptions", "invoices", "assessments", "waitlist"}
    wrong = client.request("DELETE", "/api/auth/me", json={"password": "wrong-password-1"})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "wrong_password"
    assert client.request("DELETE", "/api/auth/me", json={"password": user["password"]}).status_code == 200
    assert client.post("/api/auth/login", json=user).status_code == 401


# ---------------------------------------------------------------- billing
def test_mock_checkout_cancel_resume(client, user):
    assert client.get("/api/billing/subscription").json()["subscription"]["is_paid"] is False
    co = client.post("/api/billing/checkout", json={"plan_slug": "pro", "interval": "year"}).json()
    assert co["url"].endswith(co["checkout_id"])
    details = client.get(f"/api/billing/mock/{co['checkout_id']}").json()
    assert details["amount_cents"] == 499000 and details["status"] == "open"
    assert client.post(f"/api/billing/mock/{co['checkout_id']}/complete", json={"outcome": "success"}).json()["status"] == "complete"
    sub = client.get("/api/billing/subscription").json()
    assert sub["subscription"]["plan"]["slug"] == "pro" and len(sub["invoices"]) == 1
    assert client.post("/api/billing/cancel").json()["subscription"]["cancel_at_period_end"] is True
    assert client.post("/api/billing/resume").json()["subscription"]["cancel_at_period_end"] is False
    assert "Pro" in mail(user["email"])


def test_checkout_is_private(client, user):
    co = client.post("/api/billing/checkout", json={"plan_slug": "pro", "interval": "month"}).json()
    client.post("/api/auth/logout")
    assert client.post("/api/billing/checkout", json={"plan_slug": "pro"}).status_code == 401
    other = email()
    client.post("/api/auth/register", json={"name": "Other", "email": other, "password": PASSWORD})
    assert client.get(f"/api/billing/mock/{co['checkout_id']}").status_code == 404
    assert client.post("/api/billing/webhook/stripe", content=b"{}").status_code == 404


# ------------------------------------------------------------------ admin
def test_admin_requires_admin(client, user):
    assert client.get("/api/admin/overview").status_code == 403
    client.post("/api/auth/logout")
    assert client.get("/api/admin/overview").status_code == 401


def test_admin_overview_and_content(admin):
    d = admin.get("/api/admin/overview").json()
    assert d["waitlist"]["total"] >= 0 and len(d["signups_per_day"]) == 14
    csv = admin.get("/api/admin/waitlist.csv")
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    t = admin.post("/api/admin/testimonials", json={"name": "Real Person", "role": "Lifter", "quote": "Genuinely helpful programming."}).json()
    assert admin.put(f"/api/admin/testimonials/{t['id']}", json={"name": "Real Person", "quote": "Genuinely helpful programming!", "published": False}).status_code == 200
    assert admin.delete(f"/api/admin/testimonials/{t['id']}").status_code == 204
    assert admin.get("/api/admin/emails").status_code == 200


def test_csv_formula_injection_is_neutralised(admin, client):
    admin.post("/api/waitlist", json={"email": email(), "name": "=HYPERLINK(\"http://evil\")"})
    body = admin.get("/api/admin/waitlist.csv").text
    assert ",=HYPERLINK" not in body and "'=HYPERLINK" in body


# --------------------------------------------------------------- security
def test_cross_origin_writes_blocked(client):
    r = client.post("/api/waitlist", json={"email": email()}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/waitlist", json={"email": email()}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200


# ------------------------------------------------- assistant conversation
def chat(client, *texts):
    msgs = []
    for i, t in enumerate(texts):
        msgs.append({"role": "user", "content": t})
        if i < len(texts) - 1:
            msgs.append({"role": "assistant", "content": "ok"})
    return client.post("/api/assistant/message", json={"messages": msgs}).json()["reply"]


def test_assistant_small_talk_is_not_a_follow_up(client):
    assert chat(client, "Good morning").startswith("Good morning!")
    assert chat(client, "good moring").startswith("Good morning!")
    # the reported bug: a greeting right after a warm-up question must not repeat the warm-up answer
    assert chat(client, "How should I warm up for squats?", "Good morning").startswith("Good morning!")
    assert "squat" in chat(client, "hi, how do I squat properly?").lower()
    assert chat(client, "thanks!").startswith("You're welcome")
    assert chat(client, "bye").startswith("Take care")


def test_assistant_topics_and_scope(client):
    assert "readiness assessment" in chat(client, "I'm new to the gym")
    assert "dietitian" in chat(client, "how much protein should I eat")
    assert "doctor" in chat(client, "I have diabetes, can I lift?")
    assert "outside what I can help" in chat(client, "tell me a joke")
    assert "four programs" in chat(client, "what programs do you have")
    assert "Account page" in chat(client, "how do I cancel")
    assert "hinges" in chat(client, "my knees cave when I squat", "and for deadlifts?")


# ------------------------------------------------------------ rupees + diet
def test_plans_are_in_rupees(client):
    d = client.get("/api/plans").json()
    assert d["currency"] == "INR"
    prices = {p["slug"]: (p["price_monthly_cents"], p["price_annual_cents"]) for p in d["plans"]}
    assert prices == {"starter": (0, 0), "pro": (49900, 499000), "elite": (129900, 1299000)}


DIET = {"sex": "male", "age": 24, "height_cm": 175, "weight_kg": 70, "activity": "moderate", "goal": "bulk", "preference": "veg", "meals": 5}


def test_diet_targets_follow_the_goal(client):
    bulk = client.post("/api/diet/plan", json=DIET).json()
    cut = client.post("/api/diet/plan", json={**DIET, "goal": "cut"}).json()
    keep = client.post("/api/diet/plan", json={**DIET, "goal": "maintain"}).json()
    assert cut["targets"]["calories"] < keep["targets"]["calories"] < bulk["targets"]["calories"]
    assert cut["targets"]["protein_g"] > bulk["targets"]["protein_g"] - 1  # cut keeps protein high
    assert bulk["targets"]["weekly_change_kg"] > 0 > cut["targets"]["weekly_change_kg"]


def test_diet_meals_match_targets_for_every_preference(client):
    for pref in ("veg", "egg", "nonveg"):
        for goal in ("bulk", "cut", "recomp", "maintain"):
            for meals in (3, 4, 5, 6):
                plan = client.post("/api/diet/plan", json={**DIET, "preference": pref, "goal": goal, "meals": meals}).json()
                t, tot = plan["targets"], plan["totals"]
                assert len(plan["meals"]) == meals
                assert abs(tot["kcal"] - t["calories"]) <= t["calories"] * 0.08, (pref, goal, meals, tot, t)
                assert tot["p"] >= t["protein_g"] * 0.85, (pref, goal, meals, tot, t)
                foods = {i["food"] for m in plan["meals"] for i in m["items"]}
                if pref == "veg":
                    assert not foods & {"egg", "eggwhite", "chicken", "fish"}
                if pref == "egg":
                    assert not foods & {"chicken", "fish"}


def test_diet_swap_changes_a_meal(client):
    a = client.post("/api/diet/plan", json=DIET).json()
    b = client.post("/api/diet/plan", json={**DIET, "variants": {"lunch": 1}}).json()
    la = next(m for m in a["meals"] if m["slot"] == "lunch")
    lb = next(m for m in b["meals"] if m["slot"] == "lunch")
    assert la["variant"] == 0 and lb["variant"] == 1 and la["items"] != lb["items"]


def test_diet_safety_rules(client):
    assert client.post("/api/diet/plan", json={**DIET, "age": 16}).status_code == 422
    thin = client.post("/api/diet/plan", json={**DIET, "goal": "cut", "weight_kg": 45, "height_cm": 178})
    assert thin.status_code == 422 and thin.json()["error"]["code"] == "unsafe_goal"
    fast = client.post("/api/diet/plan", json={**DIET, "goal": "cut", "pace": "fast", "sex": "female", "weight_kg": 55, "height_cm": 160}).json()
    assert fast["targets"]["calories"] >= 1200 and "disclaimer" in fast


def test_diet_email_and_chat_intent(client):
    e = email()
    assert client.post("/api/diet/email", json={**DIET, "email": e, "name": "Ravi"}).json()["sent"] is True
    assert "protein" in mail(e).lower() and "kcal" in mail(e)
    r = client.post("/api/assistant/message", json={"messages": [{"role": "user", "content": "I weigh 72 kg and want to bulk"}]}).json()
    assert "72" in r["reply"] and r["action"]["target"] == "#diet" and r["chips"]


# ------------------------------------------------- training + sessions
def test_program_schedules_link_to_the_form_coach(client):
    for slug in ("strength-foundations", "ai-training", "smart-recovery", "return-to-training"):
        d = client.get(f"/api/programs/{slug}/schedule").json()
        assert d["days"] and all(day["exercises"] for day in d["days"])
        assert any(e["coach"] for day in d["days"] for e in day["exercises"])
    assert client.get("/api/programs/nope/schedule").status_code == 404


def test_form_sessions_saved_and_exported(client, user):
    body = {"exercise": "squat", "reps": 8, "avg_score": 86, "best_score": 97, "duration_s": 190, "faults": {"heels": 2}}
    assert client.post("/api/sessions", json=body).status_code == 201
    got = client.get("/api/sessions").json()
    assert got["summary"] == {"sessions": 1, "reps": 8, "avg_score": 86} and got["sessions"][0]["faults"] == {"heels": 2}
    assert client.get("/api/auth/export").json()["workout_sessions"][0]["reps"] == 8
    assert client.post("/api/sessions", json={**body, "exercise": "curl"}).status_code == 422
    client.post("/api/auth/logout")
    assert client.post("/api/sessions", json=body).status_code == 401


# --------------------------------------------------------- v3 additions
def test_config_reports_coach_open_access_outside_production(client):
    assert client.get("/api/config").json()["coach_open_access"] is True  # test environment is not production


def test_mock_checkout_url_is_relative_so_the_session_cookie_survives(client, user):
    r = client.post("/api/billing/checkout", json={"plan_slug": "pro", "interval": "month"}).json()
    assert r["url"].startswith("/checkout/")


def test_old_faq_text_is_refreshed_and_new_questions_added(client):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Faq
    from app.seed import OLD_FAQ_ANSWERS, seed_reference_data
    from app.config import get_settings

    with SessionLocal() as db:
        row = db.scalars(select(Faq).where(Faq.question == "What is IRON-AI?")).one()
        row.answer = OLD_FAQ_ANSWERS["What is IRON-AI?"]
        for extra in db.scalars(select(Faq).where(Faq.question == "Does my camera video get uploaded?")):
            db.delete(extra)
        db.commit()
        seed_reference_data(db, get_settings())
        assert "camera form coach" in db.scalars(select(Faq).where(Faq.question == "What is IRON-AI?")).one().answer
        assert db.scalars(select(Faq).where(Faq.question == "Does my camera video get uploaded?")).first() is not None


# ------------------------------------------------------------------ razorpay
def test_razorpay_signature_verification():
    from app.services.payments import verify_razorpay_signature

    body = b'{"event":"payment_link.paid"}'
    good = hmac_hex(body, "whsec_test")
    assert verify_razorpay_signature(body, good, "whsec_test") is True
    assert verify_razorpay_signature(body, good, "wrong_secret") is False
    assert verify_razorpay_signature(body, "not-hex-at-all", "whsec_test") is False
    assert verify_razorpay_signature(body, None, "whsec_test") is False
    assert verify_razorpay_signature(body, good, "") is False


def test_razorpay_checkout_requires_keys(client, user, override_settings):
    override_settings(payments_provider="razorpay", razorpay_key_id="", razorpay_key_secret="")
    r = client.post("/api/billing/checkout", json={"plan_slug": "pro", "interval": "month"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "payments_not_configured"


def test_razorpay_provider_creates_a_payment_link(monkeypatch):
    import httpx

    from app.config import Settings
    from app.services.payments import RazorpayProvider

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["url"] = request.method, str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "plink_fake123", "short_url": "https://rzp.io/l/fake123"})

    settings = Settings(
        environment="test", secret_key="t" * 48, base_url="http://testserver", currency="INR",
        razorpay_key_id="rzp_test_fake", razorpay_key_secret="fakesecret",
    )
    provider = RazorpayProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))

    class P:
        id, slug, name = 1, "pro", "Pro"

    class U:
        id, name, email = 7, "Test User", "t@example.com"

    class C:
        id, amount_cents, currency, interval = "cs_fake1", 49900, "INR", "month"

    result = provider.create_checkout(checkout=C(), user=U(), plan=P())
    assert result.url == "https://rzp.io/l/fake123" and result.provider_session_id == "plink_fake123"
    assert seen["method"] == "POST" and seen["url"] == "https://api.razorpay.com/v1/payment_links"
    assert seen["body"]["amount"] == 49900 and seen["body"]["currency"] == "INR"
    assert seen["body"]["notes"] == {"checkout_id": "cs_fake1", "user_id": "7", "plan_slug": "pro", "interval": "month"}
    assert seen["body"]["callback_url"] == "http://testserver/account?checkout=success"


def _razorpay_event(checkout_id: str, *, amount: int, currency: str, payment_id: str = "pay_fake1", kind: str = "payment_link.paid"):
    return {
        "event": kind,
        "payload": {
            "payment_link": {"entity": {"id": "plink_fake1", "notes": {"checkout_id": checkout_id}}},
            "payment": {"entity": {"id": payment_id, "amount": amount, "currency": currency, "status": "captured"}},
        },
    }


def test_razorpay_webhook_end_to_end(client, user, override_settings):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Plan, User as UserModel
    from app.services import billing as billing_service

    settings = override_settings(payments_provider="razorpay", razorpay_key_id="rzp_test_fake", razorpay_key_secret="fakesecret", razorpay_webhook_secret="whsec_fake")

    # bypass RazorpayProvider.create_checkout here (a real HTTP call to Razorpay, which this sandbox
    # cannot reach) - test_razorpay_provider_creates_a_payment_link above already covers that call in
    # isolation with a mocked transport. This test is about what happens once the customer has paid.
    with SessionLocal() as db:
        u = db.scalars(select(UserModel).where(UserModel.email == user["email"])).one()
        plan = db.scalars(select(Plan).where(Plan.slug == "pro")).one()
        checkout = billing_service.open_checkout(db, settings, u, plan, "month", "razorpay")
        checkout_id, amount = checkout.id, checkout.amount_cents
        db.commit()

    body = json.dumps(_razorpay_event(checkout_id, amount=amount, currency="INR", payment_id=f"pay_{uuid.uuid4().hex[:10]}")).encode()
    bad = client.post("/api/billing/webhook/razorpay", content=body, headers={"x-razorpay-signature": "wrong"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_signature"

    sig = hmac_hex(body, "whsec_fake")
    ok = client.post("/api/billing/webhook/razorpay", content=body, headers={"x-razorpay-signature": sig})
    assert ok.status_code == 200 and ok.json()["outcome"] == "activated"

    sub = client.get("/api/billing/subscription").json()
    assert sub["subscription"]["plan"]["slug"] == "pro" and sub["subscription"]["is_paid"] is True
    invoices = sub["invoices"]
    assert len(invoices) == 1 and invoices[0]["amount_cents"] == 49900
    assert "499" in mail(user["email"])  # customer receipt
    assert "just paid for Pro" in mail("divyasolanki10125@gmail.com")  # owner notification, default inbox

    # replaying the same event must not double-charge or double-notify
    again = client.post("/api/billing/webhook/razorpay", content=body, headers={"x-razorpay-signature": sig})
    assert again.json()["outcome"] == "duplicate"
    assert len(client.get("/api/billing/subscription").json()["invoices"]) == 1

    client.post("/api/auth/logout")
    assert client.post("/api/billing/webhook/razorpay", content=body, headers={"x-razorpay-signature": sig}).status_code == 200  # no auth needed


def test_razorpay_webhook_disabled_without_secret(client):
    assert client.post("/api/billing/webhook/razorpay", content=b"{}").status_code == 404


def test_razorpay_subscription_goes_past_due_instead_of_free_rolling(client, user, override_settings):
    """Unlike the mock provider (test mode: renewal is free), a lapsed Razorpay period is a real
    unpaid bill: the app must not pretend it renewed on its own."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.database import SessionLocal, utcnow
    from app.models import Plan, Subscription, User as UserModel
    from app.services import billing as billing_service

    settings = override_settings(payments_provider="razorpay", razorpay_key_id="rzp_test_fake", razorpay_key_secret="fakesecret", razorpay_webhook_secret="whsec_fake")

    with SessionLocal() as db:
        u = db.scalars(select(UserModel).where(UserModel.email == user["email"])).one()
        plan = db.scalars(select(Plan).where(Plan.slug == "pro")).one()
        checkout = billing_service.open_checkout(db, settings, u, plan, "month", "razorpay")
        checkout_id, amount = checkout.id, checkout.amount_cents
        db.commit()

    body = json.dumps(_razorpay_event(checkout_id, amount=amount, currency="INR", payment_id=f"pay_{uuid.uuid4().hex[:10]}")).encode()
    sig = hmac_hex(body, "whsec_fake")
    client.post("/api/billing/webhook/razorpay", content=body, headers={"x-razorpay-signature": sig})

    with SessionLocal() as db:
        sub = db.scalars(select(Subscription).where(Subscription.user_id == u.id).where(Subscription.provider == "razorpay").order_by(Subscription.id.desc())).first()
        sub.current_period_end = utcnow() - timedelta(days=1)
        db.commit()

    sub = client.get("/api/billing/subscription").json()["subscription"]
    assert sub["status"] == "past_due" and sub["plan"]["slug"] == "pro"  # still shown as Pro, just flagged to renew


# ------------------------------------------------------------ exercise library
def test_exercise_library_covers_every_coached_lift(client):
    d = client.get("/api/exercise-library").json()
    groups = {g["group"]: g for g in d["groups"]}
    assert set(groups) == {"Shoulders", "Chest", "Back", "Biceps", "Triceps", "Legs", "Abs"}
    coached = {e["coach"] for g in d["groups"] for e in g["exercises"] if e["coach"]}
    assert coached == {"squat", "deadlift", "pushup", "pullup"}
    for g in d["groups"]:
        assert len(g["exercises"]) >= 3
        for e in g["exercises"]:
            assert e["name"] and e["sets"] and e["cue"]


# ---------------------------------------------------------- require-login gate
def test_require_login_gates_the_homepage_for_anonymous_visitors(client, override_settings):
    override_settings(require_login=True)
    anon = client.get("/", follow_redirects=False)
    assert anon.status_code == 302 and anon.headers["location"] == "/welcome?next=/"
    assert client.get("/welcome").status_code == 200  # the gate page itself is always reachable
    assert client.get("/terms").status_code == 200  # legal pages stay public even when gated
    assert client.get("/api/plans").status_code == 200  # the API (and so the auth forms) still work

    client.post("/api/auth/register", json={"name": "Gate Test", "email": email(), "password": "Str0ng-Test-Pass-93!"})
    signed_in = client.get("/", follow_redirects=False)
    assert signed_in.status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/", follow_redirects=False).status_code == 302


def test_require_login_off_by_default(client):
    assert client.get("/", follow_redirects=False).status_code == 200


# ------------------------------------------------------------------ UPI QR checkout
def _upi_checkout(client, user, override_settings):
    override_settings(payments_provider="upi", upi_id="owner@okhdfcbank", upi_name="Owner")
    client.post("/api/auth/login", json=user)
    r = client.post("/api/billing/checkout", json={"plan_slug": "pro", "interval": "month"})
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("/checkout/cs_")
    return r.json()["checkout_id"]


def test_upi_checkout_flow_requires_owner_approval(client, user, override_settings):
    from app.config import get_settings
    from app.services.billing import upi_review_token

    cid = _upi_checkout(client, user, override_settings)
    details = client.get(f"/api/billing/upi/{cid}").json()
    assert details["status"] == "open" and details["upi_id"] == "owner@okhdfcbank"
    assert details["upi_uri"].startswith("upi://pay?pa=owner@okhdfcbank") and "cu=INR" in details["upi_uri"]
    qr = client.get(f"/api/billing/upi/{cid}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg")

    assert client.post(f"/api/billing/upi/{cid}/submit", json={"reference": "abc"}).status_code == 422  # too short
    r = client.post(f"/api/billing/upi/{cid}/submit", json={"reference": "412345678901"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    # submitting a reference alone must NOT grant the plan
    assert client.get("/api/billing/subscription").json()["subscription"]["is_paid"] is False
    assert client.post(f"/api/billing/upi/{cid}/submit", json={"reference": "412345678901"}).status_code == 409

    secret = get_settings().secret_key
    from app.config import Settings

    token = upi_review_token(Settings(secret_key=secret, environment="test"), cid)
    assert client.get(f"/api/billing/upi/{cid}/review?t=wrong").status_code == 404
    page = client.get(f"/api/billing/upi/{cid}/review?t={token}")
    assert page.status_code == 200 and "412345678901" in page.text and "Approve" in page.text
    done = client.post(f"/api/billing/upi/{cid}/review", data={"t": token, "action": "approve"})
    assert done.status_code == 200 and "activated" in done.text.lower()
    sub = client.get("/api/billing/subscription").json()
    assert sub["subscription"]["is_paid"] and sub["subscription"]["provider"] == "upi"
    assert sub["invoices"][0]["amount_cents"] > 0
    # approving twice is harmless
    assert client.post(f"/api/billing/upi/{cid}/review", data={"t": token, "action": "approve"}).status_code == 200
    assert len(client.get("/api/billing/subscription").json()["invoices"]) == 1


def test_upi_reference_cannot_be_reused(client, user, override_settings):
    cid = _upi_checkout(client, user, override_settings)
    assert client.post(f"/api/billing/upi/{cid}/submit", json={"reference": "UTR99887766"}).status_code == 200
    # a second checkout (another interval) with the same UTR is rejected
    r = client.post("/api/billing/checkout", json={"plan_slug": "pro", "interval": "year"})
    cid2 = r.json()["checkout_id"]
    assert client.post(f"/api/billing/upi/{cid2}/submit", json={"reference": "utr99887766"}).status_code == 409


def test_upi_card_option_needs_razorpay(client, user, override_settings):
    cid = _upi_checkout(client, user, override_settings)
    assert client.get(f"/api/billing/upi/{cid}").json()["cards_available"] is False
    assert client.post(f"/api/billing/upi/{cid}/card").status_code == 503


def test_http_email_provider_is_used(monkeypatch):
    from app.config import get_settings
    from app.services import mailer

    sent = {}

    class R:
        status_code = 201
        text = "ok"

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers)
        return R()

    monkeypatch.setattr(mailer.httpx, "post", fake_post)
    s = get_settings().model_copy(update={"brevo_api_key": "k", "email_from": "IRON-AI <me@gmail.com>"})
    mailer.send_email("owner@example.com", "Hi", "text", "<p>html</p>", "test", settings=s)
    assert sent["url"].startswith("https://api.brevo.com") and sent["headers"]["api-key"] == "k"
    assert sent["json"]["to"] == [{"email": "owner@example.com"}] and sent["json"]["sender"]["email"] == "me@gmail.com"


def test_home_has_phone_only_stylesheet_and_responsive_hero(client):
    html = client.get("/").text
    assert 'href="/static/css/mobile.css' in html and 'media="(max-width: 640px)"' in html
    assert "hero-m.jpg" in html and 'sizes="100vw"' in html
    assert client.get("/static/css/mobile.css").status_code == 200
