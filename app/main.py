"""Application assembly: routers, security middleware, pages and static files."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from .config import APP_VERSION, WEB_DIR, Settings, get_settings
from .database import SessionLocal, get_db, init_db
from .errors import error_response, register_error_handlers
from .models import Faq
from .routers import admin, assistant, auth, billing, diet, leads, public
from .security import optional_user
from .seed import ensure_admin, seed_reference_data

log = logging.getLogger("iron.app")

templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
PRIVATE_PAGES = ("/account", "/admin", "/checkout", "/welcome")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'wasm-unsafe-eval'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    with SessionLocal() as db:
        seed_reference_data(db, settings)
        ensure_admin(db, settings)
    log.info("%s %s ready (%s)", settings.app_name, APP_VERSION, settings.environment)
    if settings.open_browser and not settings.is_production:
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(settings.base_url)).start()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    register_error_handlers(app)

    # ------------------------------------------------------------ error pages
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
            message = {404: "Not found.", 405: "That method is not allowed here."}.get(exc.status_code, str(exc.detail))
            return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))
        if exc.status_code == 404:
            return render(request, "404.html", status_code=404)
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(500, "server_error", "Something went wrong on our side. Please try again.")

    # ------------------------------------------------------------ middleware
    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        # CSRF defence in depth: browsers always send Origin on cross-site unsafe requests.
        if request.method in UNSAFE and path.startswith("/api/") and path not in ("/api/billing/webhook/stripe", "/api/billing/webhook/razorpay"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host", ""):
                return error_response(403, "bad_origin", "Cross-site requests are not allowed.")
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if settings.cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if path.startswith("/api/") or path.startswith(PRIVATE_PAGES):
            h.setdefault("Cache-Control", "no-store")
        if path.startswith(PRIVATE_PAGES):
            h.setdefault("X-Robots-Tag", "noindex, nofollow")
        return response

    app.add_middleware(GZipMiddleware, minimum_size=800)

    # --------------------------------------------------------------- routers
    for module in (public, leads, assistant, auth, billing, diet, admin):
        app.include_router(module.router)

    # ---------------------------------------------------------------- static
    class Static(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable" if path.startswith(("fonts/", "img/")) else "public, max-age=3600"
                )
            return response

    app.mount("/static", Static(directory=str(WEB_DIR / "static")), name="static")

    # ----------------------------------------------------------------- pages
    def page(path: str, template: str, **extra):
        async def handler(request: Request):
            return render(request, template, **extra)

        app.add_api_route(path, handler, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(request: Request, settings_now: Settings = Depends(get_settings)):
        with SessionLocal() as db:
            if settings_now.require_login and optional_user(request, db, settings_now) is None:
                return RedirectResponse(f"/welcome?next={request.url.path}", status_code=302)
            faqs = list(db.scalars(select(Faq).where(Faq.published).order_by(Faq.sort_order, Faq.id)))
        graph = [
            {"@type": "Organization", "name": settings.company_name, "url": settings.base_url,
             "logo": f"{settings.base_url}/static/img/favicon.svg"},
            {"@type": "WebSite", "name": settings.app_name, "url": settings.base_url},
        ]
        if faqs:
            graph.append({
                "@type": "FAQPage",
                "mainEntity": [
                    {"@type": "Question", "name": f.question, "acceptedAnswer": {"@type": "Answer", "text": f.answer}}
                    for f in faqs
                ],
            })
        ld_json = json.dumps({"@context": "https://schema.org", "@graph": graph}).replace("</", "<\\/")
        return render(request, "index.html", page_id="home", faqs=faqs, ld_json=ld_json)

    page("/account", "account.html", page_id="account", title="Your account")
    page("/checkout/{checkout_id}", "checkout.html", page_id="checkout", title="Secure checkout")
    page("/admin", "admin.html", page_id="admin", title="Admin")
    page("/welcome", "welcome.html", page_id="welcome", title="Sign in")
    page("/terms", "legal/terms.html", page_id="legal", title="Terms of service")
    page("/privacy", "legal/privacy.html", page_id="legal", title="Privacy policy")

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        body = (
            "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /account\nDisallow: /admin\nDisallow: /checkout/\nDisallow: /welcome\n"
            f"Sitemap: {settings.base_url}/sitemap.xml\n"
        )
        return PlainTextResponse(body)

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap():
        today = datetime.now(timezone.utc).date().isoformat()
        urls = "".join(
            f"<url><loc>{settings.base_url}{p}</loc><lastmod>{today}</lastmod></url>" for p in ("/", "/terms", "/privacy")
        )
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
        return Response(xml, media_type="application/xml")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=301, headers={"Location": "/static/img/favicon.svg"})

    return app


def hero_image() -> str | None:
    """Drop a photo named hero.jpg/.jpeg/.webp/.png/.avif into web/static/img and it appears behind the hero."""
    for ext in ("jpg", "jpeg", "webp", "png", "avif"):
        if (WEB_DIR / "static" / "img" / f"hero.{ext}").exists():
            return f"hero.{ext}"
    return None


def render(request: Request, template: str, status_code: int = 200, **extra) -> HTMLResponse:
    settings: Settings = get_settings()
    context = {
        "request": request,
        "s": settings,
        "version": APP_VERSION,
        "year": datetime.now(timezone.utc).year,
        "is_production": settings.is_production,
        "hero_image": hero_image() if template == "index.html" else None,
        "title": extra.pop("title", ""),
        **extra,
    }
    return templates.TemplateResponse(request, template, context, status_code=status_code)


app = create_app()
