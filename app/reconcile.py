from collections import defaultdict
from datetime import timedelta, datetime

_EPOCH = datetime(1970, 1, 1)
AMOUNT_TOLERANCE = 0.05
DUPLICATE_CHARGE_WINDOW = timedelta(hours=48)


def _round2(n: float) -> float:
    return round(n + 1e-9, 2)


def reconcile(orders: list[dict], payments: list[dict]) -> dict:
    discrepancies: list[dict] = []

    # De-duplicate exact duplicate order rows (identical export artifact).
    # The first occurrence is kept for matching; totals exclude the repeat.
    deduped_orders = [o for o in orders if not o["is_duplicate_row"]]

    payments_by_order: dict[str, list[dict]] = defaultdict(list)
    for p in payments:
        payments_by_order[p["normalized_ref"]].append(p)

    order_keys = {o["normalized_id"] for o in deduped_orders}

    total_value_reconciled = 0.0
    total_value_in_dispute = 0.0
    total_money_at_risk = 0.0

    def add_discrepancy(**kwargs):
        kwargs["amount_at_risk"] = _round2(kwargs["amount_at_risk"])
        discrepancies.append(kwargs)

    for order in deduped_orders:
        group = payments_by_order.get(order["normalized_id"], [])
        is_cancelled_or_refunded = order["status"] in ("cancelled", "refunded")
        order_has_issue = False

        if not group:
            if order["status"] == "completed":
                add_discrepancy(
                    type="MISSING_PAYMENT",
                    severity="high",
                    order_id=order["order_id"],
                    payment_refs=[],
                    amount_at_risk=order["net_amount"],
                    currency=order["currency"],
                    summary=f"Order {order['order_id']} is marked completed but has no matching payment record.",
                    details={
                        "order_date": order["order_date"].isoformat() if order["order_date"] else None,
                        "net_amount": order["net_amount"],
                        "status": order["status"],
                    },
                )
                total_value_in_dispute += order["net_amount"]
                total_money_at_risk += order["net_amount"]
            continue

        charges = [p for p in group if p["type"] == "charge"]
        refunds = [p for p in group if p["type"] == "refund"]
        settled_charges = [p for p in charges if p["status"] == "settled"]
        pending_charges = [p for p in charges if p["status"] == "pending"]
        failed_charges = [p for p in charges if p["status"] == "failed"]
        settled_refunds = [p for p in refunds if p["status"] == "settled"]

        charged_total = _round2(sum(p["amount"] for p in settled_charges))
        refunded_total = _round2(sum(p["amount"] for p in settled_refunds))
        net_collected = _round2(charged_total - refunded_total)
        duplicate_charge_flagged = False

        # --- Currency mismatch: same numeric amount, different currency code. ---
        currency_mismatches = [p for p in group if p["currency"] != order["currency"]]
        if currency_mismatches:
            order_has_issue = True
            amount = currency_mismatches[0]["amount"]
            add_discrepancy(
                type="CURRENCY_MISMATCH",
                severity="medium",
                order_id=order["order_id"],
                payment_refs=[p["transaction_ref"] for p in currency_mismatches],
                amount_at_risk=amount,
                currency=order["currency"],
                summary=(
                    f"Order {order['order_id']} was placed in {order['currency']} but settled in "
                    f"{currency_mismatches[0]['currency']} for the same numeric amount ({amount})."
                ),
                details={
                    "order_currency": order["currency"],
                    "payment_currency": currency_mismatches[0]["currency"],
                    "amount": amount,
                },
            )
            total_value_in_dispute += amount
            total_money_at_risk += amount

        # --- Duplicate charge: 2+ settled charges, same amount, close in time. ---
        if len(settled_charges) > 1:
            by_amount: dict[float, list[dict]] = defaultdict(list)
            for c in settled_charges:
                by_amount[_round2(c["amount"])].append(c)
            for amount, dup_group in by_amount.items():
                if len(dup_group) < 2:
                    continue
                sorted_group = sorted(
                    dup_group, key=lambda p: p["processed_at"] or _EPOCH
                )
                first, last = sorted_group[0], sorted_group[-1]
                within_window = (
                    not first["processed_at"]
                    or not last["processed_at"]
                    or (last["processed_at"] - first["processed_at"]) <= DUPLICATE_CHARGE_WINDOW
                )
                if within_window:
                    order_has_issue = True
                    duplicate_charge_flagged = True
                    extra_charges = len(sorted_group) - 1
                    at_risk = _round2(amount * extra_charges)
                    add_discrepancy(
                        type="DUPLICATE_CHARGE",
                        severity="high",
                        order_id=order["order_id"],
                        payment_refs=[p["transaction_ref"] for p in sorted_group],
                        amount_at_risk=at_risk,
                        currency=order["currency"],
                        summary=(
                            f"Order {order['order_id']} was charged {len(sorted_group)} times for {amount} "
                            f"within {int(DUPLICATE_CHARGE_WINDOW.total_seconds() // 3600)}h; "
                            "likely a retried or duplicated charge."
                        ),
                        details={
                            "amount": amount,
                            "transaction_refs": [p["transaction_ref"] for p in sorted_group],
                        },
                    )
                    total_value_in_dispute += at_risk
                    total_money_at_risk += at_risk

        # --- Cancelled/refunded order still holding settled charge money. ---
        if is_cancelled_or_refunded:
            outstanding = _round2(charged_total - refunded_total)
            if outstanding > AMOUNT_TOLERANCE:
                order_has_issue = True
                if refunded_total <= AMOUNT_TOLERANCE:
                    add_discrepancy(
                        type="CHARGE_ON_CANCELLED_ORDER",
                        severity="high",
                        order_id=order["order_id"],
                        payment_refs=[p["transaction_ref"] for p in charges],
                        amount_at_risk=outstanding,
                        currency=order["currency"],
                        summary=(
                            f"Order {order['order_id']} is {order['status']} but the customer was charged "
                            f"{charged_total} and never refunded."
                        ),
                        details={
                            "charged_total": charged_total,
                            "refunded_total": refunded_total,
                            "order_status": order["status"],
                        },
                    )
                else:
                    add_discrepancy(
                        type="PARTIAL_REFUND_SHORTFALL",
                        severity="medium",
                        order_id=order["order_id"],
                        payment_refs=[p["transaction_ref"] for p in group],
                        amount_at_risk=outstanding,
                        currency=order["currency"],
                        summary=(
                            f"Order {order['order_id']} is marked {order['status']}, but only {refunded_total} of "
                            f"the {charged_total} charged has been refunded ({outstanding} short)."
                        ),
                        details={
                            "charged_total": charged_total,
                            "refunded_total": refunded_total,
                            "order_status": order["status"],
                        },
                    )
                total_value_in_dispute += outstanding
                total_money_at_risk += outstanding

        # --- Order still marked completed, but money was (partly) refunded. ---
        # Distinct from the cancelled/refunded branch above: here the order
        # system's status was never updated to reflect the refund, which is
        # itself the discrepancy worth surfacing (status out of sync with
        # payment reality), separate from the cancelled/refunded case.
        refund_on_completed_flagged = False
        if not is_cancelled_or_refunded and refunded_total > AMOUNT_TOLERANCE:
            order_has_issue = True
            refund_on_completed_flagged = True
            fully_refunded = refunded_total >= charged_total - AMOUNT_TOLERANCE
            add_discrepancy(
                type="REFUND_ON_COMPLETED_ORDER",
                severity="high" if fully_refunded else "medium",
                order_id=order["order_id"],
                payment_refs=[p["transaction_ref"] for p in group],
                amount_at_risk=refunded_total,
                currency=order["currency"],
                summary=(
                    f"Order {order['order_id']} is still marked {order['status']}, but "
                    f"{refunded_total} of the {charged_total} charged has since been refunded. "
                    "The order status was never updated to reflect this."
                ),
                details={
                    "charged_total": charged_total,
                    "refunded_total": refunded_total,
                    "order_status": order["status"],
                    "fully_refunded": fully_refunded,
                },
            )
            total_value_in_dispute += refunded_total
            total_money_at_risk += refunded_total if fully_refunded else 0

        # --- Completed order, but the money isn't actually settled. ---
        if order["status"] == "completed":
            if not settled_charges and pending_charges:
                order_has_issue = True
                amount = pending_charges[0]["amount"]
                add_discrepancy(
                    type="UNSETTLED_PAYMENT",
                    severity="medium",
                    order_id=order["order_id"],
                    payment_refs=[p["transaction_ref"] for p in pending_charges],
                    amount_at_risk=amount,
                    currency=order["currency"],
                    summary=f"Order {order['order_id']} is marked completed but its payment is still pending settlement.",
                    details={"pending_amount": amount},
                )
                total_value_in_dispute += amount
                total_money_at_risk += amount
            elif not settled_charges and failed_charges:
                order_has_issue = True
                amount = order["net_amount"]
                add_discrepancy(
                    type="FAILED_PAYMENT_ON_COMPLETED_ORDER",
                    severity="high",
                    order_id=order["order_id"],
                    payment_refs=[p["transaction_ref"] for p in failed_charges],
                    amount_at_risk=amount,
                    currency=order["currency"],
                    summary=(
                        f"Order {order['order_id']} is marked completed, but its only payment attempt failed. "
                        "No money was actually collected."
                    ),
                    details={"failed_amount": amount},
                )
                total_value_in_dispute += amount
                total_money_at_risk += amount

        # --- Amount mismatch: what we collected doesn't match what the order says. ---
        # Skipped when a duplicate charge or a refund already explains the gap
        # between order value and money collected - those are more specific,
        # more useful classifications of the same underlying number and we
        # don't want to double-count the same dollars under two types.
        if (
            not is_cancelled_or_refunded
            and settled_charges
            and not currency_mismatches
            and not duplicate_charge_flagged
            and not refund_on_completed_flagged
        ):
            diff = _round2(order["net_amount"] - net_collected)
            if abs(diff) > AMOUNT_TOLERANCE:
                order_has_issue = True
                severity = "high" if abs(diff) >= 20 else "medium"
                if diff > 0:
                    summary = (
                        f"Order {order['order_id']} expected {order['net_amount']} but only {net_collected} "
                        f"was collected (undercharged by {abs(diff)})."
                    )
                else:
                    summary = (
                        f"Order {order['order_id']} expected {order['net_amount']} but {net_collected} was "
                        f"collected (overcharged by {abs(diff)})."
                    )
                add_discrepancy(
                    type="AMOUNT_MISMATCH",
                    severity=severity,
                    order_id=order["order_id"],
                    payment_refs=[p["transaction_ref"] for p in group],
                    amount_at_risk=abs(diff),
                    currency=order["currency"],
                    summary=summary,
                    details={"expected": order["net_amount"], "collected": net_collected, "diff": diff},
                )
                total_value_in_dispute += abs(diff)
                # overcharges are a customer-service risk, not lost revenue
                total_money_at_risk += diff if diff > 0 else 0

        if not order_has_issue:
            total_value_reconciled += order["net_amount"]

    # --- Orphan payments: money moved, but no order exists for it. ---
    for key, group in payments_by_order.items():
        if key in order_keys:
            continue
        settled_orphan_charges = [p for p in group if p["type"] == "charge" and p["status"] == "settled"]
        if not settled_orphan_charges:
            continue
        amount = _round2(sum(p["amount"] for p in settled_orphan_charges))
        add_discrepancy(
            type="ORPHAN_PAYMENT",
            severity="medium",
            order_id=None,
            payment_refs=[p["transaction_ref"] for p in group],
            amount_at_risk=amount,
            currency=settled_orphan_charges[0]["currency"],
            summary=(
                f'Payment(s) referencing "{group[0]["order_reference"]}" were settled, but no such order '
                "exists in the order system."
            ),
            details={"order_reference": group[0]["order_reference"], "amount": amount},
        )
        total_value_in_dispute += amount
        total_money_at_risk += amount

    total_order_value = _round2(sum(o["net_amount"] for o in deduped_orders))
    total_payment_value = _round2(
        sum(p["amount"] for p in payments if p["type"] == "charge" and p["status"] == "settled")
        - sum(p["amount"] for p in payments if p["type"] == "refund" and p["status"] == "settled")
    )

    by_type: dict[str, dict] = {}
    for d in discrepancies:
        entry = by_type.setdefault(d["type"], {"count": 0, "amount": 0.0})
        entry["count"] += 1
        entry["amount"] = _round2(entry["amount"] + d["amount_at_risk"])

    summary = {
        "total_orders": len(deduped_orders),
        "total_payments": len(payments),
        "total_order_value": total_order_value,
        "total_payment_value": total_payment_value,
        "total_value_reconciled": _round2(total_value_reconciled),
        "total_value_in_dispute": _round2(total_value_in_dispute),
        "total_money_at_risk": _round2(total_money_at_risk),
        "by_type": by_type,
    }

    return {
        "orders": deduped_orders,
        "payments": payments,
        "discrepancies": discrepancies,
        "summary": summary,
    }