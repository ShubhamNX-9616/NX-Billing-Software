"""Mirror Try-On pictures.

The try-on tablet app (a separate site on Vercel) sends its server-side calls
here with the shared secret in the X-Tryon-Secret header, so the secret never
reaches the tablet's browser:
  GET  /api/tryon/inventory/<code>   check an inventory code before saving
  POST /api/tryon/photos             save a finished try-on picture

Pictures are stored as  tryon/<garment>/<INVENTORY-CODE>.jpg  on Cloudflare R2
(local disk if R2 isn't configured or the upload fails), mirroring how the
tailoring photos work. Saving the same code + garment again replaces the old
picture. Staff browse them in the Try-On Gallery, which serves images itself
behind the normal login — the bucket's public URL is never handed out.
"""
import base64
import binascii
import hmac
import io
import os
import re
from functools import wraps

from flask import Blueprint, Response, jsonify, render_template, request
from PIL import Image, ImageOps

from db import IST_NOW, get_db
from services import r2_storage
from services.auth import (
    api_admin_required,
    api_staff_or_admin_required,
    staff_or_admin_required,
)
from services.inventory import find_item_by_code

tryon_api_bp = Blueprint("tryon_api", __name__)
tryon_pages_bp = Blueprint("tryon_pages", __name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "tryon")

# Folder name -> label. Keep in step with STYLES in the try-on app's lib/prompts.js.
GARMENTS = {
    "kurta": "Kurta",
    "suit": "Suit",
    "blazer": "Blazer",
    "shirt": "Shirt",
    "pant": "Pant",
    "bandhgala": "Bandhgala",
    "nehru": "Nehru jacket",
}
MAX_IMAGE_BYTES = 6_000_000   # after base64 decoding; the app sends ~0.3-1 MB
MAX_PHOTO_DIM = 1600
JPEG_QUALITY = 85
MIN_SECRET_LEN = 16


