import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    Integer,
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    runs = relationship("ReconciliationRun", back_populates="user", cascade="all, delete-orphan")


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders_file_name = Column(String, nullable=False)
    payments_file_name = Column(String, nullable=False)

    total_orders = Column(Integer, nullable=False)
    total_payments = Column(Integer, nullable=False)
    total_order_value = Column(Float, nullable=False)
    total_payment_value = Column(Float, nullable=False)
    total_value_reconciled = Column(Float, nullable=False)
    total_value_in_dispute = Column(Float, nullable=False)
    total_money_at_risk = Column(Float, nullable=False)

    user = relationship("User", back_populates="runs")
    orders = relationship("OrderRecord", back_populates="run", cascade="all, delete-orphan")
    payments = relationship("PaymentRecord", back_populates="run", cascade="all, delete-orphan")
    discrepancies = relationship("Discrepancy", back_populates="run", cascade="all, delete-orphan")


class OrderRecord(Base):
    __tablename__ = "order_records"

    id = Column(String, primary_key=True, default=gen_id)
    run_id = Column(String, ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    order_id = Column(String, nullable=False)
    normalized_id = Column(String, nullable=False, index=True)
    order_date = Column(DateTime, nullable=True)
    customer_email = Column(String, nullable=True)
    currency = Column(String, nullable=False)
    gross_amount = Column(Float, nullable=False)
    discount = Column(Float, nullable=False)
    net_amount = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    is_duplicate_row = Column(Boolean, default=False)

    run = relationship("ReconciliationRun", back_populates="orders")


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id = Column(String, primary_key=True, default=gen_id)
    run_id = Column(String, ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    transaction_ref = Column(String, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    order_reference = Column(String, nullable=False)
    normalized_ref = Column(String, nullable=False, index=True)
    currency = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)
    net_settled = Column(Float, nullable=False)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False)

    run = relationship("ReconciliationRun", back_populates="payments")


class Discrepancy(Base):
    __tablename__ = "discrepancies"

    id = Column(String, primary_key=True, default=gen_id)
    run_id = Column(String, ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    type = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False)
    order_id = Column(String, nullable=True)
    payment_refs = Column(Text, nullable=False)  # JSON-encoded list
    amount_at_risk = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    details = Column(Text, nullable=False)  # JSON-encoded dict
    explanation = Column(Text, nullable=True)  # JSON-encoded ExplanationResult
    explanation_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("ReconciliationRun", back_populates="discrepancies")