# IRON-AI

FastAPI + SQLAlchemy backend and a self-hosted, no-build frontend (Jinja templates, plain ES modules, no CDN calls).

## Run it (2 minutes)

Requires Python 3.11+ (on Windows, just double-click run.bat; see START_HERE.txt).

```bash
# macOS / Linux
./run.sh

# Windows
run.bat
```

Or by hand:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
python -m uvicorn app.main:app --reload --reload-dir app --port 8000
```

Open http://localhost:8000. On first start a dev admin is created and its password is **printed once in the terminal**
(or set `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env` before first start). Admin panel: http://localhost:8000/admin.
API docs (dev only): http://localhost:8000/api/docs.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # in-memory database
```

## What is where

```
app/            FastAPI app: routers/ (HTTP), services/ (logic), models, schemas, security, seed
web/templates/  base, index (landing), account, checkout, admin, legal/, 404
web/static/     css/, js/ (shell, lib/, features/, pages/), fonts/ (self-hosted), img/ (icons.svg sprite, favicon, og.png)
tests/          pytest suite
scripts/        build_icons.py (regenerates the icon sprite)
```

Main endpoints: `/api/waitlist`, `/api/contact`, `/api/assessments`, `/api/assistant/message`, `/api/auth/*`,
`/api/billing/*`, `/api/admin/*`, `/api/plans|programs|faqs|testimonials|stats|config|health`.

## Camera form coach, exercise library, diet planner, rupees

- **Camera form coach** (squat, deadlift, push-up, pull-up): runs fully in the browser with MediaPipe Pose, self-hosted in
  `web/static/vendor/mediapipe/pose/` (no CDN). Video is never uploaded; only rep counts and scores are saved, and only if
  the user is signed in and finishes a session. It needs `localhost` or HTTPS for camera access, and a browser with
  hardware graphics acceleration (on a machine without a GPU it is too slow and says so). Free plan: squat, 3-minute
  sessions. Pro: all four lifts, unlimited time, voice cues, history. These limits are enforced in the page, so treat them
  as a soft paywall.
- **Demo mode**: "Watch a demo" plays a simulated athlete through the real analysis, so the coach can be seen without a camera. Outside production every lift is unlocked (`COACH_ALL_FREE` overrides this: `true` or `false`).
- **Ghost coach maths** lives in `web/static/js/lib/formmath.js` (pure functions, no DOM); the synthetic athletes that
  drive both the demo and the tests live in `web/static/js/lib/demo.js`. Add `?debug=1` to the URL to get
  `window.__coach` for feeding test landmarks without a camera.
- **Exercise library** (`app/services/exercise_library.py`, `GET /api/exercise-library`): correct-form reference cards for
  24 exercises across 7 muscle groups. The four the camera can watch live link straight to the coach.
- **Diet planner**: `app/services/diet.py` (Mifflin-St Jeor, protein and fat per kg, Indian foods table). Adults 18+, refuses a
  cut at a low BMI, caps weekly loss and keeps a calorie floor. Estimates only; the food table is approximate, so have a
  dietitian review it before you rely on it commercially.
- **Prices are in Indian rupees** (default `CURRENCY=INR`): Pro 499 / month or 4,990 / year, Elite 1,299 / month or 12,990 / year.
  Edit them in `app/seed.py` or the admin panel. An old database with the dollar prices upgrades on restart unless you edited the plans.
- **Weekly schedules** per program are in `app/services/training.py`.
- MediaPipe Pose is Apache-2.0 licensed (Google).

Run the JS tests with `node --test tests/js/formmath.test.mjs`.

## Imagery

