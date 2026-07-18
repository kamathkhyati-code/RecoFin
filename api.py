import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse

from datagents.agents.ingestion_agent import ingest_sources
from datagents.agents.normalization_agent import normalize_transactions
from datagents.agents.validation_agent import validate_transactions
from datagents.schemas import SourceConfig, SourceType
from reasoning.agents.matching_agent import run_matching

app = FastAPI(title="RecoFin Reconciliation API")

ROOT = Path(__file__).parent
SAMPLE = ROOT / "sample_data"
STATIC = ROOT / "static"
BANK_FIELD_MAP = {"transaction_id": "txn_id", "value_date": "date", "ccy": "currency"}


def _txn_dict(t):
    return {
        "txn_id": t.txn_id,
        "date": t.date.isoformat(),
        "amount": str(t.amount),
        "currency": t.currency.value,
        "counterparty": t.counterparty,
        "reference": t.reference,
    }


def _save_upload(upload: UploadFile, dest: Path) -> Path:
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reconcile")
async def reconcile(
    book_file: UploadFile | None = File(None),
    bank_file: UploadFile | None = File(None),
):
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)

        if book_file is not None and book_file.filename:
            book_path = _save_upload(book_file, tmp / "book.csv")
        else:
            book_path = SAMPLE / "demo_book.csv"

        if bank_file is not None and bank_file.filename:
            bank_path = _save_upload(bank_file, tmp / "bank.csv")
        else:
            bank_path = SAMPLE / "demo_bank.csv"

        book_res = ingest_sources([
            SourceConfig(name="book", source_type=SourceType.CSV, location=str(book_path)),
        ])
        bank_res = ingest_sources([
            SourceConfig(
                name="bank", source_type=SourceType.CSV, location=str(bank_path),
                options={"field_map": BANK_FIELD_MAP},
            ),
        ])

    findings = validate_transactions(book_res.transactions + bank_res.transactions)
    book_norm = normalize_transactions(book_res.transactions)
    bank_norm = normalize_transactions(bank_res.transactions)
    matches, un_book, un_bank = run_matching(book_norm, bank_norm)

    book_by_id = {t.txn_id: t for t in book_norm}
    total = len(book_norm) or 1
    rate = len(matches) / total * 100
    rejected = len(book_res.issues) + len(bank_res.issues)

    return {
        "summary": {
            "match_rate": round(rate, 1),
            "matched": len(matches),
            "unmatched": len(un_book) + len(un_bank),
            "bad_rows_rejected": rejected,
        },
        "matches": [
            {
                "book_id": m.book_txn_id,
                "bank_id": m.source_txn_id,
                "amount_usd": str(book_by_id[m.book_txn_id].amount),
                "counterparty": book_by_id[m.book_txn_id].counterparty,
                "date": book_by_id[m.book_txn_id].date.isoformat(),
                "match_type": m.match_type.value,
                "confidence": m.confidence,
            }
            for m in matches
        ],
        "unmatched": [_txn_dict(t) for t in (un_book + un_bank)],
        "book_raw": [_txn_dict(t) for t in book_res.transactions],
        "book_normalized": [_txn_dict(t) for t in book_norm],
        "bank_raw": [_txn_dict(t) for t in bank_res.transactions],
        "validation_findings": [
            {"txn_id": f.txn_id, "reason": f.reason.value, "escalate": f.escalate}
            for f in findings
        ],
    }
