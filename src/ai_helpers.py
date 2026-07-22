from __future__ import annotations

import pandas as pd


def generate_weekly_summary(
    customers: pd.DataFrame,
    shipments: pd.DataFrame,
    pickups: pd.DataFrame,
    payments: pd.DataFrame,
) -> str:
    """
    Generate a simple operations summary from the current CSV data.
    This is rule-based and does not require an external AI API.
    """

    total_customers = len(customers)
    total_shipments = len(shipments)
    total_pickups = len(pickups)

    total_paid = (
        payments["amount_paid"].fillna(0).sum()
        if "amount_paid" in payments.columns
        else 0
    )

    total_balance = (
        payments["balance_due"].fillna(0).sum()
        if "balance_due" in payments.columns
        else 0
    )

    pending_pickups = 0
    if "pickup_status" in pickups.columns:
        pending_pickups = int(
            pickups["pickup_status"]
            .isin(["Pending", "Scheduled", "Rescheduled"])
            .sum()
        )

    in_transit = 0
    delivered = 0
    if "current_status" in shipments.columns:
        in_transit = int(shipments["current_status"].eq("In Transit").sum())
        delivered = int(shipments["current_status"].eq("Delivered").sum())

    top_destination = "not available"
    if "destination_country" in shipments.columns and not shipments.empty:
        top_destination = shipments["destination_country"].mode().iloc[0]

    return (
        f"This week, Solomon Shipping recorded {total_shipments} shipments "
        f"across {total_customers} customers, with {total_pickups} pickup records. "
        f"The most common destination is {top_destination}. "
        f"There are {in_transit} shipments currently in transit and {delivered} delivered shipments. "
        f"The team has {pending_pickups} pickups still pending, scheduled, or rescheduled. "
        f"Payments collected total ${total_paid:,.2f}, with ${total_balance:,.2f} still outstanding."
    )


def get_unpaid_or_partial_payments(payments: pd.DataFrame) -> pd.DataFrame:
    """
    Return payment records where money is still owed.
    """
    if payments.empty or "balance_due" not in payments.columns:
        return pd.DataFrame()

    return payments[payments["balance_due"].fillna(0) > 0].copy()


def get_pending_pickups(pickups: pd.DataFrame) -> pd.DataFrame:
    """
    Return pickup records that still need attention.
    """
    if pickups.empty or "pickup_status" not in pickups.columns:
        return pd.DataFrame()

    return pickups[
        pickups["pickup_status"].isin(["Pending", "Scheduled", "Rescheduled"])
    ].copy()


def get_in_transit_shipments(shipments: pd.DataFrame) -> pd.DataFrame:
    """
    Return shipments currently in transit.
    """
    if shipments.empty or "current_status" not in shipments.columns:
        return pd.DataFrame()

    return shipments[shipments["current_status"].eq("In Transit")].copy()


def get_delivered_shipments(shipments: pd.DataFrame) -> pd.DataFrame:
    """
    Return delivered shipments.
    """
    if shipments.empty or "current_status" not in shipments.columns:
        return pd.DataFrame()

    return shipments[shipments["current_status"].eq("Delivered")].copy()


def get_shipments_by_destination(
    shipments: pd.DataFrame,
    destination: str,
) -> pd.DataFrame:
    """
    Return shipments going to a selected country or city.
    """
    if shipments.empty:
        return pd.DataFrame()

    destination = destination.lower().strip()

    country_match = pd.Series(False, index=shipments.index)
    city_match = pd.Series(False, index=shipments.index)

    if "destination_country" in shipments.columns:
        country_match = shipments["destination_country"].astype(str).str.lower().eq(destination)

    if "destination_city" in shipments.columns:
        city_match = shipments["destination_city"].astype(str).str.lower().eq(destination)

    return shipments[country_match | city_match].copy()


def get_delivery_issues(shipments: pd.DataFrame) -> pd.DataFrame:
    """
    Return shipments that may need delivery follow-up.
    Uses current_status for now. If delivery_status is added later,
    this can be expanded.
    """
    if shipments.empty or "current_status" not in shipments.columns:
        return pd.DataFrame()

    issue_statuses = [
        "On Hold",
        "Delayed",
        "Delivery Attempted",
        "Recipient Unavailable",
        "Returned to Warehouse",
    ]

    return shipments[shipments["current_status"].isin(issue_statuses)].copy()


