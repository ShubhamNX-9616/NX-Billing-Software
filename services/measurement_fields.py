"""Garment measurement field definitions for the Measurements trial.

One place that says which fields each garment has, so the form, the API
validation and the print slip all agree. Ported from the standalone tailor app.

Field kinds:
  count   — how many pieces (free text, small)
  inch    — a measurement in inches (free text: "42", "40.5", "40 1/2")
  select  — one of a fixed list of options
"""

STATUSES = ["Measured", "In Stitching", "Trial Ready", "Delivered"]
DEFAULT_STATUS = STATUSES[0]

YES_NO = ["Yes", "No"]


def _key(label):
    return label.lower().replace("-", "_").replace(" ", "_")


def _f(label, kind="inch", options=None):
    field = {"key": _key(label), "label": label, "kind": kind}
    if options:
        field["options"] = options
    return field


def _inches(*labels):
    return [_f(label) for label in labels]


SHIRT_FIELDS = (
    [_f("No of Shirts", "count"),
     _f("Shirt Type", "select", ["Manela", "Apple-cut", "Manela-sidecut"])]
    + _inches("Length", "Chest", "Stomach", "Seat", "Shoulder", "Sleeve Length",
              "Arm Hole", "Elbow", "Cuff", "Neck", "Collar", "X-Chest",
              "Front 1", "Front 2", "Front 3", "Back 1", "Back 2", "Back 3")
    + [_f("Front-patti", "select", ["Plain", "Box"]),
       _f("Collar Type", "select",
          ["Button-down", "Club", "Spread", "Point"]),
       _f("Cuff Type", "select",
          ["Angled", "Rounded", "Square", "French", "Rounded French",
           "Double French", "Double Rounded French"]),
       _f("Sample Shirt", "select", YES_NO)]
)

PANT_FIELDS = (
    [_f("No of Pants", "count")]
    + _inches("Length", "Waist", "Seat", "Seat Front", "Seat Back", "Thighs")
    + [_f("Thighs Type", "select", ["Loose", "Fitting"])]
    + _inches("Knee", "Knee Height", "Calf", "Bottom", "Ring", "Front Fork", "Back Fork")
    + [_f("Plates", "select", ["Plates", "Without Plates"]),
       _f("Belt", "select", ["Long Belt", "Cut Belt"]),
       _f("Button", "select", ["Hook", "Button"]),
       _f("Sample Pant", "select", YES_NO)]
)

KURTA_FIELDS = (
    [_f("No of Kurtas", "count"),
     _f("Kurta Type", "select", ["Normal", "Short", "Front Open", "Pathani"])]
    + _inches("Length", "Chest", "Stomach", "Seat", "Shoulder", "Sleeve Length",
              "Arm Hole", "Elbow", "Cuff")
    + [_f("Cuff Style", "select", ["Cuff", "Round (No Cuff)"])]
    + _inches("Neck", "Collar", "X-Chest", "Front 1", "Front 2", "Front 3", "Front 4",
              "Back 1", "Back 2", "Back 3")
    + [_f("Pockets", "select", ["Side Pockets", "No Pockets"]),
       _f("Astar", "select", YES_NO),
       _f("Collar Type", "select", ["Stand Collar"]),
       _f("Sample Kurta", "select", YES_NO)]
)

SUIT_FIELDS = (
    [_f("No of Suits", "count")]
    + _inches("Length", "Chest", "Stomach", "Seat", "Shoulder", "Sleeve Length",
              "Arms", "Neck")
)

JACKET_FIELDS = (
    [_f("No of Jackets", "count")]
    + _inches("Length", "Chest", "Stomach", "Seat", "Shoulder", "Sleeve Length",
              "Arms", "Neck")
)

PYJAMA_FIELDS = (
    [_f("No of Pyjamas", "count")]
    + _inches("Length", "Waist", "Seat", "Thighs", "Knee", "Bottom", "Ring")
)

GARMENTS = {
    "shirt":  {"label": "Shirt",  "fields": SHIRT_FIELDS},
    "pant":   {"label": "Pant",   "fields": PANT_FIELDS},
    "kurta":  {"label": "Kurta",  "fields": KURTA_FIELDS},
    "suit":   {"label": "Suit",   "fields": SUIT_FIELDS},
    "jacket": {"label": "Jacket", "fields": JACKET_FIELDS},
    "pyjama": {"label": "Pyjama", "fields": PYJAMA_FIELDS},
}

MAX_VALUE_LEN = 40


def clean_values(garment_type, raw):
    """Keep only the known fields of this garment, trimmed. Select fields must
    hold one of their options (anything else is dropped). Returns
    (values, error); error is None when everything was acceptable."""
    garment = GARMENTS.get(garment_type)
    if not garment:
        return None, "Unknown garment type"
    if not isinstance(raw, dict):
        return None, "Measurements must be an object"
    values = {}
    for field in garment["fields"]:
        v = raw.get(field["key"])
        if v is None:
            continue
        v = str(v).strip()
        if not v:
            continue
        if len(v) > MAX_VALUE_LEN:
            return None, f"{field['label']} is too long"
        if field["kind"] == "select" and v not in field["options"]:
            return None, f"Invalid option for {field['label']}"
        values[field["key"]] = v
    return values, None