The hero is the uploaded painting, cropped and graded into the site's palette by `scripts/hero_from_photo.py`
(`python scripts/hero_from_photo.py <image> --crop L,T,R,B --out web/static/img/hero.jpg`; the `--crop` fractions cut
out a frame/border, and `text_band(...)` inside that script darkens the vertical band the headline sits in, since a
published page's `mix-blend-mode: screen` only recedes where the image itself is dark). The other three photos are
studio renders made by `scripts/render_scenes.py` (numpy ray-marching, no stock photos). To use your own photography
for any of them, just overwrite `hero.jpg`, `scene-barbell.jpg`, `scene-kettlebell.jpg` or `scene-plates.jpg` in
`web/static/img/` — dark, low-key photos blend in best.

## Hero photo (optional)

A generated placeholder (a lit weight plate) ships as `web/static/img/hero.jpg`. To use your own photo, save it over that file (also `.jpeg`, `.webp`, `.png`, `.avif`). It appears behind the hero automatically,
with a slow zoom-in. Delete the file to go back to the lightning-only look. Only use images you own or have licensed.

## Behaviour worth knowing

- **Payments** default to `PAYMENTS_PROVIDER=mock`: a test-mode checkout page, no card, no money.
  - `stripe`: set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`, and point a Stripe webhook at `{BASE_URL}/api/billing/webhook/stripe`
    (events: `checkout.session.completed`, `invoice.paid`, `customer.subscription.updated`, `customer.subscription.deleted`).
  - `razorpay`: set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (full walkthrough in `.env.example`).
    Checkout opens a Razorpay Payment Link (UPI, cards, netbanking, wallets) hosted on Razorpay's own domain — nothing
    to build on the frontend. It's a one-off charge per billing period, not an auto-debit mandate: `app/services/payments.py`
    explains that trade-off, and a subscription paid this way is marked `past_due` (not silently renewed) once its period
    lapses, prompting a fresh payment link from the account page. Every successful payment emails a receipt to the customer
    and a notification to `CONTACT_INBOX` (defaults to `SUPPORT_EMAIL`).
  - Either live provider **needs its own account and a public HTTPS URL** for the webhook to reach this app — neither
    can be tested from a sandbox with no network access to the provider, so treat any "payments work end to end" claim
    as untested until you've run one real payment yourself.
- **Stay signed in**: sessions last 45 days and silently renew on every visit (`GET /api/auth/session`, called on every
  page load), so anyone who returns at least once every 45 days never gets logged out. Tune with `SESSION_DAYS`.
- **Require login**: `REQUIRE_LOGIN=true` sends anyone not signed in to `/welcome` (sign in or create an account)
  before they see the site at all. Off by default, since a subscription business usually wants visitors to see
  pricing and features first; this is for a members-only / invite-only setup specifically. The API, `/terms`,
  `/privacy` and `/welcome` itself stay reachable either way (the sign-in forms need somewhere to submit to).
- **Email**: without `SMTP_HOST` every email is only recorded (read them in Admin > Emails). Set SMTP_* to really send —
  this includes the payment notification above, so without SMTP configured it will only ever land in the admin outbox,
  not a real inbox.
- **AI assistant**: safety checks (crisis language, medical red flags) run in code first and always win. Below that it uses
  a built-in rules engine; set `ANTHROPIC_API_KEY` to let a model answer everything else.
- **Assessment** answers are never stored unless the visitor opts in (consent box) or is signed in and clicks save.
- **Analytics** are anonymous counters only (no IP, cookie or user id).
- **Rate limits** are in-memory per process. Use one worker, or swap `app/ratelimit.py` for Redis before scaling out.
- **Sign-up** tells people when an email is already registered (needed for UX); password reset and login do not leak this.

## Before you go live

1. `ENVIRONMENT=production`, `BASE_URL=https://your-domain`, a real `SECRET_KEY` (48+ random chars), `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
2. `SEED_SAMPLE_CONTENT=false`, then add real testimonials in Admin > Content (placeholders show a notice on the page until deleted).
3. Edit plan prices/features and program copy in `app/seed.py` (used only on an empty database) or in the database.
4. Set `COMPANY_NAME`, `SUPPORT_EMAIL`, `CONTACT_INBOX`, `EMAIL_FROM`, SMTP_*, social links — these ship pre-filled with
   Divya Solanki / divyasolanki10125@gmail.com; change them in `.env` (or `app/config.py`'s defaults) if that's wrong.
5. Have a lawyer review `web/templates/legal/*.html`.
6. Verify every product claim on the landing page is true for what you actually ship (form tracking, feedback cues).
7. Use Postgres for real traffic: `DATABASE_URL=postgresql+psycopg://user:pass@host/db` and `pip install "psycopg[binary]"`.
   (Tables are created automatically; there is no migration tool yet. Add Alembic before changing the schema in production.)
8. Serve behind HTTPS (Caddy/nginx/a platform proxy). Cookies become `Secure` automatically when BASE_URL starts with https.

## UPI QR payments, cards and email on Render

* `PAYMENTS_PROVIDER=upi` shows a QR (built from `UPI_ID`, amount pre-filled) plus a deep link for UPI apps. The customer submits the UTR; the owner gets an email ("UPI payment to confirm") with a signed link to Approve/Reject. The plan activates only after approval. Never leave `PAYMENTS_PROVIDER=mock` on a public site: it grants plans for free.
* Cards/netbanking/wallets: add `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (webhook URL `/api/billing/webhook/razorpay`, event `payment_link.paid`). The checkout page then shows "Pay by card".
* Render's free plan blocks SMTP. Set `BREVO_API_KEY` (and a verified `EMAIL_FROM`) or `RESEND_API_KEY`. Check Admin > Emails: status `sent` / `failed` (with the error) / `logged` (no provider configured).
