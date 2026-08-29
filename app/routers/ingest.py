import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import get_current_user
from app.csv_utils import read_csv_text, normalize_orders, normalize_payments
from app.reconcile import reconcile

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("")
async def ingest(
    orders: UploadFile = File(...),
    payments: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not orders.filename or not orders.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="orders file must be a .csv file")
    if not payments.filename or not payments.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="payments file must be a .csv file")

    try:
        orders_text = (await orders.read()).decode("utf-8-sig")
        payments_text = (await payments.read()).decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Could not read uploaded files as UTF-8 text.")

    try:
        raw_orders = read_csv_text(orders_text)
        raw_payments = read_csv_text(payments_text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}")

    if not raw_orders or not raw_payments:
        raise HTTPException(status_code=400, detail="One of the uploaded files has no data rows.")

    required_order_cols = {"order_id", "currency", "net_amount", "status"}
    required_payment_cols = {"transaction_ref", "order_reference", "amount", "type", "status"}
    if not required_order_cols.issubset(raw_orders[0].keys()):
        raise HTTPException(status_code=400, detail="orders CSV is missing required columns.")
    if not required_payment_cols.issubset(raw_payments[0].keys()):
        raise HTTPException(status_code=400, detail="payments CSV is missing required columns.")

    parsed_orders = normalize_orders(raw_orders)
    parsed_payments = normalize_payments(raw_payments)
    result = reconcile(parsed_orders, parsed_payments)
    s = result["summary"]

    run = models.ReconciliationRun(
        user_id=user.id,
        orders_file_name=orders.filename,
        payments_file_name=payments.filename,
        total_orders=s["total_orders"],
        total_payments=s["total_payments"],
        total_order_value=s["total_order_value"],
        total_payment_value=s["total_payment_value"],
        total_value_reconciled=s["total_value_reconciled"],
        total_value_in_dispute=s["total_value_in_dispute"],
        total_money_at_risk=s["total_money_at_risk"],
    )
    db.add(run)
    db.flush()  # assign run.id without committing yet

    for o in result["orders"]:
        db.add(
            models.OrderRecord(
                run_id=run.id,
                order_id=o["order_id"],
                normalized_id=o["normalized_id"],
                order_date=o["order_date"],
                customer_email=o["customer_email"],
                currency=o["currency"],
                gross_amount=o["gross_amount"],
                discount=o["discount"],
                net_amount=o["net_amount"],
                status=o["status"],
                is_duplicate_row=o["is_duplicate_row"],
            )
        )

    for p in result["payments"]:
        db.add(
            models.PaymentRecord(
                run_id=run.id,
                transaction_ref=p["transaction_ref"],
                processed_at=p["processed_at"],
                order_reference=p["order_reference"],
                normalized_ref=p["normalized_ref"],
                currency=p["currency"],
                amount=p["amount"],
                fee=p["fee"],
                net_settled=p["net_settled"],
                type=p["type"],
                status=p["status"],
            )
        )

    for d in result["discrepancies"]:
        db.add(
            models.Discrepancy(
                run_id=run.id,
                type=d["type"],
                severity=d["severity"],
                order_id=d["order_id"],
                payment_refs=json.dumps(d["payment_refs"]),
                amount_at_risk=d["amount_at_risk"],
                currency=d["currency"],
                summary=d["summary"],
                details=json.dumps(d["details"], default=str),
            )
        )

    db.commit()

    return {"run_id": run.id}