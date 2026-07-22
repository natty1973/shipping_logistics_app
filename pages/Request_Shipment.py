from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from src.styles import apply_custom_styles, hero, sidebar_shipping_options

try:
    import psycopg2
except ImportError:
    psycopg2 = None


st.set_page_config(
    page_title="Request Shipment",
    page_icon="📝",
    layout="wide",
)


DATABASE_SCHEMA = "solomon_shipping"

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


def get_database_url() -> str | None:
    """
    Read the Neon/PostgreSQL URL from supported Streamlit secret layouts.

    Supported layouts:

    DATABASE_URL = "postgresql://..."

    [connections.neon]
    url = "postgresql://..."

    [connections.postgresql]
    url = "postgresql://..."
    """

    for environment_key in ("DATABASE_URL", "NEON_DATABASE_URL"):
        environment_url = os.getenv(environment_key, "").strip()
        if environment_url:
            return environment_url

    try:
        for top_level_key in ("DATABASE_URL", "NEON_DATABASE_URL"):
            value = str(st.secrets.get(top_level_key, "")).strip()
            if value:
                return value

        connections = st.secrets.get("connections", {})

        if connections:
            for connection_name in ("neon", "postgresql", "postgres"):
                connection_settings = connections.get(connection_name, {})

                if not connection_settings:
                    continue

                for url_key in (
                    "url",
                    "connection_string",
                    "DATABASE_URL",
                    "database_url",
                ):
                    value = str(connection_settings.get(url_key, "")).strip()
                    if value:
                        return value

    except (FileNotFoundError, KeyError, TypeError, AttributeError):
        return None

    return None


def open_database_connection() -> Any:
    """Open a short-lived Neon/PostgreSQL connection."""

    if psycopg2 is None:
        raise RuntimeError(
            "PostgreSQL driver missing. Add psycopg2-binary to requirements.txt."
        )

    database_url = get_database_url()
    if not database_url:
        raise RuntimeError(
            "The Neon connection URL was not found. Use either a top-level "
            "DATABASE_URL secret or [connections.neon] with a url value."
        )

    return psycopg2.connect(
        database_url,
        connect_timeout=15,
        application_name="solomon_shipping_request_page",
    )


def next_customer_id(cursor: Any) -> str:
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s));",
        ("solomon_shipping.customer_id",),
    )
    cursor.execute(
        f"""
        SELECT COALESCE(
            MAX((SUBSTRING(customer_id FROM '^CUST-([0-9]+)$'))::INTEGER),
            0
        ) + 1
        FROM {DATABASE_SCHEMA}.customers
        WHERE customer_id ~ '^CUST-[0-9]+$';
        """
    )
    return f"CUST-{int(cursor.fetchone()[0]):03d}"


def next_shipment_id(cursor: Any, year: int) -> str:
    pattern = rf"^SST-{year}-([0-9]+)$"

    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s));",
        (f"solomon_shipping.shipment_id.{year}",),
    )
    cursor.execute(
        f"""
        SELECT COALESCE(
            MAX((SUBSTRING(shipment_id FROM %s))::INTEGER),
            0
        ) + 1
        FROM {DATABASE_SCHEMA}.shipments
        WHERE shipment_id ~ %s;
        """,
        (pattern, pattern),
    )
    return f"SST-{year}-{int(cursor.fetchone()[0]):04d}"


def next_pickup_id(cursor: Any, year: int) -> str:
    pattern = rf"^PU-{year}-([0-9]+)$"

    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s));",
        (f"solomon_shipping.pickup_id.{year}",),
    )
    cursor.execute(
        f"""
        SELECT COALESCE(
            MAX((SUBSTRING(pickup_id FROM %s))::INTEGER),
            0
        ) + 1
        FROM {DATABASE_SCHEMA}.pickup_schedule
        WHERE pickup_id ~ %s;
        """,
        (pattern, pattern),
    )
    return f"PU-{year}-{int(cursor.fetchone()[0]):04d}"


def find_existing_customer_id(
    cursor: Any,
    customer_name: str,
    phone: str,
    email: str,
) -> str | None:
    """Find a returning customer by email or by matching name and phone."""

    if email.strip():
        cursor.execute(
            f"""
            SELECT customer_id
            FROM {DATABASE_SCHEMA}.customers
            WHERE LOWER(BTRIM(email)) = LOWER(BTRIM(%s))
            LIMIT 1;
            """,
            (email.strip(),),
        )
        row = cursor.fetchone()
        if row:
            return str(row[0])

    cursor.execute(
        f"""
        SELECT customer_id
        FROM {DATABASE_SCHEMA}.customers
        WHERE LOWER(BTRIM(customer_name)) = LOWER(BTRIM(%s))
          AND REGEXP_REPLACE(COALESCE(phone, ''), '[^0-9]', '', 'g')
              = REGEXP_REPLACE(%s, '[^0-9]', '', 'g')
        LIMIT 1;
        """,
        (customer_name.strip(), phone.strip()),
    )
    row = cursor.fetchone()
    return str(row[0]) if row else None


