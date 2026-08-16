"""
One-time import of measurement scans from the old Google Drive archive into
the tailoring app.

The Drive folder holds one subfolder per customer, named "<name> <mobile>",
containing scanned PDFs named after the receipt number (e.g. 7386.pdf). Each
PDF is a single-page scan of the paper measurement slip.

For each PDF, the filename is the receipt number:

  - If that number already matches a live order (tailoring_orders or
    tailoring_suit_orders), the scan is attached to it as a measurement photo
    (tailoring_photos, item_id NULL) — the same category a phone-camera
    upload through the app produces.

  - If no such order exists (the common case — this archive mostly predates
    what's in the live DB), a new tailoring_orders row is created with just
    order_number, customer_name, mobile (parsed from the folder name), and
    order_date set to the PDF's embedded scan date (the closest date we have
    — the paper slip doesn't record the true order date). A single
    placeholder item is added, stage 'Delivered', so the order reads as
    closed/historical rather than showing up in the live "In Stitching"
    queue. No garment/pricing detail is invented — none of that survives in
    the scan.

A receipt number that appears under two different customer folders (data
entry conflict in the original paper book) is skipped entirely and reported,
never guessed.

Dry-run by default — prints a report and writes nothing. Pass --apply to
actually write DB rows and image files. Safe to re-run: a manifest file
(<root>/_import_manifest.json) records which source PDFs have already been
imported, so a second --apply run skips them instead of duplicating.

Usage (from the project root):
    python scripts/import_drive_measurements.py --root "drive-download-.../Customer Details"
    python scripts/import_drive_measurements.py --root "..." --only "Abhinav bawaskar 9823292335"
    python scripts/import_drive_measurements.py --root "..." --apply
"""

import sys
import os
import re
import json
import uuid
import argparse
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import fitz  # PyMuPDF

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db.tailoring import get_tailoring_db
from services import r2_storage

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "tailoring")

NAME_STRIP_SUFFIX_RE = re.compile(r"\(\d+\)$")
PDF_DATE_RE = re.compile(r"D:(\d{4})(\d{2})(\d{2})")


def parse_folder(folder_name):
    """'Abhinav bawaskar 9823292335' -> ('Abhinav bawaskar', '9823292335').
    Phone may be absent or malformed (split by spaces, wrong digit count) —
    returns None for phone in that case rather than guessing."""
    digits_only = re.sub(r"\D", "", folder_name)
    m = re.search(r"\d{10}$", digits_only)
    phone = m.group(0) if m else None
    name = folder_name
    if phone:
        name = re.sub(r"[\d\s\-]{10,}$", "", folder_name).strip()
    return name or folder_name, phone


def parse_receipt_number(stem):
    """'5316(1)' -> 5316, 'Copy of 6293' -> 6293, 'Scanned_20251007-2035' -> None."""
    s = stem.strip()
    s = re.sub(r"^copy of\s+", "", s, flags=re.IGNORECASE)
    s = NAME_STRIP_SUFFIX_RE.sub("", s).strip()
    return int(s) if s.isdigit() else None


def scan_date(pdf_path):
    """Best-available date for the slip: the PDF's embedded scan timestamp.
    Falls back to today if a file has no usable metadata (rare)."""
    try:
        doc = fitz.open(pdf_path)
        raw = doc.metadata.get("creationDate") or ""
        doc.close()
        m = PDF_DATE_RE.match(raw)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    except Exception:
        pass
    return date.today().isoformat()


def find_order(db, receipt_number):
    """Look up the receipt number against both the regular order book and the
    suits book. Returns (table, row) or (None, None). Ambiguous matches
    (same number in both books, or duplicated within one) are reported, not
    guessed."""
    regular = db.execute(
        "SELECT * FROM tailoring_orders WHERE order_number = ?", (receipt_number,)
    ).fetchall()
    suits = db.execute(
        "SELECT * FROM tailoring_suit_orders WHERE order_number = ?", (receipt_number,)
    ).fetchall()
    if regular and suits:
        return "ambiguous", None
    if len(regular) > 1 or len(suits) > 1:
        return "ambiguous", None
    if regular:
        return "tailoring_orders", regular[0]
    if suits:
        return "tailoring_suit_orders", suits[0]
    return None, None


