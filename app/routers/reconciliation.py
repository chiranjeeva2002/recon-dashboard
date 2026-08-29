import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


@router.get("")
def get_reconciliation(
    run_id: str | None = Query(default=None),
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    runs = (
        db.query(models.ReconciliationRun)
        .filter(models.ReconciliationRun.user_id == user.id)
        .order_by(models.ReconciliationRun.created_at.desc())
        .all()
    )

    if not runs:
        return {"runs": [], "run": None, "discrepancies": [], "total": 0, "page": page, "page_size": page_size, "by_type": []}

    run_ids = {r.id for r in runs}
    if not run_id or run_id not in run_ids:
        run = runs[0]
    else:
        run = next(r for r in runs if r.id == run_id)

    query = db.query(models.Discrepancy).filter(models.Discrepancy.run_id == run.id)
    if type:
        query = query.filter(models.Discrepancy.type == type)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                models.Discrepancy.order_id.ilike(like),
                models.Discrepancy.summary.ilike(like),
                models.Discrepancy.payment_refs.ilike(like),
            )
        )

    total = query.count()
    rows = query.all()
    rows.sort(key=lambda d: (_SEVERITY_RANK.get(d.severity, 9), -d.amount_at_risk))
    page_rows = rows[(page - 1) * page_size : (page - 1) * page_size + page_size]

    by_type_query = (
        db.query(
            models.Discrepancy.type,
            func.count(models.Discrepancy.id),
            func.sum(models.Discrepancy.amount_at_risk),
        )
        .filter(models.Discrepancy.run_id == run.id)
        .group_by(models.Discrepancy.type)
        .all()
    )

    def serialize_run(r: models.ReconciliationRun) -> dict:
        return {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "orders_file_name": r.orders_file_name,
            "payments_file_name": r.payments_file_name,
            "total_orders": r.total_orders,
            "total_payments": r.total_payments,
            "total_order_value": r.total_order_value,
            "total_payment_value": r.total_payment_value,
            "total_value_reconciled": r.total_value_reconciled,
            "total_value_in_dispute": r.total_value_in_dispute,
            "total_money_at_risk": r.total_money_at_risk,
        }

    return {
        "runs": [serialize_run(r) for r in runs],
        "run": serialize_run(run),
        "discrepancies": [
            {
                "id": d.id,
                "type": d.type,
                "severity": d.severity,
                "order_id": d.order_id,
                "payment_refs": json.loads(d.payment_refs),
                "amount_at_risk": d.amount_at_risk,
                "currency": d.currency,
                "summary": d.summary,
                "details": json.loads(d.details),
                "explanation": json.loads(d.explanation) if d.explanation else None,
            }
            for d in page_rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "by_type": [{"type": t, "count": c, "amount": a or 0.0} for t, c, a in by_type_query],
    }