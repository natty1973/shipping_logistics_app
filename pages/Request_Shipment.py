from __future__ import annotations

from datetime import date, datetime
from random import randint

import pandas as pd
import streamlit as st

from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(
    page_title="Request Shipment",
    page_icon="📝",
    layout="wide",
)


SHIPPING_OPTIONS = [
    "Express Air — 3–5 Business Days",
    "Standard Air — 7–10 Business Days",
    "Express Sea — Approx. 3 Weeks",
    "Standard Sea — 4–6 Weeks",
]


ITEM_TYPES = [
    "Barrel",
    "Box",
    "Crate",
    "Suitcase",
    "Document",
    "Household Goods",
    "Electronics",
    "Food Items",
    "Clothing",
    "Other",
]


DESTINATION_COUNTRIES = [
    "Guyana",
    "Trinidad",
    "Jamaica",
    "Barbados",
    "Other",
]


PICKUP_AREAS = [
    "Queens",
    "Brooklyn",
    "Bronx",
    "Manhattan",
    "Staten Island",
    "New Jersey",
    "Jersey City",
    "Newark",
    "Long Island",
    "Other",
]


PREFERRED_WINDOWS = [
    "Morning",
    "Afternoon",
    "Evening",
    "Flexible",
]


def generate_request_id() -> str:
    today = datetime.now().strftime("%Y%m%d")
    random_number = randint(1000, 9999)
    return f"REQ-{today}-{random_number}"


def get_portal_label() -> str:
    portal_mode = st.session_state.get("portal_mode", "customer")

    if portal_mode == "staff":
        return "Staff Portal"

    if portal_mode == "owner":
        return "Owner Portal"

    return "Customer Portal"


def get_page_subtitle() -> str:
    portal_mode = st.session_state.get("portal_mode", "customer")

    if portal_mode == "staff":
        return (
            "Create a shipment request on behalf of a customer. Staff can capture the customer’s "
            "preferred pickup date/window, but the official two-hour pickup window is confirmed later."
        )

    if portal_mode == "owner":
        return (
            "Create or review the shipment intake workflow. Customers provide preferred pickup availability; "
            "staff or owner confirms the official two-hour pickup window."
        )

    return (
        "Start a new shipment request by entering your contact details, pickup location, destination, "
        "item details, and preferred pickup availability. Solomon Shipping will confirm the official two-hour pickup window."
    )


def initialize_request_storage() -> None:
    if "shipment_request_records" not in st.session_state:
        st.session_state.shipment_request_records = []


