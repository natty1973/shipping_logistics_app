from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_loader import (
    load_branch_payments,
    load_shipment_change_history,
    load_shipments,
    load_status_history,
)
from src.styles import apply_custom_styles, hero, sidebar_shipping_options
from src.utils import format_currency


st.set_page_config(
    page_title="Shipment Status",
    page_icon="📦",
    layout="wide",
)


STATUS_ORDER = [
    "Request Received",
    "Pickup Scheduled",
    "Picked Up",
    "At Warehouse",
    "In Transit",
    "Arrived at Destination",
    "Out for Delivery",
    "Delivered",
]


def safe_get(record: pd.Series, column: str, default: str = "Not Available") -> str:
    value = record.get(column, default)

    if pd.isna(value):
        return default

    return str(value)


def search_shipments(shipments: pd.DataFrame, lookup_value: str) -> pd.DataFrame:
    if shipments.empty or not lookup_value:
        return pd.DataFrame()

    search_columns = [
        "shipment_id",
        "customer_id",
        "customer_name",
        "sender_name",
        "receiver_name",
        "destination_city",
        "destination_country",
        "current_status",
        "shipment_status",
        "status",
        "tracking_number",
    ]

    available_columns = [col for col in search_columns if col in shipments.columns]

    if not available_columns:
        return pd.DataFrame()

    search_text = shipments[available_columns].astype(str).agg(" ".join, axis=1)

    return shipments[
        search_text.str.lower().str.contains(lookup_value.lower(), na=False)
    ].copy()


def get_status_column(shipments: pd.DataFrame) -> str | None:
    for candidate in ["current_status", "shipment_status", "status"]:
        if candidate in shipments.columns:
            return candidate

    return None


def render_status_timeline(current_status: str) -> None:
    st.subheader("Shipment Progress")

    if not current_status or current_status == "Not Available":
        st.info("No current shipment status found.")
        return

    normalized_current = current_status.lower()

    timeline_html = "<div style='display:flex; flex-wrap:wrap; gap:0.5rem; margin-top:0.7rem;'>"

    current_index = -1

    for idx, status in enumerate(STATUS_ORDER):
        if status.lower() in normalized_current or normalized_current in status.lower():
            current_index = idx
            break

    for idx, status in enumerate(STATUS_ORDER):
        if current_index >= 0 and idx < current_index:
            bg = "#E6F4EF"
            color = "#0B6E4F"
            border = "#0B6E4F"
            icon = "✓"
        elif idx == current_index:
            bg = "#FFF2B8"
            color = "#053B2D"
            border = "#F7D774"
            icon = "●"
        else:
            bg = "#F3F4F6"
            color = "#6B7280"
            border = "#E5E7EB"
            icon = "○"

        timeline_html += f"""
        <div style='
            padding:0.7rem 0.9rem;
            border-radius:999px;
            background:{bg};
            color:{color};
            border:1px solid {border};
            font-weight:800;
            font-size:0.86rem;
        '>{icon} {status}</div>
        """

    timeline_html += "</div>"

    st.markdown(timeline_html, unsafe_allow_html=True)


def render_shipment_summary(record: pd.Series, status_column: str | None) -> None:
    shipment_id = safe_get(record, "shipment_id")
    customer_name = safe_get(record, "customer_name", safe_get(record, "sender_name"))
    destination_city = safe_get(record, "destination_city")
    destination_country = safe_get(record, "destination_country")
    current_status = safe_get(record, status_column) if status_column else "Not Available"
    estimated_delivery = safe_get(record, "estimated_delivery_date")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        with st.container(border=True):
            st.markdown("#### Shipment ID")
            st.write(shipment_id)

    with col2:
        with st.container(border=True):
            st.markdown("#### Customer")
            st.write(customer_name)

    with col3:
        with st.container(border=True):
            st.markdown("#### Current Status")
            st.write(current_status)

    with col4:
        with st.container(border=True):
            st.markdown("#### Estimated Delivery")
            st.write(estimated_delivery)

    with st.container(border=True):
        st.markdown("#### Destination")
        st.write(f"{destination_city}, {destination_country}")

    render_status_timeline(current_status)


