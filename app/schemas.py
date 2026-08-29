from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str


class RunOut(BaseModel):
    id: str
    created_at: datetime
    orders_file_name: str
    payments_file_name: str
    total_orders: int
    total_payments: int
    total_order_value: float
    total_payment_value: float
    total_value_reconciled: float
    total_value_in_dispute: float
    total_money_at_risk: float

    class Config:
        from_attributes = True


class DiscrepancyOut(BaseModel):
    id: str
    type: str
    severity: str
    order_id: Optional[str]
    payment_refs: list[str]
    amount_at_risk: float
    currency: str
    summary: str
    details: dict
    explanation: Optional[dict] = None


class ExplainRequest(BaseModel):
    discrepancy_ids: list[str] = Field(min_length=1, max_length=25)


class ExplainResponse(BaseModel):
    headline: str
    likely_cause: str
    recommended_action: str
    confidence: Literal["low", "medium", "high"]