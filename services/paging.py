"""Shared ?limit= / ?offset= handling for list endpoints.

The bill history lists used to return every bill in one response, so the page got
slower (and the download bigger) with every bill ever made. Endpoints now accept
?limit= and ?offset= and report the full match count in the X-Total-Count header;
the history page loads a first page and a "Show more" button fetches the rest.
Without ?limit= nothing changes, so other callers keep getting the full list."""
from flask import jsonify, request

MAX_PAGE_SIZE = 1000


def page_args():
    """(limit, offset) from the query string. limit is None (= no limit) unless a
    positive ?limit= was sent, and is capped at MAX_PAGE_SIZE; offset is never negative."""
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", default=0, type=int) or 0
    limit = min(limit, MAX_PAGE_SIZE) if limit and limit > 0 else None
    return limit, max(offset, 0)


def page_sql(limit, offset):
    """The LIMIT/OFFSET tail for a query. Both values are integers by construction."""
    if limit is None:
        return f" LIMIT -1 OFFSET {offset}" if offset else ""
    return f" LIMIT {limit} OFFSET {offset}"


def paged_json(rows, total):
    """JSON array of rows, with the number of rows matching the whole query."""
    resp = jsonify([dict(r) for r in rows])
    resp.headers["X-Total-Count"] = str(total)
    return resp
