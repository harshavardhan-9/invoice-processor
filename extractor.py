import json
import os
import anthropic
import pdfplumber

SYSTEM_PROMPT = (
    "You are an invoice data extractor. Extract the following fields from invoice text and return ONLY "
    "valid JSON with these exact keys: vendor_name, invoice_number, po_reference (null if not found), "
    "line_items (array of {description, quantity, unit_price, amount}), subtotal, tax, total, "
    "due_date (ISO format or null), currency (default USD). If a field cannot be found, use null."
)

def parse_pdf(path: str) -> dict:
    with pdfplumber.open(path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
    if len(text) >= 50:
        return {"text": text, "method": "pdfplumber"}
    import pytesseract
    from pdf2image import convert_from_path
    images = convert_from_path(path)
    text = "\n".join(pytesseract.image_to_string(img) for img in images).strip()
    return {"text": text, "method": "pytesseract OCR"}

def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None

def extract_fields(text: str) -> dict:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = resp.content[0].text
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        raise ValueError("model reply contained no JSON object")
    data = json.loads(raw[start:end + 1])
    for k in ("subtotal", "tax", "total"):
        data[k] = _num(data.get(k))
    data["line_items"] = data.get("line_items") or []
    data["currency"] = data.get("currency") or "USD"
    return data
