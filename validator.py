import json
import os

import database
from matcher import DATA_DIR, similarity

TOLERANCE = 0.05


def validate(extracted: dict, match: dict) -> dict:
    """Stage 4: vendor / PO-vendor / currency / amount / duplicate / cumulative checks."""
    with open(os.path.join(DATA_DIR, "vendors.json")) as f:
        vendors = json.load(f)

    vendor = extracted.get("vendor_name")
    total = extracted.get("total")
    po = match["po"]

    vendor_approved = any(similarity(vendor, v) >= 0.8 for v in vendors)
    vendor_matches_po = bool(po) and similarity(vendor, po["vendor"]) >= 0.8
    currency_matches = bool(po) and (extracted.get("currency") or "USD").upper() == po["currency"].upper()

    variance_pct = None
    amount_in_tolerance = False
    if po and total is not None:
        variance = (total - po["amount"]) / po["amount"]
        variance_pct = round(variance * 100, 2)
        amount_in_tolerance = abs(variance) <= TOLERANCE

    dup = database.find_duplicate(vendor, extracted.get("invoice_number"))

    cumulative_total = None
    cumulative_exceeds = False
    if po and total is not None:
        prior = database.cumulative_for_po(po["po_number"])
        cumulative_total = round(prior + total, 2)
        # only a split-PO problem if earlier invoices exist; a lone overage is the tolerance check's job
        cumulative_exceeds = prior > 0 and cumulative_total > po["amount"]

    return {
        "vendor_approved": vendor_approved,
        "po_matched": po is not None,
        "vendor_matches_po": vendor_matches_po,
        "currency_matches": currency_matches,
        "amount_in_tolerance": amount_in_tolerance,
        "variance_pct": variance_pct,
        "is_duplicate": dup is not None,
        "duplicate_of": dup,
        "cumulative_po_total": cumulative_total,
        "cumulative_exceeds_po": cumulative_exceeds,
    }


def decide(extracted: dict, match: dict, checks: dict) -> dict:
    """Stage 5: first matching rule wins."""
    po = match["po"]
    vendor = extracted.get("vendor_name")
    inv = extracted.get("invoice_number")
    total = extracted.get("total")

    if checks["is_duplicate"]:
        when = checks["duplicate_of"]["timestamp"][:10]
        return {"decision": "REJECT", "confidence_score": 0,
                "reason": f"Duplicate invoice: {inv} from {vendor} was previously submitted on {when}"}
    if not checks["vendor_approved"]:
        return {"decision": "REJECT", "confidence_score": 0,
                "reason": f"Vendor {vendor} is not in the approved vendor list"}
    if match["match_type"] == "none":
        if match.get("ref_not_found"):
            return {"decision": "REJECT", "confidence_score": 0,
                    "reason": f"PO reference {match['ref_not_found']} was not found in PO records"}
        return {"decision": "REJECT", "confidence_score": 0,
                "reason": "No matching PO found for this invoice"}
    if not checks["vendor_matches_po"]:
        return {"decision": "FLAG", "confidence_score": 60,
                "reason": (f"Invoice vendor {vendor} does not match the vendor on {po['po_number']} "
                           f"({po['vendor']}). Manual review required.")}
    if not checks["currency_matches"]:
        return {"decision": "FLAG", "confidence_score": 60,
                "reason": (f"Invoice currency {extracted.get('currency')} differs from PO currency "
                           f"{po['currency']}; amounts cannot be compared. Manual review required.")}
    if total is None:
        return {"decision": "FLAG", "confidence_score": 60,
                "reason": "Invoice total could not be extracted. Flagged for manual review."}
    if checks["cumulative_exceeds_po"]:
        over = checks["cumulative_po_total"] - po["amount"]
        return {"decision": "FLAG", "confidence_score": 70,
                "reason": (f"Cumulative invoices against {po['po_number']} total ${checks['cumulative_po_total']:,.2f}, "
                           f"exceeding PO limit of ${po['amount']:,.2f} by ${over:,.2f}")}
    if not checks["amount_in_tolerance"]:
        v = checks["variance_pct"]
        return {"decision": "FLAG", "confidence_score": 75,
                "reason": (f"Invoice amount ${total:,.2f} is {abs(v):.1f}% {'above' if v > 0 else 'below'} "
                           f"PO amount ${po['amount']:,.2f}, outside ±5% tolerance. Flagged for manual review.")}
    if match["match_type"] == "fuzzy":  # no PO number on the invoice: always needs a human, however good the name match
        return {"decision": "FLAG", "confidence_score": 60,
                "reason": "PO matched by vendor name only (no PO reference found). Manual verification required."}
    return {"decision": "APPROVED", "confidence_score": 100,
            "reason": "Vendor, PO, and amount match within tolerance. Cleared for payment."}
