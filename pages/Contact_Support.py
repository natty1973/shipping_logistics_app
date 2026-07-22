from __future__ import annotations

import pandas as pd
import streamlit as st

from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(
    page_title="Contact Support",
    page_icon="☎️",
    layout="wide",
)


def main() -> None:
    """
    Customer-facing support page.

    MVP version:
    - Collects a support request
    - Shows a confirmation message
    - Does not yet save to database
    """

    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Contact Support",
        subtitle=(
            "Need help with a shipment, pickup, payment, or delivery? "
            "Send a support request and the Solomon Shipping team will follow up."
        ),
    )

    st.subheader("Solomon Shipping and Trading Inc.")

    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.markdown("### 📍 Office Address")
            st.write("200 Main St Rear")
            st.write("City of Orange, NJ 07050")

    with col2:
        with st.container(border=True):
            st.markdown("### ☎️ Phone")
            st.write("973-675-4921")

    st.divider()

    st.subheader("Support Request Form")

    with st.form("support_request_form"):
        col1, col2 = st.columns(2)

        with col1:
            customer_name = st.text_input("Full Name")
            phone = st.text_input("Phone Number")
            email = st.text_input("Email Address")

        with col2:
            shipment_id = st.text_input("Shipment ID, if available")
            support_topic = st.selectbox(
                "Support Topic",
                [
                    "Shipment Status",
                    "Pickup Scheduling",
                    "Payment Question",
                    "Delivery Question",
                    "Change Contact Information",
                    "General Question",
                ],
            )

        message = st.text_area(
            "How can we help?",
            placeholder="Write your message here...",
            height=140,
        )

        submitted = st.form_submit_button("Submit Support Request")

    if submitted:
        if not customer_name or not phone or not message:
            st.error("Please enter your name, phone number, and message before submitting.")
        else:
            support_record = pd.DataFrame(
                [
                    {
                        "customer_name": customer_name,
                        "phone": phone,
                        "email": email,
                        "shipment_id": shipment_id,
                        "support_topic": support_topic,
                        "message": message,
                    }
                ]
            )

            st.success("Your support request has been received.")

            st.markdown("### Request Summary")
            st.dataframe(support_record, use_container_width=True)

            st.info(
                "MVP note: this form currently previews the support request. Later, we can save it to a database, send an email, or create a support ticket."
            )

    st.divider()

    st.subheader("Common Support Topics")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True):
            st.markdown("### 📦 Shipment Updates")
            st.write("Ask about package movement, delivery status, or estimated arrival.")

    with col2:
        with st.container(border=True):
            st.markdown("### 🚚 Pickup Questions")
            st.write("Request help with pickup dates, pickup windows, or address updates.")

    with col3:
        with st.container(border=True):
            st.markdown("### 💳 Payment Support")
            st.write("Ask about invoices, balances, payment confirmation, or receipts.")


if __name__ == "__main__":
    main()