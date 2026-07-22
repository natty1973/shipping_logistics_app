from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_loader import load_branch_payments, load_payments
from src.styles import apply_custom_styles, hero, sidebar_shipping_options
from src.utils import format_currency


st.set_page_config(
    page_title="Payments",
    page_icon="💳",
    layout="wide",
)


def get_numeric_sum(df: pd.DataFrame, column: str) -> float:
    """
    Safely sum a numeric column.
    """

    if df.empty or column not in df.columns:
        return 0.0

    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def filter_dataframe(
    df: pd.DataFrame,
    payment_terms: list[str],
    payment_statuses: list[str],
    release_statuses: list[str],
    branches: list[str],
) -> pd.DataFrame:
    """
    Apply owner payment filters.
    """

    filtered = df.copy()

    if payment_terms and "payment_terms" in filtered.columns:
        filtered = filtered[filtered["payment_terms"].astype(str).isin(payment_terms)]

    if payment_statuses and "payment_status" in filtered.columns:
        filtered = filtered[filtered["payment_status"].astype(str).isin(payment_statuses)]

    if release_statuses and "release_status" in filtered.columns:
        filtered = filtered[filtered["release_status"].astype(str).isin(release_statuses)]

    if branches and "payment_collected_at" in filtered.columns:
        filtered = filtered[filtered["payment_collected_at"].astype(str).isin(branches)]

    return filtered


def render_summary_metrics(branch_payments: pd.DataFrame) -> None:
    """
    Render branch payment summary cards.
    """

    total_charged = get_numeric_sum(branch_payments, "amount_charged")
    paid_nj = get_numeric_sum(branch_payments, "amount_paid_nj")
    paid_guyana = get_numeric_sum(branch_payments, "amount_paid_guyana")
    total_paid = get_numeric_sum(branch_payments, "total_amount_paid")
    balance_due = get_numeric_sum(branch_payments, "balance_due")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Charged", format_currency(total_charged))

    with col2:
        st.metric("Paid in New Jersey", format_currency(paid_nj))

    with col3:
        st.metric("Paid in Guyana", format_currency(paid_guyana))

    with col4:
        st.metric("Balance Due", format_currency(balance_due))

    col5, col6, col7 = st.columns(3)

    with col5:
        st.metric("Total Paid", format_currency(total_paid))

    with col6:
        freight_collect_count = 0
        if "payment_terms" in branch_payments.columns:
            freight_collect_count = int(
                branch_payments["payment_terms"]
                .astype(str)
                .str.contains("Receiver Paid|Freight Collect", case=False, na=False)
                .sum()
            )
        st.metric("Freight Collect Shipments", freight_collect_count)

    with col7:
        hold_count = 0
        if "release_status" in branch_payments.columns:
            hold_count = int(
                branch_payments["release_status"]
                .astype(str)
                .str.contains("Hold", case=False, na=False)
                .sum()
            )
        st.metric("Held Until Paid", hold_count)


def render_branch_breakdown(branch_payments: pd.DataFrame) -> None:
    """
    Render payment breakdown by branch/payment terms/status.
    """

    st.subheader("Branch Payment Breakdown")

    breakdown_tabs = st.tabs(
        [
            "By Payment Terms",
            "By Payment Status",
            "By Release Status",
            "By Collection Location",
        ]
    )

    with breakdown_tabs[0]:
        if "payment_terms" in branch_payments.columns:
            summary = (
                branch_payments.groupby("payment_terms", dropna=False)
                .agg(
                    shipments=("shipment_id", "count"),
                    amount_charged=("amount_charged", "sum"),
                    amount_paid_nj=("amount_paid_nj", "sum"),
                    amount_paid_guyana=("amount_paid_guyana", "sum"),
                    total_amount_paid=("total_amount_paid", "sum"),
                    balance_due=("balance_due", "sum"),
                )
                .reset_index()
            )
            st.dataframe(summary, use_container_width=True)
        else:
            st.info("payment_terms column not found.")

    with breakdown_tabs[1]:
        if "payment_status" in branch_payments.columns:
            summary = (
                branch_payments.groupby("payment_status", dropna=False)
                .agg(
                    shipments=("shipment_id", "count"),
                    amount_charged=("amount_charged", "sum"),
                    total_amount_paid=("total_amount_paid", "sum"),
                    balance_due=("balance_due", "sum"),
                )
                .reset_index()
            )
            st.dataframe(summary, use_container_width=True)
        else:
            st.info("payment_status column not found.")

    with breakdown_tabs[2]:
        if "release_status" in branch_payments.columns:
            summary = (
                branch_payments.groupby("release_status", dropna=False)
                .agg(
                    shipments=("shipment_id", "count"),
                    amount_charged=("amount_charged", "sum"),
                    total_amount_paid=("total_amount_paid", "sum"),
                    balance_due=("balance_due", "sum"),
                )
                .reset_index()
            )
            st.dataframe(summary, use_container_width=True)
        else:
            st.info("release_status column not found.")

    with breakdown_tabs[3]:
        if "payment_collected_at" in branch_payments.columns:
            summary = (
                branch_payments.groupby("payment_collected_at", dropna=False)
                .agg(
                    shipments=("shipment_id", "count"),
                    amount_charged=("amount_charged", "sum"),
                    amount_paid_nj=("amount_paid_nj", "sum"),
                    amount_paid_guyana=("amount_paid_guyana", "sum"),
                    total_amount_paid=("total_amount_paid", "sum"),
                    balance_due=("balance_due", "sum"),
                )
                .reset_index()
            )
            st.dataframe(summary, use_container_width=True)
        else:
            st.info("payment_collected_at column not found.")


