# Invoice Processor — PDF to Decision

Upload a vendor invoice PDF and the app runs it through a 5-stage pipeline (parse → Claude Haiku extraction → PO match → 3-way validation → decision), showing each stage live. It returns APPROVED / FLAG / REJECT with a plain-English reason, a confidence score, and a stored audit trail.

## How to run

1. Clone / open the folder.
2. `pip install -r requirements.txt` (the OCR fallback for scanned PDFs additionally needs the Tesseract and Poppler binaries on PATH; clean PDFs don't).
3. Set your key: PowerShell `$env:ANTHROPIC_API_KEY="sk-ant-..."` / bash `export ANTHROPIC_API_KEY=sk-ant-...`
4. `python create_test_invoices.py` (generates sample PDFs in `data/invoices/`), then `uvicorn main:app --reload`
5. Open http://localhost:8000

## What the pipeline checks

Rules are applied in priority order; the first match wins.

| # | Rule | Decision |
|---|---|---|
| 1 | Same vendor + invoice number already processed (case-insensitive) | REJECT |
| 2 | Vendor not on the approved list | REJECT |
| 3 | No PO found, or the invoice cites a PO number that doesn't exist | REJECT |
| 4 | Invoice vendor doesn't match the matched PO's vendor | FLAG |
| 5 | Invoice currency differs from the PO currency | FLAG |
| 6 | Total could not be extracted | FLAG |
| 7 | Earlier invoices exist on the PO and the running total exceeds it | FLAG |
| 8 | Total outside ±5% of the PO amount | FLAG |
| 9 | PO matched by vendor name only (no PO number on the invoice) | FLAG |
| 10 | Everything passes | APPROVED |

PO references are normalized before matching (`po 4471`, `PO4471` and `PO-4471` are the same PO). Bad or empty PDFs return a clear 422; LLM failures return a 502.

## Testing the edge cases

Cumulative tracking means earlier runs affect later ones. To reset, stop the server and delete `invoice_runs.db`. Three takes:

**Take A: one database, in this order**

| Order | PDF | Expected | Why |
|---|---|---|---|
| 1 | `happy_path.pdf` | APPROVED | INV-20831, PO-4471, $48,250 = PO. Books $48,250 on the PO |
| 2 | `split_po_second.pdf` | FLAG (EC-4) | $25K on top of $48,250: cumulative $73,250 exceeds the PO |
| 3 | `duplicate.pdf` | REJECT (EC-2) | INV-20831 already processed |

**Take B: reset, then run alone.** `over_tolerance.pdf` → FLAG (EC-1), $51,000 is +5.7% over the PO.

**Take C: reset, then run alone.** `missing_po.pdf` → FLAG at 60% (EC-3), no PO number, matched by vendor name only.

Takes B and C need a fresh database. With earlier invoices on PO-4471, the cumulative rule would fire first and hide the reason you want to show.

## Known limitation: partial billing

Tolerance compares the invoice total with the full PO amount, not the remaining balance. A legitimate $25K partial invoice on a $48,250 PO flags because it is 48% below the PO. A human reviewer would approve it; a production version would compare against the remaining balance. This is a deliberate tradeoff: false positives are safer than false negatives in AP workflows.

Other limits: the UI's stage animation is paced after the response returns (the pipeline itself runs for real), and failed runs (e.g. an LLM outage) are not saved to history.

## Key choices

Claude Haiku because invoice formats vary too much for regex, while all decisions stay in deterministic Python rules; ±5% tolerance as a standard AP window; split-PO tracking sums every APPROVED and FLAG invoice already stored against a PO and adds the current one.

## What I'd build next

Remaining-balance tolerance for partial billing, email alerts on FLAG/REJECT, multi-currency conversion, vendor onboarding API, bulk upload, human approve/override with a user-action audit log, Postgres with a unique constraint on vendor + invoice number.
