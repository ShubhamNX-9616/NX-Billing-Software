"""Request-level protections that wrap the whole app (see app.py)."""
import os

from flask import request, session
from werkzeug.middleware.proxy_fix import ProxyFix

DEFAULT_UPLOAD_MB = 25
MAX_IMAGE_PIXELS = 60_000_000       # ~ a 7700x7700 photo; anything bigger is refused


def env_int(name, default):
    """Integer from an environment variable; a blank or garbled value means `default`."""
    try:
        return int(str(os.environ.get(name, "")).strip())
    except ValueError:
        return default


def install_proxy_fix(app, proxy_count):
    """Trust exactly `proxy_count` reverse proxies for the client address.

    The login lockout is keyed on the client's IP. Reading the *first* entry of
    X-Forwarded-For (as the code used to) lets anyone send their own header and
    look like a new address on every attempt, so the lockout never triggered.
    ProxyFix takes the entry written by our own proxy - counted from the right,
    where a client cannot forge it - and exposes it as request.remote_addr.

    1 fits PythonAnywhere and a Cloudflare tunnel (one proxy in front). Use 0 when
    nothing sits in front of the app (plain LAN use), so the header is ignored."""
    if proxy_count and proxy_count > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count)


def install_request_limits(app, max_upload_mb=DEFAULT_UPLOAD_MB):
    """Refuse oversized request bodies before they are read into memory, and cap
    the pixel count Pillow will decode (a small file can claim to be enormous)."""
    app.config["MAX_CONTENT_LENGTH"] = max(1, int(max_upload_mb)) * 1024 * 1024
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    except ImportError:          # Pillow is optional for this module's other job
        pass


# Frame-ancestors / base-uri / object-src / form-action only: they block clickjacking
# and injected <base>/<object>/forms without forbidding inline scripts, which the pages
# use heavily. A full script-src policy would need those scripts moved to files first.
CONTENT_SECURITY_POLICY = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"


def install_security_headers(app):
    """Standard browser protections on every response.

      X-Content-Type-Options    the browser must not guess a file's type (an uploaded
                                "photo" is never run as a script)
      X-Frame-Options / CSP     no other site may put these pages in a frame
                                (clickjacking: tricking a click on a hidden button)
      Referrer-Policy           other sites only learn our domain, not the page path
      Permissions-Policy        camera for ourselves only; no microphone/location/payment
      Strict-Transport-Security tells browsers to insist on HTTPS (only when the site is
                                configured for HTTPS via SESSION_COOKIE_SECURE)
      Cache-Control: no-store   pages and data shown to a signed-in user are not kept in
                                the browser cache, so the Back button after logging out
                                on a shared PC cannot reopen them

    Headers a route already set (photo caching, static files) are left as they are."""

    @app.after_request
    def _add_headers(response):
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=()")
        h.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if app.config.get("SESSION_COOKIE_SECURE"):
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        if (request.endpoint != "static" and "Cache-Control" not in h
                and session.get("user_id") is not None):
            h["Cache-Control"] = "no-store"
        return response