def render_payment_lookup(branch_payments: pd.DataFrame) -> None:
    """
    Render shipment/invoice payment lookup.
    """

    st.subheader("Payment Lookup")

    lookup_value = st.text_input(
        "Search by shipment ID, invoice number, sender, receiver, payment status, or release status",
        placeholder="Example: SST-2026-0002, INV-2026-0002, receiver paid, hold until paid",
    )

    filtered = branch_payments.copy()

    if lookup_value:
        search_columns = [
            "shipment_id",
            "invoice_number",
            "sender_name",
            "receiver_name",
            "payment_terms",
            "payment_responsibility",
            "payment_status",
            "release_status",
            "payment_collected_at",
            "collected_by",
            "notes",
        ]

        available_columns = [col for col in search_columns if col in filtered.columns]

        if available_columns:
            search_text = filtered[available_columns].astype(str).agg(" ".join, axis=1)
            filtered = filtered[
                search_text.str.lower().str.contains(lookup_value.lower(), na=False)
            ]

    if filtered.empty:
        st.info("No payment records matched your search.")
    else:
        st.dataframe(filtered, use_container_width=True)


def render_payment_release_queue(branch_payments: pd.DataFrame) -> None:
    """
    Show shipments that should not be released until payment is complete.
    """

    st.subheader("Release / Hold Queue")

    if branch_payments.empty:
        st.info("No branch payment records available.")
        return

    queue = branch_payments.copy()

    if "release_status" in queue.columns:
        queue = queue[
            queue["release_status"].astype(str).str.contains(
                "Hold|Cancelled",
                case=False,
                na=False,
            )
        ]

    if queue.empty:
        st.success("No shipments are currently on hold for payment.")
    else:
        display_columns = [
            "shipment_id",
            "invoice_number",
            "sender_name",
            "receiver_name",
            "payment_terms",
            "amount_charged",
            "amount_paid_nj",
            "amount_paid_guyana",
            "total_amount_paid",
            "balance_due",
            "payment_status",
            "release_status",
            "payment_collected_at",
            "notes",
        ]

        available_columns = [col for col in display_columns if col in queue.columns]

        st.warning(
            "These shipments may require payment review before release to the receiver."
        )
        st.dataframe(queue[available_columns], use_container_width=True)


def render_record_payment_form(branch_payments: pd.DataFrame) -> None:
    """
    MVP form to preview recording a New Jersey or Guyana payment.
    """

    st.subheader("Record Branch Payment")

    if branch_payments.empty or "shipment_id" not in branch_payments.columns:
        st.info("Branch payment data is required before recording payments.")
        return

    shipment_options = (
        branch_payments["shipment_id"].dropna().astype(str).unique().tolist()
    )

    with st.form("record_branch_payment_form"):
        col1, col2 = st.columns(2)

        with col1:
            shipment_id = st.selectbox("Shipment ID", shipment_options)
            payment_location = st.selectbox(
                "Payment Collected At",
                [
                    "New Jersey Branch",
                    "Guyana Office",
                ],
            )
            payment_method = st.selectbox(
                "Payment Method",
                [
                    "Cash",
                    "Card",
                    "Zelle",
                    "Bank Transfer",
                    "Mobile Money",
                    "Other",
                ],
            )

        with col2:
            amount_received = st.number_input(
                "Amount Received",
                min_value=0.0,
                step=5.0,
                value=0.0,
            )
            collected_by = st.text_input("Collected By")
            payment_date = st.date_input("Payment Date")

        notes = st.text_area(
            "Payment Notes",
            placeholder="Add receipt note, branch note, or receiver/sender payment details.",
            height=100,
        )

        submitted = st.form_submit_button(
            "Preview Payment Update",
            use_container_width=True,
        )

    if submitted:
        selected_record = branch_payments[
            branch_payments["shipment_id"].astype(str) == str(shipment_id)
        ]

        if selected_record.empty:
            st.error("Selected shipment was not found.")
            return

        current = selected_record.iloc[0]

        amount_charged = float(current.get("amount_charged", 0))
        current_paid_nj = float(current.get("amount_paid_nj", 0))
        current_paid_guyana = float(current.get("amount_paid_guyana", 0))

        updated_paid_nj = current_paid_nj
        updated_paid_guyana = current_paid_guyana

        if payment_location == "New Jersey Branch":
            updated_paid_nj += amount_received
        else:
            updated_paid_guyana += amount_received

        updated_total_paid = updated_paid_nj + updated_paid_guyana
        updated_balance = max(amount_charged - updated_total_paid, 0)

        if updated_balance <= 0:
            updated_payment_status = "Paid"
            updated_release_status = "Cleared for Pickup"
        elif updated_total_paid > 0:
            updated_payment_status = "Partial"
            updated_release_status = "Hold Until Balance Paid"
        else:
            updated_payment_status = "Unpaid"
            updated_release_status = "Hold Until Paid"

        preview_record = {
            "shipment_id": shipment_id,
            "payment_collected_at": payment_location,
            "payment_method": payment_method,
            "amount_received": amount_received,
            "collected_by": collected_by,
            "payment_date": str(payment_date),
            "previous_paid_nj": current_paid_nj,
            "previous_paid_guyana": current_paid_guyana,
            "updated_paid_nj": updated_paid_nj,
            "updated_paid_guyana": updated_paid_guyana,
            "updated_total_paid": updated_total_paid,
            "updated_balance_due": updated_balance,
            "updated_payment_status": updated_payment_status,
            "updated_release_status": updated_release_status,
            "notes": notes,
        }

        st.success("Payment update preview generated.")

        st.dataframe(pd.DataFrame([preview_record]), use_container_width=True)

        st.info(
            "MVP note: this previews the payment update only. Later, this will write directly "
            "to the database or branch_payments table and create a receipt/history entry."
        )