def render_payment_release_status(
    shipment_id: str,
    branch_payments: pd.DataFrame,
) -> None:
    st.subheader("Payment / Release Status")

    if branch_payments.empty or "shipment_id" not in branch_payments.columns:
        st.info("No branch payment information available for this shipment.")
        return

    payment_df = branch_payments[
        branch_payments["shipment_id"].astype(str).str.lower() == shipment_id.lower()
    ].copy()

    if payment_df.empty:
        st.info("No payment record found for this shipment.")
        return

    record = payment_df.iloc[0]

    amount_charged = float(record.get("amount_charged", 0))
    total_paid = float(record.get("total_amount_paid", 0))
    balance_due = float(record.get("balance_due", 0))
    release_status = safe_get(record, "release_status")
    payment_terms = safe_get(record, "payment_terms")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Amount Charged", format_currency(amount_charged))

    with col2:
        st.metric("Total Paid", format_currency(total_paid))

    with col3:
        st.metric("Balance Due", format_currency(balance_due))

    with col4:
        st.metric("Release Status", release_status)

    with st.container(border=True):
        st.markdown("#### Payment Terms")
        st.write(payment_terms)

    if balance_due <= 0:
        st.success("This shipment appears paid and cleared for pickup/release.")
    else:
        st.warning(
            "This shipment has a remaining balance. It may not be released until payment is completed or approved."
        )


def render_status_history(
    shipment_id: str,
    status_history: pd.DataFrame,
    change_history: pd.DataFrame,
) -> None:
    st.subheader("Shipment History")

    frames = []

    if not status_history.empty and "shipment_id" in status_history.columns:
        status_df = status_history[
            status_history["shipment_id"].astype(str).str.lower() == shipment_id.lower()
        ].copy()

        if not status_df.empty:
            frames.append(status_df)

    if not change_history.empty and "shipment_id" in change_history.columns:
        change_df = change_history[
            change_history["shipment_id"].astype(str).str.lower() == shipment_id.lower()
        ].copy()

        if not change_df.empty:
            frames.append(change_df)

    if not frames:
        st.info("No shipment history found for this shipment yet.")
        return

    for idx, frame in enumerate(frames):
        st.markdown(f"### History Source {idx + 1}")
        st.dataframe(frame, use_container_width=True)


def main() -> None:
    """
    Customer/staff/owner shipment status page.

    Customers can search their shipment and see current status, payment/release status,
    and shipment history.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    shipments = load_shipments()
    status_history = load_status_history()
    branch_payments = load_branch_payments()
    change_history = load_shipment_change_history()

    hero(
        title="Shipment Status",
        subtitle=(
            "Check the current shipment stage, delivery progress, payment release status, "
            "and shipment history using a shipment ID, customer name, or tracking information."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Shipment Lookup</span>
        <span class="badge-dark">Current Status</span>
        <span class="badge-red">Payment Release Check</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    if shipments.empty:
        st.warning("No shipment data found. Please check that shipments.csv is inside the data folder.")
        return

    st.subheader("Find a Shipment")

    lookup_value = st.text_input(
        "Enter Shipment ID, customer name, receiver name, or tracking number",
        placeholder="Example: SST-2026-0001",
    )

    if not lookup_value:
        st.info("Enter a shipment ID or customer detail to view shipment status.")
        return

    matched_shipments = search_shipments(shipments, lookup_value)

    if matched_shipments.empty:
        st.error("No matching shipment found. Please check the information and try again.")
        return

    st.markdown("### Matching Shipments")
    st.dataframe(matched_shipments, use_container_width=True)

    status_column = get_status_column(shipments)

    selected_shipment_id = st.selectbox(
        "Select Shipment ID",
        options=matched_shipments["shipment_id"].dropna().astype(str).unique().tolist(),
    )

    selected_df = matched_shipments[
        matched_shipments["shipment_id"].astype(str) == selected_shipment_id
    ].copy()

    if selected_df.empty:
        st.error("Selected shipment could not be found.")
        return

    record = selected_df.iloc[0]

    st.divider()

    render_shipment_summary(record, status_column)

    st.divider()

    render_payment_release_status(
        shipment_id=selected_shipment_id,
        branch_payments=branch_payments,
    )

    st.divider()

    render_status_history(
        shipment_id=selected_shipment_id,
        status_history=status_history,
        change_history=change_history,
    )


if __name__ == "__main__":
    main()