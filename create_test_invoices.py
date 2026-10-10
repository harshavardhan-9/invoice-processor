"""Generates the 5 sample invoice PDFs into data/invoices/."""
import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "invoices")

INVOICES = [
    ("happy_path.pdf", "INV-20831", "PO-4471", 48250.00),
    ("over_tolerance.pdf", "INV-20832", "PO-4471", 51000.00),
    ("duplicate.pdf", "INV-20831", "PO-4471", 48250.00),
    ("missing_po.pdf", "INV-20833", None, 48250.00),
    ("split_po_second.pdf", "INV-20834", "PO-4471", 25000.00),
]


def make_invoice(filename, number, po, total):
    c = canvas.Canvas(os.path.join(OUT, filename), pagesize=letter)
    w, h = letter

    c.setFont("Helvetica-Bold", 22)
    c.drawString(50, h - 60, "INVOICE")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, h - 90, "Northwind Traders")
    c.setFont("Helvetica", 10)
    c.drawString(50, h - 105, "1200 Commerce Way, Seattle, WA 98101")

    c.setFont("Helvetica", 11)
    c.drawString(350, h - 60, f"Invoice Number: {number}")
    c.drawString(350, h - 76, "Invoice Date: 2026-10-01")
    c.drawString(350, h - 92, "Due Date: 2026-10-31")
    if po:
        c.drawString(350, h - 108, f"PO Reference: {po}")

    c.drawString(50, h - 145, "Bill To: Acme Corp Accounts Payable")

    y = h - 190
    c.setFont("Helvetica-Bold", 10)
    for x, t in [(50, "Description"), (300, "Qty"), (360, "Unit Price"), (460, "Amount")]:
        c.drawString(x, y, t)
    c.line(50, y - 4, 560, y - 4)

    # two line items that sum to the total
    first = round(total * 0.6, 2)
    second = round(total - first, 2)
    c.setFont("Helvetica", 10)
    rows = [("Office supplies - bulk order", 1, first), ("Furniture and equipment", 1, second)]
    y -= 22
    for desc, qty, amt in rows:
        c.drawString(50, y, desc)
        c.drawString(300, y, str(qty))
        c.drawString(360, y, f"${amt:,.2f}")
        c.drawString(460, y, f"${amt:,.2f}")
        y -= 18

    y -= 20
    c.drawString(360, y, "Subtotal:")
    c.drawString(460, y, f"${total:,.2f}")
    c.drawString(360, y - 16, "Tax:")
    c.drawString(460, y - 16, "$0.00")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(360, y - 36, "TOTAL DUE:")
    c.drawString(460, y - 36, f"${total:,.2f}")

    c.setFont("Helvetica", 9)
    c.drawString(50, 60, "Payment terms: Net 30. Currency: USD. Thank you for your business.")
    c.save()


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for args in INVOICES:
        make_invoice(*args)
        print("created", args[0])
