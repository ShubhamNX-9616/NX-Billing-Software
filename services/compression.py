"""gzip for dynamic text responses (JSON, HTML pages).

The big list endpoints shrink ~10x, which matters on phones and over the
tunnel. Photos, spreadsheets and static files are left alone: JPEGs and xlsx
are already compressed, and static files are streamed and cached by version.
"""
import gzip
from flask import request

MIN_SIZE = 1024
COMPRESSIBLE = ("application/json", "text/html", "text/plain", "text/csv")


def _gzip_response(response):
    if (response.status_code != 200
            or response.direct_passthrough
            or "Content-Encoding" in response.headers
            or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
            or response.mimetype not in COMPRESSIBLE):
        return response
    data = response.get_data()
    if len(data) < MIN_SIZE:
        return response
    response.set_data(gzip.compress(data, compresslevel=5))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(response.get_data()))
    response.headers.add("Vary", "Accept-Encoding")
    return response


def init_compression(app):
    app.after_request(_gzip_response)