def tryon_secret_required(f):
    """Only the try-on app's server may call these endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        expected = os.environ.get("TRYON_SHARED_SECRET", "")
        if len(expected) < MIN_SECRET_LEN:
            return jsonify({"error": "Try-on saving is not set up on this server."}), 503
        given = request.headers.get("X-Tryon-Secret", "")
        if not hmac.compare_digest(given.encode(), expected.encode()):
            return jsonify({"error": "Not allowed."}), 401
        return f(*args, **kwargs)
    return decorated


def _safe_code(code):
    return re.sub(r"[^A-Za-z0-9_-]", "_", code or "")


def _key(garment, code):
    return f"tryon/{garment}/{code}.jpg"


def _local_path(garment, code):
    return os.path.join(UPLOAD_DIR, garment, f"{code}.jpg")


def _remove_local(garment, code):
    try:
        os.remove(_local_path(garment, code))
    except OSError:
        pass


def _item_summary(item):
    return {
        "item_code": item["item_code"],
        "item_name": item["item_name"],
        "cloth_type": item["cloth_type"],
        "company_name": item["company_name"],
        "quality_number": item["quality_number"],
        "shade_number": item["shade_number"],
    }


# ---------------------------------------------------------------------------
# Called by the try-on app's server
# ---------------------------------------------------------------------------
@tryon_api_bp.route("/tryon/inventory/<path:code>", methods=["GET"])
@tryon_secret_required
def lookup_inventory(code):
    item = find_item_by_code(get_db(), code)
    if not item or not item["item_code"]:
        return jsonify({"error": "Item not found"}), 404
    return jsonify(_item_summary(item))


@tryon_api_bp.route("/tryon/photos", methods=["POST"])
@tryon_secret_required
def save_photo():
    body = request.get_json(silent=True) or {}
    garment = body.get("garment")
    if garment not in GARMENTS:
        return jsonify({"error": "Unknown garment."}), 400

    db = get_db()
    item = find_item_by_code(db, str(body.get("item_code") or "").strip())
    if not item or not item["item_code"]:
        return jsonify({"error": "Inventory code not found."}), 404
    code = _safe_code(item["item_code"])

    raw = body.get("image")
    if not isinstance(raw, str) or not raw:
        return jsonify({"error": "No picture provided."}), 400
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    if len(raw) > MAX_IMAGE_BYTES * 4 // 3 + 16:
        return jsonify({"error": "Picture is too large."}), 413
    try:
        data = base64.b64decode(raw, validate=True)
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((MAX_PHOTO_DIM, MAX_PHOTO_DIM))
    except (binascii.Error, ValueError, OSError):
        return jsonify({"error": "That is not a valid picture."}), 400

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)

    # R2 first (keeps the server's disk quota free); local disk if R2 isn't
    # configured or the upload fails, so a picture is never lost.
    key = _key(garment, code)
    on_r2 = r2_storage.is_configured() and r2_storage.upload_bytes(buf.getvalue(), key)
    if on_r2:
        _remove_local(garment, code)
    else:
        os.makedirs(os.path.dirname(_local_path(garment, code)), exist_ok=True)
        with open(_local_path(garment, code), "wb") as f:
            f.write(buf.getvalue())
        if r2_storage.is_configured():
            r2_storage.delete_object(key)   # don't leave a stale older copy

    db.execute(
        f"""INSERT INTO tryon_photos (garment, item_code, storage, created_at)
            VALUES (?, ?, ?, {IST_NOW})
            ON CONFLICT(garment, item_code) DO UPDATE SET
                storage = excluded.storage, created_at = excluded.created_at""",
        (garment, code, "r2" if on_r2 else "local"),
    )
    db.commit()
    return jsonify({
        "ok": True,
        "garment": garment,
        "item_code": item["item_code"],
        "item_name": item["item_name"],
        "path": key,
    }), 201


# ---------------------------------------------------------------------------
# Try-On Gallery (logged-in staff)
# ---------------------------------------------------------------------------
@tryon_pages_bp.route("/tryon-gallery")
@staff_or_admin_required
def gallery_page():
    return render_template("tryon_gallery.html", garments=GARMENTS)


@tryon_api_bp.route("/tryon-gallery", methods=["GET"])
@api_staff_or_admin_required
def gallery_list():
    garment = request.args.get("garment", "").strip()
    q = request.args.get("q", "").strip()
    sql = """SELECT p.id, p.garment, p.item_code, p.created_at,
                    i.item_name, i.company_name, i.quality_number
             FROM tryon_photos p
             LEFT JOIN inventory_items i ON i.item_code = p.item_code
             WHERE 1=1"""
    params = []
    if garment in GARMENTS:
        sql += " AND p.garment = ?"
        params.append(garment)
    if q:
        sql += " AND (p.item_code LIKE ? OR i.item_name LIKE ? OR i.company_name LIKE ? OR i.quality_number LIKE ?)"
        params += [f"%{q}%"] * 4
    sql += " ORDER BY p.created_at DESC, p.id DESC LIMIT 500"
    rows = []
    for r in get_db().execute(sql, params).fetchall():
        d = dict(r)
        d["garment_label"] = GARMENTS.get(d["garment"], d["garment"])
        d["url"] = f"/tryon-gallery/image/{d['garment']}/{d['item_code']}?v={d['created_at']}"
        rows.append(d)
    return jsonify(rows)


@tryon_pages_bp.route("/tryon-gallery/image/<garment>/<code>")
@api_staff_or_admin_required
def gallery_image(garment, code):
    row = get_db().execute(
        "SELECT storage FROM tryon_photos WHERE garment = ? AND item_code = ?",
        (garment, code),
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    if row["storage"] == "r2":
        data = r2_storage.download_bytes(_key(garment, code))
    else:
        try:
            with open(_local_path(garment, _safe_code(code)), "rb") as f:
                data = f.read()
        except OSError:
            data = None
    if not data:
        return jsonify({"error": "Picture file is missing."}), 404
    return Response(data, mimetype="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


@tryon_api_bp.route("/tryon-gallery/<int:photo_id>", methods=["DELETE"])
@api_admin_required
def gallery_delete(photo_id):
    db = get_db()
    row = db.execute("SELECT * FROM tryon_photos WHERE id = ?", (photo_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    db.execute("DELETE FROM tryon_photos WHERE id = ?", (photo_id,))
    db.commit()
    code = _safe_code(row["item_code"])
    _remove_local(row["garment"], code)
    if r2_storage.is_configured():
        r2_storage.delete_object(_key(row["garment"], code))
    return jsonify({"ok": True})
