from __future__ import annotations

import streamlit as st

from src.data_loader import load_all_data
from src.metrics import (
    get_total_customers,
    get_total_shipments,
    get_total_revenue_collected,
    get_total_outstanding_balance,
)
from src.styles import apply_custom_styles, hero, section_card
from src.utils import format_currency


st.set_page_config(
    page_title="Solomon Shipping MVP",
    page_icon="🚢",
    layout="wide",
)


def main() -> None:
    """
    Main landing page for the Solomon Shipping MVP.
    """

    apply_custom_styles()

    data = load_all_data()

    customers = data["customers"]
    shipments = data["shipments"]
    payments = data["payments"]

    hero(
        title="Welcome to Solomon Shipping and Trading",
        subtitle=(
            "A modern logistics command center for managing shipments, pickups, "
            "payments, customer records, reports, and AI-assisted operations."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">MVP Prototype</span>
        <span class="badge-dark">Logistics Platform</span>
        <span class="badge-red">Operations Dashboard</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Customers",
            value=get_total_customers(customers),
        )

    with col2:
        st.metric(
            label="Shipments",
            value=get_total_shipments(shipments),
        )

    with col3:
        st.metric(
            label="Revenue Collected",
            value=format_currency(get_total_revenue_collected(payments)),
        )

    with col4:
        st.metric(
            label="Outstanding Balance",
            value=format_currency(get_total_outstanding_balance(payments)),
        )

    st.divider()

    st.subheader("Platform Workflow")

    workflow_col1, workflow_col2, workflow_col3 = st.columns(3)

    with workflow_col1:
        section_card(
            "1. Customer Request",
            "Capture customer details, pickup information, destination, item type, and shipment notes.",
            accent="green",
        )

        section_card(
            "2. Pickup Scheduling",
            "Assign pickup dates, time windows, and staff members to keep operations organized.",
            accent="green",
        )

    with workflow_col2:
        section_card(
            "3. Shipment Tracking",
            "Track each shipment from request received to warehouse, transit, arrival, and delivery.",
            accent="green",
        )

        section_card(
            "4. Payment Monitoring",
            "Monitor invoices, payment status, collected revenue, partial payments, and balances due.",
            accent="red",
        )

    with workflow_col3:
        section_card(
            "5. Reports",
            "Generate weekly shipment, pickup, customer, payment, and status history reports.",
            accent="green",
        )

        section_card(
            "6. AI Assistant",
            "Ask basic operational questions about shipments, unpaid balances, pickups, and revenue.",
            accent="red",
        )

    st.divider()

    st.subheader("MVP Modules")

    module_col1, module_col2, module_col3 = st.columns(3)

    with module_col1:
        section_card(
            "Dashboard",
            "High-level view of shipment activity, payments, pickups, and delivery performance.",
        )

        section_card(
            "Shipments",
            "Search, filter, and review shipment records with status and payment information.",
        )

    with module_col2:
        section_card(
            "Customers",
            "View customer profiles, shipment counts, balances, and destination information.",
        )

        section_card(
            "Pickup Schedule",
            "Manage pickup status, assigned staff, pickup windows, and schedule activity.",
        )

    with module_col3:
        section_card(
            "Payments",
            "Track invoices, amounts charged, amounts paid, payment methods, and balances.",
            accent="red",
        )

        section_card(
            "Reports + AI",
            "Export management reports and use the assistant to summarize operational activity.",
            accent="red",
        )


if __name__ == "__main__":
    main()