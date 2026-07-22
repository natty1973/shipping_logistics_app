from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_loader import load_branch_payments
from src.styles import apply_custom_styles, hero, sidebar_shipping_options
from src.utils import format_currency


st.set_page_config(
    page_title="My Payments",
    page_icon="💳",
    layout="wide",
)


def search_customer_payments(branch_payments: pd.DataFrame, lookup_value: str) -> pd.DataFrame:
    if branch_payments.empty or not lookup_value:
        return pd.DataFrame()

    search_columns = [
        "shipment_id",
        "invoice_number",
        "sender_name",
        "receiver_name",
        "payment_terms",
        "payment_responsibility",
        "payment_status",
        "release_status",
        "notes",
    ]

    available_columns = [col for col in search_columns if col in branch_payments.columns]

    if not available_columns:
        return pd.DataFrame()

    search_text = branch_payments[available_columns].astype(str).agg(" ".join, axis=1)

    return branch_payments[
        search_text.str.lower().str.contains(lookup_value.lower(), na=False)
    ].copy()


def safe_money(record: pd.Series, column: str) -> float:
    try:
        return float(record.get(column, 0))
    except (TypeError, ValueError):
        return 0.0


def render_payment_summary(record: pd.Series) -> None:
    amount_charged = safe_money(record, "amount_charged")
    paid_nj = safe_money(record, "amount_paid_nj")
    paid_guyana = safe_money(record, "amount_paid_guyana")
    total_paid = safe_money(record, "total_amount_paid")
    balance_due = safe_money(record, "balance_due")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Amount Charged", format_currency(amount_charged))

    with col2:
        st.metric("Total Paid", format_currency(total_paid))

    with col3:
        st.metric("Balance Due", format_currency(balance_due))

    with col4:
        st.metric("Payment Status", str(record.get("payment_status", "Not Available")))

    col5, col6 = st.columns(2)

    with col5:
        with st.container(border=True):
            st.markdown("#### Paid in New Jersey")
            st.write(format_currency(paid_nj))

    with col6:
        with st.container(border=True):
            st.markdown("#### Paid in Guyana")
            st.write(format_currency(paid_guyana))

    with st.container(border=True):
        st.markdown("#### Release Status")
        st.write(str(record.get("release_status", "Not Available")))

    if balance_due <= 0:
        st.success("This shipment appears fully paid.")
    else:
        st.warning(
            "This shipment has a remaining balance. Payment may be required before the barrel is released."
        )


def main() -> None:
    """
    Customer-facing payment lookup page using branch_payments.csv.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    branch_payments = load_branch_payments()

    hero(
        title="My Payments",
        subtitle=(
            "Look up your shipment invoice, payment terms, New Jersey/Guyana payment status, "
            "balance due, and release status."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Customer Payment Lookup</span>
        <span class="badge-dark">NJ + Guyana Payments</span>
        <span class="badge-red">Balance / Release Status</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    if branch_payments.empty:
        st.warning("No branch payment data found. Please check that branch_payments.csv is inside the data folder.")
        return

    st.subheader("Find Your Payment")

    lookup_value = st.text_input(
        "Enter Shipment ID, Invoice Number, Sender Name, or Receiver Name",
        placeholder="Example: SST-2026-0001 or INV-2026-0001",
    )

    if not lookup_value:
        st.info("Enter your shipment ID, invoice number, sender name, or receiver name to view payment details.")
        return

    matched_payments = search_customer_payments(branch_payments, lookup_value)

    if matched_payments.empty:
        st.error("No payment record found. Please check the information and try again.")
        return

    st.markdown("### Matching Payment Records")

    display_columns = [
        "shipment_id",
        "invoice_number",
        "sender_name",
        "receiver_name",
        "payment_terms",
        "payment_responsibility",
        "amount_charged",
        "total_amount_paid",
        "balance_due",
        "payment_status",
        "release_status",
        "payment_collected_at",
        "notes",
    ]

    available_columns = [col for col in display_columns if col in matched_payments.columns]

    st.dataframe(matched_payments[available_columns], use_container_width=True)

    st.divider()

    selected_shipment_id = st.selectbox(
        "Select Shipment ID",
        options=matched_payments["shipment_id"].dropna().astype(str).unique().tolist(),
    )

    selected_df = matched_payments[
        matched_payments["shipment_id"].astype(str) == selected_shipment_id
    ].copy()

    if selected_df.empty:
        st.error("Selected payment record could not be found.")
        return

    record = selected_df.iloc[0]

    st.subheader("Payment Details")

    detail_col1, detail_col2, detail_col3 = st.columns(3)

    with detail_col1:
        with st.container(border=True):
            st.markdown("#### Payment Terms")
            st.write(str(record.get("payment_terms", "Not Available")))

    with detail_col2:
        with st.container(border=True):
            st.markdown("#### Payment Responsibility")
            st.write(str(record.get("payment_responsibility", "Not Available")))

    with detail_col3:
        with st.container(border=True):
            st.markdown("#### Where Payment Is Collected")
            st.write(str(record.get("payment_collected_at", "Not Available")))

    render_payment_summary(record)

    st.divider()

    st.subheader("Payment Help")

    with st.container(border=True):
        st.markdown(
            """
            If your shipment is marked **Hold Until Paid** or **Hold Until Balance Paid**, 
            please contact Solomon Shipping and Trading Inc. to confirm payment instructions.

            **Phone:** 973-675-4921  
            **Address:** 200 Main St Rear, City of Orange, NJ 07050
            """
        )


if __name__ == "__main__":
    main()