def answer_data_question(
    question: str,
    shipments: pd.DataFrame,
    pickups: pd.DataFrame,
    payments: pd.DataFrame,
    customers: pd.DataFrame,
) -> tuple[str, pd.DataFrame | None]:
    """
    Rule-based assistant for the MVP.

    This gives the platform the feel of an AI assistant without requiring
    OpenAI, LangChain, or a paid API key in the first version.
    """

    q = question.lower().strip()

    if not q:
        return "Ask a question about shipments, pickups, payments, or customers.", None

    # Outstanding balances / unpaid records
    if (
        "unpaid" in q
        or "balance" in q
        or "owed" in q
        or "outstanding" in q
        or "follow-up" in q
        or "follow up" in q
    ):
        result = get_unpaid_or_partial_payments(payments)

        if result.empty:
            return "There are no unpaid or partial payment records in the current data.", result

        total_balance = result["balance_due"].fillna(0).sum()

        return (
            f"There are {len(result)} records with an outstanding balance. "
            f"The total outstanding balance is ${total_balance:,.2f}.",
            result,
        )

    # Fully paid records
    if "paid" in q and "unpaid" not in q and "partial" not in q:
        if payments.empty or "payment_status" not in payments.columns:
            return "I could not find payment status data.", None

        result = payments[payments["payment_status"].eq("Paid")].copy()

        total_paid = (
            result["amount_paid"].fillna(0).sum()
            if "amount_paid" in result.columns
            else 0
        )

        return (
            f"There are {len(result)} fully paid records. "
            f"The total paid amount for these records is ${total_paid:,.2f}.",
            result,
        )

    # Partial payments
    if "partial" in q:
        if payments.empty or "payment_status" not in payments.columns:
            return "I could not find partial payment data.", None

        result = payments[payments["payment_status"].eq("Partial")].copy()

        return f"There are {len(result)} partial payment records.", result

    # Revenue
    if "revenue" in q or "collected" in q or "money" in q or "income" in q:
        if payments.empty or "amount_paid" not in payments.columns:
            return "I could not find revenue data.", None

        total_paid = payments["amount_paid"].fillna(0).sum()

        return (
            f"Total revenue collected in the current dataset is ${total_paid:,.2f}.",
            payments,
        )

    # In transit
    if "in transit" in q or "transit" in q:
        result = get_in_transit_shipments(shipments)
        return f"There are {len(result)} shipments currently in transit.", result

    # Delivered
    if "delivered" in q or "delivery completed" in q:
        result = get_delivered_shipments(shipments)
        return f"There are {len(result)} delivered shipments.", result

    # Delivery issues
    if (
        "issue" in q
        or "problem" in q
        or "delay" in q
        or "delayed" in q
        or "hold" in q
        or "on hold" in q
    ):
        result = get_delivery_issues(shipments)

        if result.empty:
            return "No delivery issues were found in the current shipment data.", result

        return f"There are {len(result)} shipments that may need delivery follow-up.", result

    # Pickups
    if "pickup" in q or "pickups" in q or "schedule" in q:
        if pickups.empty:
            return "I could not find pickup schedule data.", None

        result = pickups.copy()

        if "pending" in q or "scheduled" in q or "rescheduled" in q:
            result = get_pending_pickups(pickups)

            return (
                f"There are {len(result)} pickups that are pending, scheduled, or rescheduled.",
                result,
            )

        return f"There are {len(result)} pickup records in the schedule.", result

    # Guyana
    if "guyana" in q:
        result = get_shipments_by_destination(shipments, "guyana")
        return f"There are {len(result)} shipments going to Guyana.", result

    # Trinidad
    if "trinidad" in q:
        result = get_shipments_by_destination(shipments, "trinidad")
        return f"There are {len(result)} shipments going to Trinidad.", result

    # Barbados
    if "barbados" in q:
        result = get_shipments_by_destination(shipments, "barbados")
        return f"There are {len(result)} shipments going to Barbados.", result

    # Jamaica
    if "jamaica" in q:
        result = get_shipments_by_destination(shipments, "jamaica")
        return f"There are {len(result)} shipments going to Jamaica.", result

    # Customer count
    if "customer" in q or "customers" in q:
        return f"There are {len(customers)} customers in the current dataset.", customers

    # Shipment count
    if "shipment" in q or "shipments" in q:
        return f"There are {len(shipments)} shipments in the current dataset.", shipments

    return (
        "I can answer questions about unpaid balances, revenue, pickups, customers, "
        "delivered shipments, in-transit shipments, delivery issues, and shipments by destination.",
        None,
    )