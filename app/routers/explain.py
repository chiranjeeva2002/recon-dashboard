import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user
from app.llm import explain_discrepancies

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.post("/explain", response_model=schemas.ExplainResponse)
def explain(
    payload: schemas.ExplainRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    discrepancies = (
        db.query(models.Discrepancy)
        .join(models.ReconciliationRun)
        .filter(
            models.Discrepancy.id.in_(payload.discrepancy_ids),
            models.ReconciliationRun.user_id == user.id,
        )
        .all()
    )

    if not discrepancies:
        raise HTTPException(status_code=404, detail="No matching discrepancies found")

    payload_for_llm = [
        {
            "type": d.type,
            "order_id": d.order_id,
            "amount_at_risk": d.amount_at_risk,
            "currency": d.currency,
            "summary": d.summary,
            "details": json.loads(d.details),
        }
        for d in discrepancies
    ]

    result = explain_discrepancies(payload_for_llm)
    explanation_json = result.model_dump_json()

    for d in discrepancies:
        d.explanation = explanation_json
        d.explanation_at = datetime.utcnow()
    db.commit()

    return schemas.ExplainResponse(**result.model_dump())