def main() -> None:
    """
    Customer/staff/owner shipment request form.

    This is an intake form. It collects preferred pickup information,
    but it does not guarantee the final pickup time.
    """

    apply_custom_styles()
    sidebar_shipping_options()
    initialize_request_storage()

    portal_label = get_portal_label()

    hero(
        title="Request Shipment",
        subtitle=get_page_subtitle(),
    )

    st.markdown(
        f"""
        <span class="badge-green">{portal_label}</span>
        <span class="badge-dark">Shipment Intake</span>
        <span class="badge-red">Preferred Pickup Only</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    st.info(
        "Pickup times entered here are preferred availability only. Solomon Shipping staff will review driver availability and confirm the official two-hour pickup window."
    )

    st.subheader("Shipment Request Form")

    with st.form("shipment_request_form"):
        st.markdown("### Customer Information")

        customer_col1, customer_col2 = st.columns(2)

        with customer_col1:
            customer_name = st.text_input("Full Name")
            phone = st.text_input("Phone Number")
            email = st.text_input("Email Address")

        with customer_col2:
            customer_type = st.selectbox(
                "Customer Type",
                ["New Customer", "Returning Customer"],
            )
            preferred_contact = st.selectbox(
                "Preferred Contact Method",
                ["Phone", "Email", "WhatsApp", "Text Message"],
            )
            requested_by = st.text_input(
                "Request Entered By",
                value="Customer" if portal_label == "Customer Portal" else portal_label,
            )

        st.divider()

        st.markdown("### Preferred Pickup Information")

        st.caption(
            "This is not the final confirmed pickup schedule. Staff will confirm the official two-hour pickup window after reviewing driver availability and route capacity."
        )

        pickup_col1, pickup_col2 = st.columns(2)

        with pickup_col1:
            pickup_address = st.text_input("Pickup Address")
            pickup_city = st.text_input("Pickup City")
            pickup_state = st.text_input("Pickup State", value="NJ")
            pickup_zip = st.text_input("Pickup ZIP Code")

        with pickup_col2:
            pickup_area = st.selectbox(
                "Pickup Area / Route",
                PICKUP_AREAS,
            )
            preferred_pickup_date = st.date_input(
                "Preferred Pickup Date",
                value=date.today(),
            )
            preferred_pickup_window = st.selectbox(
                "Preferred Pickup Window",
                PREFERRED_WINDOWS,
            )
            pickup_flexibility = st.selectbox(
                "If this time is unavailable, can we offer another window?",
                [
                    "Yes, any available time that day",
                    "Yes, but contact me first",
                    "No, only this window works",
                ],
            )

        pickup_notes = st.text_area(
            "Pickup Notes",
            placeholder="Add gate code, apartment number, parking instructions, best contact person, or preferred pickup notes.",
            height=100,
        )

        st.divider()

        st.markdown("### Destination Information")

        destination_col1, destination_col2 = st.columns(2)

        with destination_col1:
            destination_country = st.selectbox(
                "Destination Country",
                DESTINATION_COUNTRIES,
            )
            destination_city = st.text_input("Destination City / Area")

        with destination_col2:
            recipient_name = st.text_input("Recipient Name")
            recipient_phone = st.text_input("Recipient Phone Number")

        st.divider()

        st.markdown("### Shipment Details")

        shipment_col1, shipment_col2 = st.columns(2)

        with shipment_col1:
            item_type = st.selectbox("Item Type", ITEM_TYPES)
            quantity = st.number_input(
                "Quantity",
                min_value=1,
                step=1,
                value=1,
            )
            estimated_weight = st.text_input(
                "Estimated Weight, if known",
                placeholder="Example: 50 lbs",
            )

        with shipment_col2:
            shipping_option = st.selectbox(
                "Preferred Shipping Option",
                SHIPPING_OPTIONS,
            )
            declared_value = st.text_input(
                "Declared Value, if applicable",
                placeholder="Example: $250",
            )
            special_handling = st.multiselect(
                "Special Handling",
                [
                    "Fragile",
                    "Keep Dry",
                    "Heavy Item",
                    "Food Items",
                    "Documents",
                    "No Special Handling",
                ],
                default=["No Special Handling"],
            )

        shipment_notes = st.text_area(
            "Additional Shipment Notes",
            placeholder="Add item details, delivery notes, or special requests.",
            height=120,
        )

        st.divider()

        st.markdown("### Payment Preference")

        payment_terms = st.selectbox(
            "How will this shipment be paid?",
            [
                "Sender Paid / Prepaid",
                "Receiver Paid / Freight Collect",
                "Split Payment",
                "Not Sure Yet",
            ],
        )

        payment_notes = st.text_area(
            "Payment Notes",
            placeholder="Example: Sender pays deposit in New Jersey, receiver pays balance in Guyana.",
            height=80,
        )

        submitted = st.form_submit_button(
            "Submit Shipment Request",
            use_container_width=True,
        )

    if submitted:
        required_fields = [
            customer_name,
            phone,
            pickup_address,
            pickup_city,
            destination_country,
            destination_city,
            recipient_name,
            recipient_phone,
        ]

        if any(not str(field).strip() for field in required_fields):
            st.error(
                "Please complete the required customer, pickup, destination, and recipient fields before submitting."
            )
            return

        request_id = generate_request_id()

        request_record = {
            "request_id": request_id,
            "request_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "entered_from_portal": portal_label,
            "requested_by": requested_by,
            "customer_name": customer_name,
            "phone": phone,
            "email": email,
            "customer_type": customer_type,
            "preferred_contact": preferred_contact,
            "pickup_address": pickup_address,
            "pickup_city": pickup_city,
            "pickup_state": pickup_state,
            "pickup_zip": pickup_zip,
            "pickup_area": pickup_area,
            "preferred_pickup_date": str(preferred_pickup_date),
            "preferred_pickup_window": preferred_pickup_window,
            "pickup_flexibility": pickup_flexibility,
            "pickup_notes": pickup_notes,
            "destination_country": destination_country,
            "destination_city": destination_city,
            "recipient_name": recipient_name,
            "recipient_phone": recipient_phone,
            "item_type": item_type,
            "quantity": quantity,
            "estimated_weight": estimated_weight,
            "shipping_option": shipping_option,
            "declared_value": declared_value,
            "special_handling": ", ".join(special_handling),
            "shipment_notes": shipment_notes,
            "payment_terms": payment_terms,
            "payment_notes": payment_notes,
            "request_status": "Submitted - Pending Pickup Confirmation",
        }

        st.session_state.shipment_request_records.append(request_record)

        st.success(
            f"Shipment request submitted successfully. Request ID: {request_id}"
        )

        st.warning(
            "Your pickup is not confirmed yet. Solomon Shipping will review driver availability and confirm a two-hour pickup window."
        )

        st.markdown("### Request Summary")

        request_df = pd.DataFrame([request_record])
        st.dataframe(request_df, use_container_width=True)

        csv = request_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Download Request Confirmation",
            data=csv,
            file_name=f"{request_id}_shipment_request.csv",
            mime="text/csv",
        )

        st.info(
            "MVP note: this request is currently stored only during the app session. Later, it will save to the database and create shipment, pickup, payment, and history records."
        )

    st.divider()

    st.subheader("How the Pickup Confirmation Process Works")

    process_col1, process_col2, process_col3 = st.columns(3)

    with process_col1:
        with st.container(border=True):
            st.markdown("### 1. Submit Request")
            st.write("Customer submits shipment and preferred pickup availability.")

    with process_col2:
        with st.container(border=True):
            st.markdown("### 2. Staff Reviews")
            st.write("Staff checks route capacity, driver availability, and pickup area.")

    with process_col3:
        with st.container(border=True):
            st.markdown("### 3. Two-Hour Window Confirmed")
            st.write("Solomon Shipping confirms the official pickup window and notifies the customer.")

    if st.session_state.shipment_request_records:
        with st.expander("View submitted requests from this session"):
            session_df = pd.DataFrame(st.session_state.shipment_request_records)
            st.dataframe(session_df, use_container_width=True)


if __name__ == "__main__":
    main()