def main() -> None:
    """
    Owner-facing Payments page.

    This page shows New Jersey and Guyana payments, freight collect balances,
    release status, and payment branch activity.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    branch_payments = load_branch_payments()
    legacy_payments = load_payments()

    hero(
        title="Payments",
        subtitle=(
            "Monitor New Jersey and Guyana payments, sender-paid shipments, freight collect balances, "
            "split payments, and release status before barrels are picked up."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner Financial View</span>
        <span class="badge-dark">NJ + Guyana Branch Payments</span>
        <span class="badge-red">Freight Collect / Release Control</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    if branch_payments.empty:
        st.warning(
            "No branch payment data found. Please confirm branch_payments.csv is in the data folder."
        )

        if not legacy_payments.empty:
            st.info("Showing legacy payments.csv below.")
            st.dataframe(legacy_payments, use_container_width=True)

        return

    render_summary_metrics(branch_payments)

    st.divider()

    filters_col1, filters_col2, filters_col3, filters_col4 = st.columns(4)

    with filters_col1:
        payment_terms_options = (
            sorted(branch_payments["payment_terms"].dropna().astype(str).unique())
            if "payment_terms" in branch_payments.columns
            else []
        )
        selected_payment_terms = st.multiselect(
            "Payment Terms",
            options=payment_terms_options,
            default=payment_terms_options,
        )

    with filters_col2:
        payment_status_options = (
            sorted(branch_payments["payment_status"].dropna().astype(str).unique())
            if "payment_status" in branch_payments.columns
            else []
        )
        selected_payment_statuses = st.multiselect(
            "Payment Status",
            options=payment_status_options,
            default=payment_status_options,
        )

    with filters_col3:
        release_status_options = (
            sorted(branch_payments["release_status"].dropna().astype(str).unique())
            if "release_status" in branch_payments.columns
            else []
        )
        selected_release_statuses = st.multiselect(
            "Release Status",
            options=release_status_options,
            default=release_status_options,
        )

    with filters_col4:
        branch_options = (
            sorted(branch_payments["payment_collected_at"].dropna().astype(str).unique())
            if "payment_collected_at" in branch_payments.columns
            else []
        )
        selected_branches = st.multiselect(
            "Collected At",
            options=branch_options,
            default=branch_options,
        )

    filtered_payments = filter_dataframe(
        df=branch_payments,
        payment_terms=selected_payment_terms,
        payment_statuses=selected_payment_statuses,
        release_statuses=selected_release_statuses,
        branches=selected_branches,
    )

    st.divider()

    tabs = st.tabs(
        [
            "Branch Payments Table",
            "Release / Hold Queue",
            "Branch Breakdown",
            "Payment Lookup",
            "Record Payment",
        ]
    )

    with tabs[0]:
        st.subheader("Branch Payments Table")
        st.dataframe(filtered_payments, use_container_width=True)

    with tabs[1]:
        render_payment_release_queue(filtered_payments)

    with tabs[2]:
        render_branch_breakdown(filtered_payments)

    with tabs[3]:
        render_payment_lookup(filtered_payments)

    with tabs[4]:
        render_record_payment_form(branch_payments)


if __name__ == "__main__":
    main()