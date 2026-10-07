import json
import os
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "invoice_runs.db").replace("\\", "/")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class InvoiceRun(Base):
    __tablename__ = "invoice_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    vendor_name = Column(String)
    invoice_number = Column(String)
    po_reference = Column(String)
    po_matched = Column(String)
    invoice_total = Column(Float)
    po_amount = Column(Float)
    variance_pct = Column(Float)
    decision = Column(String)
    reason = Column(Text)
    confidence_score = Column(Integer)
    raw_extracted_json = Column(Text)
    result_json = Column(Text)  # full API response, so /runs/{id} can replay the run

    def to_summary(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() + "Z",
            "vendor_name": self.vendor_name,
            "invoice_number": self.invoice_number,
            "po_reference": self.po_reference,
            "po_matched": self.po_matched,
            "invoice_total": self.invoice_total,
            "po_amount": self.po_amount,
            "variance_pct": self.variance_pct,
            "decision": self.decision,
            "reason": self.reason,
            "confidence_score": self.confidence_score,
        }

    def to_detail(self):
        d = self.to_summary()
        d["extracted_fields"] = json.loads(self.raw_extracted_json or "{}")
        d["result"] = json.loads(self.result_json or "{}")
        return d


def init_db():
    Base.metadata.create_all(engine)


def save_run(**fields) -> InvoiceRun:
    with SessionLocal() as s:
        run = InvoiceRun(**fields)
        s.add(run)
        s.commit()
        s.refresh(run)
        return run


def find_duplicate(vendor_name, invoice_number):
    """Earlier run with the same invoice number from the same vendor (case-insensitive), or None."""
    if not invoice_number:
        return None
    with SessionLocal() as s:
        rows = s.query(InvoiceRun).filter(
            func.lower(func.trim(InvoiceRun.invoice_number)) == invoice_number.strip().lower()
        ).order_by(InvoiceRun.id)
        for r in rows:
            if (r.vendor_name or "").strip().lower() == (vendor_name or "").strip().lower():
                return {"id": r.id, "timestamp": r.timestamp.isoformat()}
    return None


def cumulative_for_po(po_number) -> float:
    """Sum of invoice totals already APPROVED or FLAGGED against this PO."""
    with SessionLocal() as s:
        rows = s.query(InvoiceRun).filter(
            InvoiceRun.po_matched == po_number,
            InvoiceRun.decision.in_(["APPROVED", "FLAG"]),
        ).all()
        return sum(r.invoice_total or 0 for r in rows)


def all_runs():
    with SessionLocal() as s:
        rows = s.query(InvoiceRun).order_by(InvoiceRun.timestamp.desc(), InvoiceRun.id.desc())
        return [r.to_summary() for r in rows]


def get_run(run_id):
    with SessionLocal() as s:
        r = s.get(InvoiceRun, run_id)
        return r.to_detail() if r else None
