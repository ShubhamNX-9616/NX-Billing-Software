"""
One-time cleanup: shrink tailoring photos already sitting in Cloudflare R2
that never went through the app's normal upload resize (e.g. the archived
Drive-import scans in scripts/import_drive_measurements.py, which render
PDFs straight to JPEG at a fixed DPI with no size/quality cap).

Uses the exact same resize as a live phone-camera upload
(routes/tailoring.py's upload_photo): longest side capped at MAX_PHOTO_DIM,
re-encoded as JPEG at PHOTO_JPEG_QUALITY. Only touches objects above
--min-kb (default 500, matching what was reported) — anything already
under that is left alone rather than re-compressed for no reason.

Overwrites the object in R2 under the same key, so the app and every DB
row keep working unchanged (filenames don't change) — but this is lossy
and not reversible: once applied, the original larger file is gone from
R2. Dry-run by default; pass --apply to actually overwrite anything.

Usage (from the project root):
    python scripts/shrink_r2_photos.py
    python scripts/shrink_r2_photos.py --min-kb 300
    python scripts/shrink_r2_photos.py --apply
"""

import sys
import os
import io
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from PIL import Image, ImageOps

from db.tailoring import get_tailoring_db
from services import r2_storage
from routes.tailoring import MAX_PHOTO_DIM, PHOTO_JPEG_QUALITY


def iter_photo_filenames(db):
    rows = db.execute("SELECT filename FROM tailoring_photos").fetchall()
    rows += db.execute("SELECT filename FROM tailoring_suit_photos").fetchall()
    return sorted({r["filename"] for r in rows})


def shrink(image_bytes):
    """Same transform as a live upload: EXIF-correct orientation, cap the
    longest side, re-encode as JPEG at the app's standard quality."""
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_PHOTO_DIM, MAX_PHOTO_DIM))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                         help="Actually overwrite oversized objects in R2 (default: dry run)")
    parser.add_argument("--min-kb", type=int, default=500,
                         help="Only shrink objects at or above this size in KB (default 500)")
    args = parser.parse_args()

    if not r2_storage.is_configured():
        print("R2 is not configured (missing R2_* env vars) — nothing to do.")
        sys.exit(1)

    threshold = args.min_kb * 1024
    db = get_tailoring_db()
    filenames = iter_photo_filenames(db)
    print(f"{len(filenames)} distinct photo(s) referenced in the tailoring DB.")

    not_on_r2 = []
    under_threshold = 0
    oversized = []   # (filename, size)

    for name in filenames:
        size = r2_storage.object_size(name)
        if size is None:
            not_on_r2.append(name)
            continue
        if size >= threshold:
            oversized.append((name, size))
        else:
            under_threshold += 1

    total_over_kb = sum(s for _, s in oversized) / 1024
    print(f"  on R2, under {args.min_kb}KB:  {under_threshold}")
    print(f"  on R2, >= {args.min_kb}KB:     {len(oversized)}  ({total_over_kb:.0f} KB total)")
    print(f"  not found on R2 (local-disk fallback, presumably): {len(not_on_r2)}")
    print()

    if not oversized:
        print("Nothing to shrink.")
        return

    if not args.apply:
        print("-- Oversized (first 30 shown) --")
        for name, size in oversized[:30]:
            print(f"  {name}: {size / 1024:.0f} KB")
        if len(oversized) > 30:
            print(f"  ... and {len(oversized) - 30} more")
        print(f"\nDry run only — {len(oversized)} photo(s) would be shrunk. Re-run with --apply to write them.")
        return

    print(f"Applying: shrinking {len(oversized)} photo(s)...")
    shrunk, failed = 0, []
    before_total = after_total = 0

    for name, before_size in oversized:
        try:
            raw = r2_storage.download_bytes(name)
            if raw is None:
                failed.append((name, "download returned nothing"))
                continue
            new_bytes = shrink(raw)
            if not r2_storage.upload_bytes(new_bytes, name):
                failed.append((name, "upload failed"))
                continue
            before_total += before_size
            after_total += len(new_bytes)
            shrunk += 1
        except Exception as e:
            failed.append((name, str(e)))

    print(f"Shrunk {shrunk} photo(s).")
    if before_total:
        pct = 100 * (1 - after_total / before_total)
        print(f"  {before_total/1024:.0f} KB -> {after_total/1024:.0f} KB  ({pct:.0f}% smaller)")
    if failed:
        print(f"Failed: {len(failed)}")
        for name, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
