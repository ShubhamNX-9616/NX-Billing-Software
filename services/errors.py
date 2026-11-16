"""One place for how the app reports unexpected failures.

Before this, 60+ routes did `return jsonify({"error": str(e)}), 500`: the raw
Python / SQLite error text (table names, SQL, file paths) went to whoever made the
request, and nothing was written to a log, so a failure left no trace for the
shop admin to find. server_error() fixes both: it logs the real exception (with
traceback) and sends back only a short, safe message.
"""
from flask import current_app, jsonify, request
from werkzeug.exceptions import HTTPException

GENERIC_500 = ("Something went wrong on the server. Please try again, and tell the "
               "shop admin if it keeps happening.")


def server_error(exc=None):
    """Log the exception being handled and return a generic 500 JSON response.
    Call it from inside an `except` block: `return server_error(e)`.

    A deliberate HTTP error (for example 413 "request too large", raised when a route
    reads an oversized body) is not a crash: `except Exception` blocks catch those
    too, so it is re-raised here for the app-wide handler to answer with the right
    status instead of being reported as a 500."""
    if isinstance(exc, HTTPException):
        raise exc
    current_app.logger.error("Unhandled error in %s %s", request.method, request.path,
                             exc_info=exc if exc is not None else True)
    return jsonify({"error": GENERIC_500}), 500


def _wants_json():
    return request.path.startswith("/api/")


def install_error_handlers(app):
    """Catch-all for anything a route did not handle itself.

    /api/ callers (the page scripts) always get JSON with the right status code,
    never an HTML error page they cannot parse. Other pages keep Flask's normal
    HTTP error pages, and an unexpected crash is logged and shown as a plain
    message instead of leaking a traceback."""

    @app.errorhandler(Exception)
    def _handle(exc):
        if isinstance(exc, HTTPException):
            if not _wants_json():
                return exc
            message = exc.description or exc.name
            if exc.code == 413:
                limit_mb = (app.config.get("MAX_CONTENT_LENGTH") or 0) // (1024 * 1024)
                message = f"That file is too large (the limit is {limit_mb} MB)." if limit_mb \
                    else "That file is too large."
            return jsonify({"error": message}), exc.code
        app.logger.error("Unhandled error in %s %s", request.method, request.path, exc_info=exc)
        if _wants_json():
            return jsonify({"error": GENERIC_500}), 500
        return (f"<h3 style='font-family:sans-serif;text-align:center;margin-top:40px;'>"
                f"{GENERIC_500}</h3>"), 500