def build_shipment_notes(data: dict[str, Any]) -> str:
    note_lines = [
        f"Recipient: {data['recipient_name']}",
        f"Recipient phone: {data['recipient_phone']}",
        f"Preferred contact: {data['preferred_contact']}",
        f"Pickup area: {data['pickup_area']}",
        f"Preferred pickup window: {data['preferred_pickup_window']}",
        f"Pickup flexibility: {data['pickup_flexibility']}",
        f"Estimated weight: {data['estimated_weight'] or 'Not provided'}",
        f"Declared value: {data['declared_value'] or 'Not provided'}",
        f"Special handling: {data['special_handling'] or 'None'}",
        f"Payment preference: {data['payment_terms']}",
    ]

    if data["pickup_notes"]:
        note_lines.append(f"Pickup notes: {data['pickup_notes']}")
    if data["shipment_notes"]:
        note_lines.append(f"Shipment notes: {data['shipment_notes']}")
    if data["payment_notes"]:
        note_lines.append(f"Payment notes: {data['payment_notes']}")

    return "\n".join(note_lines)


def save_shipment_request(data: dict[str, Any]) -> dict[str, Any]:
    """Save the request and return the permanent IDs generated by PostgreSQL."""

    connection = open_database_connection()

    try:
        connection.autocommit = False

        with connection.cursor() as cursor:
            customer_id = find_existing_customer_id(
                cursor,
                data["customer_name"],
                data["phone"],
                data["email"],
            )

            if customer_id is None:
                customer_id = next_customer_id(cursor)
                cursor.execute(
                    f"""
                    INSERT INTO {DATABASE_SCHEMA}.customers (
                        customer_id,
                        customer_name,
                        phone,
                        email,
                        origin_city,
                        origin_state,
                        destination_country,
                        destination_city,
                        customer_type,
                        notes
                    )
                    VALUES (
                        %s, %s, %s, NULLIF(%s, ''), %s,
                        %s, %s, %s, %s, %s
                    );
                    """,
                    (
                        customer_id,
                        data["customer_name"],
                        data["phone"],
                        data["email"],
                        data["pickup_city"],
                        data["pickup_state"],
                        data["destination_country"],
                        data["destination_city"],
                        data["customer_type"],
                        f"Preferred contact: {data['preferred_contact']}",
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {DATABASE_SCHEMA}.customers
                    SET
                        customer_name = %s,
                        phone = %s,
                        email = COALESCE(NULLIF(%s, ''), email),
                        origin_city = %s,
                        origin_state = %s,
                        destination_country = %s,
                        destination_city = %s,
                        customer_type = %s,
                        notes = %s
                    WHERE customer_id = %s;
                    """,
                    (
                        data["customer_name"],
                        data["phone"],
                        data["email"],
                        data["pickup_city"],
                        data["pickup_state"],
                        data["destination_country"],
                        data["destination_city"],
                        data["customer_type"],
                        f"Preferred contact: {data['preferred_contact']}",
                        customer_id,
                    ),
                )

            current_year = datetime.now().year
            shipment_id = next_shipment_id(cursor, current_year)
            pickup_id = next_pickup_id(cursor, current_year)
            shipment_mode = "Air" if "Air" in data["shipping_option"] else "Sea"

            cursor.execute(
                f"""
                INSERT INTO {DATABASE_SCHEMA}.shipments (
                    shipment_id,
                    customer_id,
                    customer_name,
                    shipment_date,
                    item_type,
                    quantity,
                    origin_city,
                    origin_state,
                    destination_country,
                    destination_city,
                    current_status,
                    amount_charged,
                    amount_paid,
                    balance_due,
                    payment_status,
                    notes,
                    service_type,
                    shipment_mode,
                    release_status
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'Request Received', 0, 0, 0, 'Unpaid', %s, %s, %s,
                    'Pending Review'
                );
                """,
                (
                    shipment_id,
                    customer_id,
                    data["customer_name"],
                    date.today(),
                    data["item_type"],
                    data["quantity"],
                    data["pickup_city"],
                    data["pickup_state"],
                    data["destination_country"],
                    data["destination_city"],
                    build_shipment_notes(data),
                    data["shipping_option"],
                    shipment_mode,
                ),
            )

            full_pickup_address = ", ".join(
                part
                for part in [
                    data["pickup_address"],
                    data["pickup_city"],
                    data["pickup_state"],
                    data["pickup_zip"],
                ]
                if part
            )

            pickup_notes = "\n".join(
                part
                for part in [
                    "Preferred availability only; official two-hour window pending confirmation.",
                    f"Pickup area: {data['pickup_area']}",
                    f"Flexibility: {data['pickup_flexibility']}",
                    data["pickup_notes"],
                ]
                if part
            )

            cursor.execute(
                f"""
                INSERT INTO {DATABASE_SCHEMA}.pickup_schedule (
                    pickup_id,
                    shipment_id,
                    customer_id,
                    customer_name,
                    pickup_date,
                    pickup_time_window,
                    pickup_address,
                    assigned_staff,
                    pickup_status,
                    notes
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    NULL, 'Pending Confirmation', %s
                );
                """,
                (
                    pickup_id,
                    shipment_id,
                    customer_id,
                    data["customer_name"],
                    data["preferred_pickup_date"],
                    data["preferred_pickup_window"],
                    full_pickup_address,
                    pickup_notes,
                ),
            )

            shipment_number = shipment_id.rsplit("-", 1)[-1]
            status_id = f"STAT-{current_year}-{shipment_number}-01"

            cursor.execute(
                f"""
                INSERT INTO {DATABASE_SCHEMA}.status_history (
                    status_id,
                    shipment_id,
                    status,
                    status_date,
                    updated_by,
                    notes
                )
                VALUES (
                    %s, %s, 'Request Received', CURRENT_TIMESTAMP, %s, %s
                );
                """,
                (
                    status_id,
                    shipment_id,
                    data["requested_by"],
                    "Shipment request submitted through the Request Shipment page.",
                ),
            )

        connection.commit()

        return {
            "shipment_id": shipment_id,
            "customer_id": customer_id,
            "pickup_id": pickup_id,
            "request_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "request_status": "Request Received",
            "pickup_status": "Pending Confirmation",
        }

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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
            "Create a shipment request on behalf of a customer. A permanent shipment ID is generated "
            "when the request is saved; the official pickup window is confirmed later."
        )
    if portal_mode == "owner":
        return (
            "Create or review shipment intake. Every saved request receives a permanent shipment ID "
            "for tracking and shipment management."
        )
    return (
        "Start a shipment request. After successful submission, you will receive a permanent shipment ID "
        "to track and manage your shipment."
    )


def initialize_request_storage() -> None:
    if "shipment_request_records" not in st.session_state:
        st.session_state.shipment_request_records = []
    if "last_shipment_confirmation" not in st.session_state:
        st.session_state.last_shipment_confirmation = None


def display_confirmation(record: dict[str, Any]) -> None:
    st.success("Your shipment request was saved successfully.")
    st.markdown("### Your Shipment ID")
    st.code(record["shipment_id"], language=None)
    st.warning(
        "Save this Shipment ID. You will need it to track the package or manage this shipment. "
        "Your pickup is still pending confirmation."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Shipment Status", record["request_status"])
    with col2:
        st.metric("Pickup Status", record["pickup_status"])
    with col3:
        st.metric("Customer ID", record["customer_id"])


def main() -> None:
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
        "A permanent Shipment ID is generated after the request is successfully saved. "
        "Pickup times entered here are preferred availability only."
    )

    st.subheader("Shipment Request Form")

    with st.form("shipment_request_form", clear_on_submit=False):
        st.markdown("### Customer Information")
        customer_col1, customer_col2 = st.columns(2)

        with customer_col1:
            customer_name = st.text_input("Full Name *")
            phone = st.text_input("Phone Number *")
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
            "This is not the final confirmed pickup schedule. Staff will confirm the official two-hour window after reviewing driver availability and route capacity."
        )

        pickup_col1, pickup_col2 = st.columns(2)

        with pickup_col1:
            pickup_address = st.text_input("Pickup Address *")
            pickup_city = st.text_input("Pickup City *")
            pickup_state = st.text_input("Pickup State *", value="NJ")
            pickup_zip = st.text_input("Pickup ZIP Code")

        with pickup_col2:
            pickup_area = st.selectbox("Pickup Area / Route", PICKUP_AREAS)
            preferred_pickup_date = st.date_input(
                "Preferred Pickup Date",
                value=date.today(),
                min_value=date.today(),
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
                "Destination Country *",
                DESTINATION_COUNTRIES,
            )
            destination_city = st.text_input("Destination City / Area *")

        with destination_col2:
            recipient_name = st.text_input("Recipient Name *")
            recipient_phone = st.text_input("Recipient Phone Number *")

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
        required_fields = {
            "Full Name": customer_name,
            "Phone Number": phone,
            "Pickup Address": pickup_address,
            "Pickup City": pickup_city,
            "Pickup State": pickup_state,
            "Destination City": destination_city,
            "Recipient Name": recipient_name,
            "Recipient Phone Number": recipient_phone,
        }

        missing_fields = [
            label
            for label, value in required_fields.items()
            if not str(value).strip()
        ]

        if missing_fields:
            st.error(
                "Please complete these required fields: "
                + ", ".join(missing_fields)
                + "."
            )
        else:
            form_data = {
                "entered_from_portal": portal_label,
                "requested_by": requested_by.strip() or portal_label,
                "customer_name": customer_name.strip(),
                "phone": phone.strip(),
                "email": email.strip(),
                "customer_type": customer_type,
                "preferred_contact": preferred_contact,
                "pickup_address": pickup_address.strip(),
                "pickup_city": pickup_city.strip(),
                "pickup_state": pickup_state.strip(),
                "pickup_zip": pickup_zip.strip(),
                "pickup_area": pickup_area,
                "preferred_pickup_date": preferred_pickup_date,
                "preferred_pickup_window": preferred_pickup_window,
                "pickup_flexibility": pickup_flexibility,
                "pickup_notes": pickup_notes.strip(),
                "destination_country": destination_country,
                "destination_city": destination_city.strip(),
                "recipient_name": recipient_name.strip(),
                "recipient_phone": recipient_phone.strip(),
                "item_type": item_type,
                "quantity": int(quantity),
                "estimated_weight": estimated_weight.strip(),
                "shipping_option": shipping_option,
                "declared_value": declared_value.strip(),
                "special_handling": ", ".join(special_handling),
                "shipment_notes": shipment_notes.strip(),
                "payment_terms": payment_terms,
                "payment_notes": payment_notes.strip(),
            }

            try:
                with st.spinner(
                    "Saving the shipment request and generating the Shipment ID..."
                ):
                    database_result = save_shipment_request(form_data)

                request_record = {
                    **database_result,
                    **form_data,
                }

                st.session_state.shipment_request_records.append(request_record)
                st.session_state.last_shipment_confirmation = request_record

                display_confirmation(request_record)

                st.markdown("### Request Summary")
                request_df = pd.DataFrame([request_record])
                st.dataframe(request_df, use_container_width=True)

                csv_data = request_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Shipment Confirmation",
                    data=csv_data,
                    file_name=f"{request_record['shipment_id']}_shipment_confirmation.csv",
                    mime="text/csv",
                )

            except Exception as exc:
                st.session_state.last_shipment_confirmation = None
                st.error(
                    "The shipment request could not be saved to Neon, so no Shipment ID was issued. "
                    "Confirm that DATABASE_URL is saved in Streamlit Secrets and that the "
                    "solomon_shipping tables were installed successfully."
                )
                st.caption(f"Technical details: {exc}")

    elif st.session_state.last_shipment_confirmation:
        with st.expander("View the most recent shipment confirmation"):
            display_confirmation(st.session_state.last_shipment_confirmation)

    st.divider()
    st.subheader("How the Pickup Confirmation Process Works")
    process_col1, process_col2, process_col3 = st.columns(3)

    with process_col1:
        with st.container(border=True):
            st.markdown("### 1. Submit Request")
            st.write(
                "The customer submits the request and immediately receives a permanent Shipment ID."
            )

    with process_col2:
        with st.container(border=True):
            st.markdown("### 2. Staff Reviews")
            st.write(
                "Staff checks route capacity, driver availability, pickup area, and shipment details."
            )

    with process_col3:
        with st.container(border=True):
            st.markdown("### 3. Pickup Window Confirmed")
            st.write(
                "Solomon Shipping confirms the official pickup window and updates the same Shipment ID."
            )

    if st.session_state.shipment_request_records:
        with st.expander("View submitted requests from this session"):
            session_df = pd.DataFrame(st.session_state.shipment_request_records)
            st.dataframe(session_df, use_container_width=True)


if __name__ == "__main__":
    main()