def load_manifest(root):
    path = os.path.join(root, "_import_manifest.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(root, manifest):
    path = os.path.join(root, "_import_manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def store_image(image_bytes, filename):
    stored_on_r2 = r2_storage.is_configured() and r2_storage.upload_bytes(image_bytes, filename)
    if not stored_on_r2:
        os.makedirs(os.path.abspath(UPLOAD_DIR), exist_ok=True)
        with open(os.path.join(os.path.abspath(UPLOAD_DIR), filename), "wb") as f:
            f.write(image_bytes)


def pdf_to_jpeg_bytes(pdf_path, dpi):
    doc = fitz.open(pdf_path)
    pix = doc[0].get_pixmap(dpi=dpi)
    data = pix.tobytes("jpeg")
    doc.close()
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Path to the 'Customer Details' folder")
    parser.add_argument("--apply", action="store_true", help="Actually write DB rows and images (default: dry run)")
    parser.add_argument("--only", help="Only process the one subfolder with this exact name (for a single-customer test)")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI for the JPEG (default 200)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Not a directory: {root}")
        sys.exit(1)
    walk_root = os.path.join(root, args.only) if args.only else root
    if args.only and not os.path.isdir(walk_root):
        print(f"No such subfolder under root: {args.only}")
        sys.exit(1)

    manifest = load_manifest(root)
    db = get_tailoring_db()

    # Group every PDF under its receipt number first, so a number that
    # appears under two different customer folders can be caught as a
    # conflict before anything is matched or created.
    by_number = defaultdict(list)   # receipt_number -> [(folder_name, cust_name, cust_phone, src_path, rel_path)]
    unmatched_filenames = []

    for dirpath, _dirnames, filenames in os.walk(walk_root):
        pdfs = [f for f in filenames if f.lower().endswith(".pdf")]
        if not pdfs:
            continue
        folder_name = os.path.basename(dirpath)
        cust_name, cust_phone = parse_folder(folder_name)

        for fname in pdfs:
            src_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(src_path, root)
            stem = os.path.splitext(fname)[0]
            receipt_number = parse_receipt_number(stem)
            if receipt_number is None:
                unmatched_filenames.append((rel_path, "non-numeric filename"))
                continue
            by_number[receipt_number].append((folder_name, cust_name, cust_phone, src_path, rel_path))

    attach_existing = []   # (receipt_number, table, order, [ (src_path, rel_path) ])
    create_new = []        # (receipt_number, cust_name, cust_phone, [ (src_path, rel_path) ])
    conflicts = []         # (receipt_number, [folder_names])
    mobile_mismatch = []
    already_done = []

    for receipt_number, entries in by_number.items():
        distinct_folders = {e[0] for e in entries}
        if len(distinct_folders) > 1:
            conflicts.append((receipt_number, sorted(distinct_folders), [e[4] for e in entries]))
            continue

        folder_name, cust_name, cust_phone = entries[0][0], entries[0][1], entries[0][2]
        srcs = [(e[3], e[4]) for e in entries]

        table, order = find_order(db, receipt_number)
        if table == "ambiguous":
            conflicts.append((receipt_number, [f"{folder_name} (ambiguous vs existing DB rows)"], [e[4] for e in entries]))
            continue

        new_srcs = [(s, r) for s, r in srcs if r not in manifest]
        done_srcs = [r for s, r in srcs if r in manifest]
        already_done.extend(done_srcs)
        if not new_srcs:
            continue

        if order is not None:
            if order["mobile"] and cust_phone and order["mobile"] != cust_phone:
                mobile_mismatch.append((entries[0][4], receipt_number, cust_phone, order["mobile"], order["customer_name"]))
            attach_existing.append((receipt_number, table, order, new_srcs))
        else:
            create_new.append((receipt_number, cust_name, cust_phone, new_srcs))

    total_new_photos = sum(len(s) for *_, s in attach_existing) + sum(len(s) for *_, s in create_new)

    print(f"Scanned under: {walk_root}")
    print(f"  attach to existing order:  {len(attach_existing)} order(s), {sum(len(s) for *_, s in attach_existing)} photo(s)")
    print(f"  create new archived order: {len(create_new)} order(s), {sum(len(s) for *_, s in create_new)} photo(s)")
    print(f"  already imported:          {len(already_done)}")
    print(f"  conflicts (skipped):       {len(conflicts)}")
    print(f"  non-numeric filenames:     {len(unmatched_filenames)}")
    print(f"  mobile mismatches:         {len(mobile_mismatch)}  (imported anyway — receipt number is authoritative)")
    print()

    if attach_existing:
        print("-- Attach to existing order --")
        for num, table, order, srcs in attach_existing:
            print(f"  receipt {num} -> {table}#{order['id']} '{order['customer_name']}' ({order['mobile']})  [{len(srcs)} photo(s)]")
        print()

    if create_new:
        print("-- Create new archived order (first 20 shown) --")
        for num, cust_name, cust_phone, srcs in create_new[:20]:
            print(f"  receipt {num}: '{cust_name}' {cust_phone or '(no phone)'}  [{len(srcs)} photo(s)]  <- {srcs[0][1]}")
        if len(create_new) > 20:
            print(f"  ... and {len(create_new) - 20} more")
        print()

    if conflicts:
        print("-- Conflicts (same receipt number under different folders — skipped, needs manual check) --")
        for num, folders, rels in conflicts:
            print(f"  receipt {num}: {folders}")
            for r in rels:
                print(f"      {r}")
        print()

    if unmatched_filenames:
        print(f"-- Non-numeric filenames (skipped): {len(unmatched_filenames)} --")
        for rel_path, reason in unmatched_filenames[:10]:
            print(f"  {rel_path}: {reason}")
        print()

    if mobile_mismatch:
        print("-- Mobile mismatch on existing-order attach (imported anyway, worth a glance) --")
        for rel_path, num, folder_phone, order_phone, cust_name in mobile_mismatch:
            print(f"  {rel_path}: receipt {num}, folder phone {folder_phone} != order phone {order_phone} ({cust_name})")
        print()

    if not args.apply:
        print(f"Dry run only — {total_new_photos} photo(s) across {len(attach_existing) + len(create_new)} order(s) would be imported. Re-run with --apply to write them.")
        return

    print(f"Applying: {total_new_photos} photo(s)...")
    imported, failed = 0, []
    today = date.today().isoformat()

    for num, table, order, srcs in attach_existing:
        photos_table = "tailoring_suit_photos" if table == "tailoring_suit_orders" else "tailoring_photos"
        for src_path, rel_path in srcs:
            try:
                image_bytes = pdf_to_jpeg_bytes(src_path, args.dpi)
                filename = f"order{order['id']}-{uuid.uuid4().hex[:10]}.jpg"
                store_image(image_bytes, filename)
                db.execute(
                    f"INSERT INTO {photos_table} (order_id, item_id, filename) VALUES (?, NULL, ?)",
                    (order["id"], filename),
                )
                manifest[rel_path] = {"order_id": order["id"], "table": table, "filename": filename}
                imported += 1
            except Exception as e:
                failed.append((rel_path, str(e)))

    for num, cust_name, cust_phone, srcs in create_new:
        try:
            slip_date = scan_date(srcs[0][0])
            notes = (f"Imported from Drive archive on {today}; scan dated {slip_date}. "
                     f"No item/pricing detail available from the original paper record.")
            cur = db.execute(
                """INSERT INTO tailoring_orders
                   (order_number, order_date, customer_name, mobile, delivered_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (num, slip_date, cust_name, cust_phone, slip_date, notes),
            )
            order_id = cur.lastrowid
            db.execute(
                """INSERT INTO tailoring_items
                   (order_id, garment_type, qty, rate, amount, stage, stitched_at)
                   VALUES (?, '(archived)', 0, 0, 0, 'Delivered', ?)""",
                (order_id, slip_date),
            )
            for src_path, rel_path in srcs:
                image_bytes = pdf_to_jpeg_bytes(src_path, args.dpi)
                filename = f"order{order_id}-{uuid.uuid4().hex[:10]}.jpg"
                store_image(image_bytes, filename)
                db.execute(
                    "INSERT INTO tailoring_photos (order_id, item_id, filename) VALUES (?, NULL, ?)",
                    (order_id, filename),
                )
                manifest[rel_path] = {"order_id": order_id, "table": "tailoring_orders", "filename": filename}
                imported += 1
        except Exception as e:
            failed.append((srcs[0][1], str(e)))

    db.commit()
    save_manifest(root, manifest)

    print(f"Imported {imported} photo(s).")
    if failed:
        print(f"Failed: {len(failed)}")
        for rel_path, err in failed:
            print(f"  {rel_path}: {err}")


if __name__ == "__main__":
    main()
