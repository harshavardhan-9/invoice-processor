import difflib
import json
import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_pos():
    with open(os.path.join(DATA_DIR, "pos.json")) as f:
        return json.load(f)


def similarity(a, b) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower().strip(), (b or "").lower().strip()).ratio()


def normalize_po(ref) -> str:
    """'po 4471', 'PO-4471 ' and 'PO4471' all become 'PO4471'."""
    return re.sub(r"[^A-Z0-9]", "", (ref or "").upper())


def match_po(vendor_name, po_reference) -> dict:
    """Stage 3: exact PO number first, then fuzzy vendor name (threshold 0.8)."""
    pos = load_pos()

    if normalize_po(po_reference):
        ref = normalize_po(po_reference)
        for po in pos:
            if normalize_po(po["po_number"]) == ref:
                return {"po": po, "match_type": "exact", "match_confidence": 1.0}
        # the invoice names a PO that doesn't exist: don't guess by vendor name
        return {"po": None, "match_type": "none", "match_confidence": 0.0,
                "ref_not_found": po_reference.strip()}

    best, best_score = None, 0.0
    for po in pos:
        score = similarity(vendor_name, po["vendor"])
        if score > best_score:
            best, best_score = po, score
    if best and best_score >= 0.8:
        return {"po": best, "match_type": "fuzzy", "match_confidence": round(best_score, 2)}
    return {"po": None, "match_type": "none", "match_confidence": 0.0}
