import json
import os
import shutil
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

import database
from extractor import extract_fields, parse_pdf
from matcher import match_po
from validator import decide, validate

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Invoice Processor")
database.init_db()


def log(msg: str):
    print(f"[pipeline] {msg}", flush=True)


@app.post("/process")
async def process(invoice: UploadFile = File(...)):
    if not (invoice.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file")

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(invoice.file, f)

    stages = []
    try:
        log(f"Received {invoice.filename}")

        # Stage 1 - PDF parsing
        log("Stage 1/5: parsing PDF...")
        try:
            parsed = parse_pdf(tmp_path)
        except Exception as e:
            raise HTTPException(422, f"Could not read PDF: {e}")
        if not parsed["text"].strip():
            raise HTTPException(422, "No text could be extracted from this PDF")
        stages.append({"name": "PDF Parsed", "status": "done",
                       "output": f"{len(parsed['text'])} characters extracted via {parsed['method']}"})
        log(f"  -> {len(parsed['text'])} chars via {parsed['method']}")

        # Stage 2 - LLM extraction
        log("Stage 2/5: extracting fields with Claude Haiku...")
        try:
            extracted = extract_fields(parsed["text"])
        except Exception as e:
            raise HTTPException(502, f"LLM extraction failed: {e}")
        stages.append({"name": "Fields Extracted", "status": "done",
                       "output": f"{extracted.get('vendor_name')} / {extracted.get('invoice_number')} / "
                                 f"total {extracted.get('total')}"})
        log(f"  -> {extracted.get('vendor_name')} {extracted.get('invoice_number')} total={extracted.get('total')}")

        # Stage 3 - PO matching
        log("Stage 3/5: matching PO...")
        match = match_po(extracted.get("vendor_name"), extracted.get("po_reference"))
        po = match["po"]
        if po:
            out = f"{po['po_number']} ({match['match_type']} match, {match['match_confidence']:.0%} confidence)"
            status = "done" if match["match_type"] == "exact" else "flagged"
        else:
            out = (f"PO reference {match['ref_not_found']} not found" if match.get("ref_not_found")
                   else "No matching PO found")
            status = "rejected"
        stages.append({"name": "PO Matched", "status": status, "output": out})
        log(f"  -> {out}")

        # Stage 4 - validation
        log("Stage 4/5: validating...")
        checks = validate(extracted, match)
        failed = [k for k, ok in [("vendor", checks["vendor_approved"]),
                                  ("vendor/PO", checks["vendor_matches_po"]),
                                  ("currency", checks["currency_matches"]),
                                  ("amount", checks["amount_in_tolerance"]),
                                  ("duplicate", not checks["is_duplicate"]),
                                  ("cumulative", not checks["cumulative_exceeds_po"])] if not ok]
        stages.append({"name": "Validation Complete",
                       "status": "done" if not failed else "flagged",
                       "output": "All checks passed" if not failed else "Failed: " + ", ".join(failed)})
        log(f"  -> failed checks: {failed or 'none'}")

        # Stage 5 - decision
        log("Stage 5/5: making decision...")
        result = decide(extracted, match, checks)
        d = result["decision"]
        stages.append({"name": "Decision Made",
                       "status": {"APPROVED": "done", "FLAG": "flagged", "REJECT": "rejected"}[d],
                       "output": f"{d} ({result['confidence_score']}% confidence)"})
        log(f"  -> {d}: {result['reason']}")

        response = {
            "decision": d,
            "reason": result["reason"],
            "confidence_score": result["confidence_score"],
            "extracted_fields": extracted,
            "matched_po": po,
            "match_type": match["match_type"],
            "match_confidence": match["match_confidence"],
            "validation_checks": checks,
            "processing_stages": stages,
            "filename": invoice.filename,
        }
        run = database.save_run(
            vendor_name=extracted.get("vendor_name"),
            invoice_number=extracted.get("invoice_number"),
            po_reference=extracted.get("po_reference"),
            po_matched=po["po_number"] if po else None,
            invoice_total=extracted.get("total"),
            po_amount=po["amount"] if po else None,
            variance_pct=checks["variance_pct"],
            decision=d,
            reason=result["reason"],
            confidence_score=result["confidence_score"],
            raw_extracted_json=json.dumps(extracted),
            result_json=json.dumps(response),
        )
        response["run_id"] = run.id
        log(f"Saved as run #{run.id}")
        return response
    finally:
        os.remove(tmp_path)


@app.get("/runs")
def runs():
    rows = database.all_runs()
    return {
        "runs": rows,
        "summary": {
            "total": len(rows),
            "approved_count": sum(r["decision"] == "APPROVED" for r in rows),
            "flagged_count": sum(r["decision"] == "FLAG" for r in rows),
            "rejected_count": sum(r["decision"] == "REJECT" for r in rows),
        },
    }


@app.get("/runs/{run_id}")
def run_detail(run_id: int):
    run = database.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))
