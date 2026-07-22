from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_loader import (
    load_branch_payments,
    load_drivers,
    load_pickup_capacity,
    load_pickups,
    load_shipment_change_history,
    load_shipments,
)
from src.styles import apply_custom_styles, hero, sidebar_shipping_options
from src.utils import format_currency


st.set_page_config(
    page_title="AI Assistant",
    page_icon="🤖",
    layout="wide",
)


def safe_sum(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0

    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def safe_filter_contains(
    df: pd.DataFrame,
    column: str,
    text: str,
) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return pd.DataFrame()

    return df[
        df[column].astype(str).str.contains(text, case=False, na=False)
    ].copy()


def display_table_if_available(df: pd.DataFrame, title: str) -> None:
    if df.empty:
        st.info(f"No records found for: {title}")
    else:
        st.markdown(f"### {title}")
        st.dataframe(df, use_container_width=True)


def answer_payment_question(question: str, branch_payments: pd.DataFrame) -> bool:
    """
    Rule-based payment answers for owner-level AI assistant.
    """

    q = question.lower()

    if branch_payments.empty:
        return False

    if "new jersey" in q or "nj" in q:
        total = safe_sum(branch_payments, "amount_paid_nj")
        st.success(f"Total collected in New Jersey: {format_currency(total)}")

        if "amount_paid_nj" in branch_payments.columns:
            df = branch_payments[
                pd.to_numeric(branch_payments["amount_paid_nj"], errors="coerce").fillna(0) > 0
            ].copy()
            display_table_if_available(df, "Payments Collected in New Jersey")
        return True

    if "guyana" in q:
        total = safe_sum(branch_payments, "amount_paid_guyana")
        st.success(f"Total collected in Guyana: {format_currency(total)}")

        if "amount_paid_guyana" in branch_payments.columns:
            df = branch_payments[
                pd.to_numeric(branch_payments["amount_paid_guyana"], errors="coerce").fillna(0) > 0
            ].copy()
            display_table_if_available(df, "Payments Collected in Guyana")
        return True

    if "balance" in q or "outstanding" in q or "owed" in q:
        balance = safe_sum(branch_payments, "balance_due")
        st.warning(f"Total outstanding balance: {format_currency(balance)}")

        if "balance_due" in branch_payments.columns:
            df = branch_payments[
                pd.to_numeric(branch_payments["balance_due"], errors="coerce").fillna(0) > 0
            ].copy()
            display_table_if_available(df, "Shipments with Outstanding Balances")
        return True

    if "freight collect" in q or "receiver paid" in q:
        if "payment_terms" in branch_payments.columns:
            df = branch_payments[
                branch_payments["payment_terms"]
                .astype(str)
                .str.contains("Receiver Paid|Freight Collect", case=False, na=False)
            ].copy()

            st.info(f"Found {len(df)} freight collect / receiver-paid shipments.")
            display_table_if_available(df, "Freight Collect / Receiver-Paid Shipments")
            return True

    if "hold" in q or "release" in q or "cleared" in q:
        if "release_status" in branch_payments.columns:
            if "cleared" in q:
                df = branch_payments[
                    branch_payments["release_status"]
                    .astype(str)
                    .str.contains("Cleared", case=False, na=False)
                ].copy()
                st.success(f"Found {len(df)} shipments cleared for pickup/release.")
                display_table_if_available(df, "Cleared Shipments")
            else:
                df = branch_payments[
                    branch_payments["release_status"]
                    .astype(str)
                    .str.contains("Hold", case=False, na=False)
                ].copy()
                st.warning(f"Found {len(df)} shipments currently on payment hold.")
                display_table_if_available(df, "Shipments on Hold")
            return True

    if "paid" in q or "payment" in q or "money" in q:
        total_charged = safe_sum(branch_payments, "amount_charged")
        total_paid = safe_sum(branch_payments, "total_amount_paid")
        balance = safe_sum(branch_payments, "balance_due")
        paid_nj = safe_sum(branch_payments, "amount_paid_nj")
        paid_guyana = safe_sum(branch_payments, "amount_paid_guyana")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Charged", format_currency(total_charged))

        with col2:
            st.metric("Total Paid", format_currency(total_paid))

        with col3:
            st.metric("Paid in NJ", format_currency(paid_nj))

        with col4:
            st.metric("Paid in Guyana", format_currency(paid_guyana))

        st.warning(f"Outstanding balance: {format_currency(balance)}")
        return True

    return False


def answer_pickup_question(
    question: str,
    pickup_capacity: pd.DataFrame,
    drivers: pd.DataFrame,
    pickups: pd.DataFrame,
) -> bool:
    """
    Rule-based pickup and driver answers.
    """

    q = question.lower()

    if "driver" in q:
        st.info(f"Total drivers in the system: {len(drivers)}")

        if not drivers.empty:
            display_columns = [
                "driver_id",
                "driver_name",
                "phone",
                "service_areas",
                "primary_area",
                "max_pickups_per_day",
                "active_status",
            ]
            available_columns = [col for col in display_columns if col in drivers.columns]
            display_table_if_available(drivers[available_columns], "Driver Directory")
        return True

    if "capacity" in q or "available slot" in q or "slots" in q or "full" in q:
        if pickup_capacity.empty:
            return False

        available_slots = safe_sum(pickup_capacity, "available_slots")
        scheduled_pickups = safe_sum(pickup_capacity, "scheduled_pickups")
        max_pickups = safe_sum(pickup_capacity, "max_pickups")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Max Pickups", int(max_pickups))

        with col2:
            st.metric("Scheduled Pickups", int(scheduled_pickups))

        with col3:
            st.metric("Available Slots", int(available_slots))

        if "capacity_status" in pickup_capacity.columns:
            if "full" in q:
                df = pickup_capacity[
                    pickup_capacity["capacity_status"]
                    .astype(str)
                    .str.contains("Full", case=False, na=False)
                ].copy()
                display_table_if_available(df, "Full Pickup Routes")
            elif "limited" in q:
                df = pickup_capacity[
                    pickup_capacity["capacity_status"]
                    .astype(str)
                    .str.contains("Limited", case=False, na=False)
                ].copy()
                display_table_if_available(df, "Limited Pickup Routes")
            else:
                display_table_if_available(pickup_capacity, "Pickup Capacity Board")

        return True

    if "pickup" in q or "schedule" in q:
        if pickups.empty:
            return False

        st.info(f"Total pickup records: {len(pickups)}")
        display_table_if_available(pickups, "Pickup Schedule Records")
        return True

    return False


def answer_change_question(question: str, change_history: pd.DataFrame) -> bool:
    """
    Rule-based customer change request answers.
    """

    q = question.lower()

    if change_history.empty:
        return False

    if "pending" in q or "change request" in q or "reschedule" in q or "cancel" in q:
        df = change_history.copy()

        if "approval_status" in df.columns:
            df = df[
                df["approval_status"].astype(str).str.lower().eq("pending")
            ].copy()

        if "change_date" in df.columns:
            df = df.sort_values("change_date", ascending=False)

        st.warning(f"Pending customer change requests: {len(df)}")
        display_table_if_available(df, "Pending Change Requests")
        return True

    if "history" in q or "audit" in q:
        df = change_history.copy()

        if "change_date" in df.columns:
            df = df.sort_values("change_date", ascending=False)

        display_table_if_available(df, "Full Shipment Change History")
        return True

    return False


def answer_shipment_question(question: str, shipments: pd.DataFrame) -> bool:
    """
    Rule-based shipment status answers.
    """

    q = question.lower()

    if shipments.empty:
        return False

    status_column = None

    for candidate in ["current_status", "shipment_status", "status"]:
        if candidate in shipments.columns:
            status_column = candidate
            break

    if "shipment" in q or "status" in q or "delivered" in q or "transit" in q:
        st.info(f"Total shipment records: {len(shipments)}")

        if status_column:
            summary = (
                shipments.groupby(status_column, dropna=False)
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )

            st.markdown("### Shipment Status Summary")
            st.dataframe(summary, use_container_width=True)

        display_table_if_available(shipments, "Shipment Records")
        return True

    return False


def render_suggested_questions() -> None:
    st.markdown("### Suggested Questions")

    suggestions = [
        "How much money was collected in New Jersey?",
        "How much money was collected in Guyana?",
        "Which shipments are on hold because of payment?",
        "Which freight collect shipments still have balances?",
        "Which pickup routes are full?",
        "How many pickup slots are available?",
        "Which drivers are active?",
        "Which customer change requests are pending?",
        "Show shipment status summary.",
    ]

    for question in suggestions:
        st.caption(f"• {question}")


def main() -> None:
    """
    Owner-facing rule-based AI assistant.

    This is an MVP assistant that answers from CSV data without requiring
    a paid LLM API yet.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    shipments = load_shipments()
    pickups = load_pickups()
    branch_payments = load_branch_payments()
    pickup_capacity = load_pickup_capacity()
    drivers = load_drivers()
    change_history = load_shipment_change_history()

    hero(
        title="AI Assistant",
        subtitle=(
            "Ask owner-level questions about payments, freight collect balances, held shipments, "
            "pickup capacity, drivers, customer change requests, and shipment status."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner AI Assistant</span>
        <span class="badge-dark">CSV-Grounded Insights</span>
        <span class="badge-red">MVP Rule-Based Mode</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    render_suggested_questions()

    st.divider()

    question = st.text_input(
        "Ask a question about Solomon Shipping operations",
        placeholder="Example: Which shipments are on hold because of payment?",
    )

    if not question:
        st.info("Enter a question above, or use one of the suggested questions.")
        return

    st.markdown("## Assistant Answer")

    handled = (
        answer_payment_question(question, branch_payments)
        or answer_pickup_question(question, pickup_capacity, drivers, pickups)
        or answer_change_question(question, change_history)
        or answer_shipment_question(question, shipments)
    )

    if not handled:
        st.warning(
            "I could not match that question to the current MVP rules. Try asking about payments, "
            "New Jersey collections, Guyana collections, freight collect, held shipments, drivers, "
            "pickup capacity, pending changes, or shipment status."
        )

    st.divider()

    with st.expander("What this AI Assistant can answer right now"):
        st.markdown(
            """
            This MVP assistant is rule-based and grounded in the CSV files. It can answer questions about:

            - New Jersey payments
            - Guyana payments
            - Freight collect / receiver-paid shipments
            - Outstanding balances
            - Release holds
            - Pickup capacity
            - Driver directory
            - Pending change requests
            - Shipment status summaries

            Later, this can be upgraded to a true AI/RAG assistant connected to the database.
            """
        )


if __name__ == "__main__":
    main()