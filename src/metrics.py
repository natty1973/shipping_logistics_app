from __future__ import annotations

import pandas as pd


def get_total_shipments(shipments: pd.DataFrame) -> int:
    """
    Count total shipment records.
    """
    return len(shipments)


def get_total_customers(customers: pd.DataFrame) -> int:
    """
    Count total customer records.
    """
    return len(customers)


def get_pending_pickups(pickups: pd.DataFrame) -> int:
    """
    Count pickups that are pending, scheduled, or rescheduled.
    """
    if pickups.empty or "pickup_status" not in pickups.columns:
        return 0

    pending_statuses = ["Pending", "Scheduled", "Rescheduled"]

    return int(pickups["pickup_status"].isin(pending_statuses).sum())


def get_in_transit_shipments(shipments: pd.DataFrame) -> int:
    """
    Count shipments currently in transit.
    """
    if shipments.empty or "current_status" not in shipments.columns:
        return 0

    return int(shipments["current_status"].eq("In Transit").sum())


def get_delivered_shipments(shipments: pd.DataFrame) -> int:
    """
    Count delivered shipments.
    """
    if shipments.empty or "current_status" not in shipments.columns:
        return 0

    return int(shipments["current_status"].eq("Delivered").sum())


def get_total_revenue_collected(payments: pd.DataFrame) -> float:
    """
    Sum all payments collected.
    """
    if payments.empty or "amount_paid" not in payments.columns:
        return 0.0

    return float(payments["amount_paid"].fillna(0).sum())


def get_total_outstanding_balance(payments: pd.DataFrame) -> float:
    """
    Sum all outstanding balances.
    """
    if payments.empty or "balance_due" not in payments.columns:
        return 0.0

    return float(payments["balance_due"].fillna(0).sum())


def get_total_amount_charged(payments: pd.DataFrame) -> float:
    """
    Sum all amounts charged.
    """
    if payments.empty or "amount_charged" not in payments.columns:
        return 0.0

    return float(payments["amount_charged"].fillna(0).sum())