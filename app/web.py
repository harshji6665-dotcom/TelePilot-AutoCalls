import base64
import hashlib
from pathlib import Path
import re
import time
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .security import UserError, digest

COOKIE = "telepilot_login"


class ExchangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=30, max_length=100)


class StepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=512)
    consent: bool = False


class BrowserLimiter:
    def __init__(self):
        self.buckets = {}

    def allow(self, identity):
        current = time.monotonic()
        if len(self.buckets) > 1000:
            self.buckets = {k: v for k, v in self.buckets.items() if current - v[0] < 300}
        since, count = self.buckets.get(identity, (current, 0))
        if current - since > 300:
            since, count = current, 0
        self.buckets[identity] = (since, count + 1)
        return count < 10


def build_web(runtime):
    config, login = runtime.config, runtime.login
    app = FastAPI(title="TelePilot", docs_url=None, redoc_url=None, openapi_url=None)
    public_host = urlparse(config.public_base_url).hostname
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "app", "healthcheck.railway.app"] + ([public_host] if public_host else []),
    )
    template = (Path(__file__).parent / "templates/login.html").read_text(encoding="utf-8")
    script = re.search(r"<script>(.*?)</script>", template, re.S).group(1)
    script_hash = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    limiter = BrowserLimiter()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if not runtime.ready or runtime.stopping:
                return JSONResponse(
                    {"error": "Service is starting or shutting down. Wait for /health/ready, then use a fresh bot login link if needed."},
                    status_code=503,
                    headers={"Cache-Control": "no-store"},
                )
            if request.url.path.startswith("/api/login/") and config.login_mode != "browser":
                return JSONResponse(
                    {"error": "Browser sign-in is disabled. Use the private-chat account panel."},
                    status_code=410,
                    headers={"Cache-Control": "no-store"},
                )
            origin = request.headers.get("origin")
            if origin and origin != config.public_base_url:
                return JSONResponse({"error": "Wrong site origin."}, status_code=403)
            if request.method == "POST" and origin != config.public_base_url:
                return JSONResponse({"error": "Same-site HTTPS origin required."}, status_code=403)
            size = request.headers.get("content-length", "0")
            if not size.isdigit() or int(size) > 2048:
                return JSONResponse({"error": "Request too large."}, status_code=413)
            # Bound both declared and chunked bodies; never accumulate unbounded credentials.
            if request.method == "POST":
                import asyncio

                chunks, total = [], 0
                try:
                    async with asyncio.timeout(10):
                        async for chunk in request.stream():
                            total += len(chunk)
                            if total > 2048:
                                return JSONResponse({"error": "Request too large."}, status_code=413)
                            chunks.append(chunk)
                except TimeoutError:
                    return JSONResponse({"error": "Request timed out."}, status_code=408)
                request._body = b"".join(chunks)  # Starlette's cached-body contract for downstream parsing.
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": f"default-src 'none'; script-src 'sha256-{script_hash}'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        if config.public_base_url:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_, exc):
        # FastAPI's default validation response includes the raw input value.
        # Credential fields must never be reflected into error payloads.
        return JSONResponse({"error": "Invalid or oversized login input."}, status_code=422)

    @app.exception_handler(UserError)
    async def user_error(_, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(Exception)
    async def internal_error(_, exc):
        import logging

        logging.getLogger(__name__).error("Portal action failed; error=%s", type(exc).__name__)
        return JSONResponse({"error": "Temporary server error. Request a fresh login link if needed."}, status_code=503)

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        import asyncio

        try:
            await asyncio.wait_for(runtime.store.client.admin.command("ping"), 3)
            healthy = runtime.ready and not runtime.stopping and all(not t.done() for t in runtime.tasks)
        except Exception:
            healthy = False
        return JSONResponse({"status": "ready" if healthy else "not_ready"}, status_code=200 if healthy else 503)

    @app.get("/")
    @app.get("/login")
    async def page():
        if config.login_mode != "browser":
            return HTMLResponse("<h1>Browser sign-in disabled</h1><p>Use Sign in account in your private bot chat.</p>", status_code=410)
        return HTMLResponse(template)

    @app.post("/api/login/exchange")
    async def exchange(body: ExchangeBody, request: Request):
        if not config.public_base_url:
            raise UserError("HTTPS sign-in is not configured by the operator.")
        if not limiter.allow(request.client.host if request.client else "unknown"):
            return JSONResponse({"error": "Too many login attempts. Wait five minutes."}, status_code=429)
        cookie, csrf, context = await login.exchange(body.token)
        response = JSONResponse({**login.status(context), "csrf": csrf})
        response.set_cookie(COOKIE, cookie, max_age=600, secure=True, httponly=True, samesite="strict", path="/api/login")
        return response

    @app.get("/api/login/status")
    async def status(request: Request):
        context = await login.get(request.cookies.get(COOKIE))
        return {**login.status(context), "csrf": context.csrf}

    @app.post("/api/login/step")
    async def step(body: StepBody, request: Request):
        context = await login.get(request.cookies.get(COOKIE), request.headers.get("x-csrf-token", ""))
        if context.stage == "phone" and not body.consent:
            raise UserError("Confirm that you own this account and authorize storing its session.")
        return await login.step(context, body.value)

    @app.post("/api/login/cancel")
    async def cancel(request: Request):
        cookie = request.cookies.get(COOKIE)
        await login.get(cookie, request.headers.get("x-csrf-token", ""))
        await login.close_context(digest(cookie))
        response = JSONResponse({"stage": "denied"})
        response.delete_cookie(COOKIE, path="/api/login", secure=True, httponly=True, samesite="strict")
        return response

    return app
