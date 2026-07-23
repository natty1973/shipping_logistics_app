from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.styles import apply_custom_styles, hero, sidebar_shipping_options


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


def get_configured_connection_names() -> list[str]:
    """
    Return Streamlit SQL connection names without reading or exposing credentials.

    This supports any name already used elsewhere in the app, such as:
    [connections.neon]
    [connections.postgresql]
    [connections.sql]
    """

    discovered_names: list[str] = []

    try:
        connections = st.secrets.get("connections", {})

        if connections and hasattr(connections, "keys"):
            discovered_names.extend(str(name) for name in connections.keys())

    except (FileNotFoundError, KeyError, TypeError, AttributeError):
        pass

    common_names = [
        "neon",
        "postgresql",
        "postgres",
        "sql",
        "database",
        "db",
    ]

    unique_names: list[str] = []

    for name in [*discovered_names, *common_names]:
        clean_name = str(name).strip()

        if clean_name and clean_name not in unique_names:
            unique_names.append(clean_name)

    return unique_names


def get_top_level_database_url() -> str | None:
    """
    Fallback for projects that use a top-level DATABASE_URL instead of
    a [connections.<name>] section.
    """

    for environment_key in ("DATABASE_URL", "NEON_DATABASE_URL"):
        environment_value = os.getenv(environment_key, "").strip()

        if environment_value:
            return environment_value

    try:
        for secret_key in ("DATABASE_URL", "NEON_DATABASE_URL"):
            secret_value = str(st.secrets.get(secret_key, "")).strip()

            if secret_value:
                return secret_value

    except (FileNotFoundError, KeyError, TypeError, AttributeError):
        return None

    return None


@st.cache_resource(show_spinner=False)
def create_fallback_engine(database_url: str) -> Engine:
    """Create a cached SQLAlchemy engine for a top-level database URL."""

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 15,
            "application_name": "solomon_shipping_request_page",
        },
    )


def test_engine(engine: Engine) -> None:
    """Confirm that the configured connection can execute a PostgreSQL query."""

    with engine.connect() as database:
        database.execute(text("SELECT 1;"))


def resolve_database_engine() -> tuple[Engine, str]:
    """
    Reuse the same Streamlit SQL connection already configured for the app.

    The previous page tried to manually extract a URL from st.secrets. That
    failed when the existing Streamlit connection used a different name or
    individual connection fields. st.connection handles both URL-based and
    field-based SQL configurations automatically.
    """

    attempted_names: list[str] = []

    for connection_name in get_configured_connection_names():
        attempted_names.append(connection_name)

        try:
            streamlit_connection = st.connection(
                connection_name,
                type="sql",
            )

            try:
                test_engine(streamlit_connection.engine)
            except Exception:
                # Reinitialize once in case Community Cloud cached an older
                # password before the Neon credential was changed.
                streamlit_connection.reset()
                streamlit_connection = st.connection(
                    connection_name,
                    type="sql",
                )
                test_engine(streamlit_connection.engine)

            return (
                streamlit_connection.engine,
                f"Streamlit connection: {connection_name}",
            )

        except Exception:
            continue

    database_url = get_top_level_database_url()

    if database_url:
        fallback_engine = create_fallback_engine(database_url)
        test_engine(fallback_engine)

        return (
            fallback_engine,
            "Top-level DATABASE_URL",
        )

    attempted_text = ", ".join(attempted_names) or "none"

    raise RuntimeError(
        "No working Streamlit SQL connection was found. "
        f"Connection names checked: {attempted_text}. "
        "The Request Shipment page now uses the same "
        "[connections.<name>] configuration as the rest of the app."
    )


def verify_required_tables(database: Any) -> None:
    """Stop before inserting if required Solomon Shipping tables are absent."""

    required_tables = [
        "customers",
        "shipments",
        "pickup_schedule",
        "status_history",
    ]

    missing_tables: list[str] = []

    for table_name in required_tables:
        relation_name = f"{DATABASE_SCHEMA}.{table_name}"

        existing_relation = database.execute(
            text("SELECT TO_REGCLASS(:relation_name);"),
            {"relation_name": relation_name},
        ).scalar_one_or_none()

        if existing_relation is None:
            missing_tables.append(relation_name)

    if missing_tables:
        raise RuntimeError(
            "These required Neon tables are missing: "
            + ", ".join(missing_tables)
        )


def acquire_customer_lock(database: Any) -> None:
    """Serialize customer lookup and creation during simultaneous submissions."""

    database.execute(
        text(
            """
            SELECT PG_ADVISORY_XACT_LOCK(
                HASHTEXT(:lock_name)
            );
            """
        ),
        {"lock_name": "solomon_shipping.customer_create"},
    )


def next_customer_id(database: Any) -> str:
    """Generate the next readable customer ID, such as CUST-012."""

    database.execute(
        text(
            """
            SELECT PG_ADVISORY_XACT_LOCK(
                HASHTEXT(:lock_name)
            );
            """
        ),
        {"lock_name": "solomon_shipping.customer_id"},
    )

    next_number = database.execute(
        text(
            f"""
            SELECT COALESCE(
                MAX(SPLIT_PART(customer_id, '-', 2)::INTEGER),
                0
            ) + 1
            FROM {DATABASE_SCHEMA}.customers
            WHERE customer_id ~ '^CUST-[0-9]+$';
            """
        )
    ).scalar_one()

    return f"CUST-{int(next_number):03d}"


def next_shipment_id(database: Any, year: int) -> str:
    """Generate the next permanent shipment ID, such as SST-2026-0026."""

    pattern = rf"^SST-{year}-[0-9]+$"

    database.execute(
        text(
            """
            SELECT PG_ADVISORY_XACT_LOCK(
                HASHTEXT(:lock_name)
            );
            """
        ),
        {"lock_name": f"solomon_shipping.shipment_id.{year}"},
    )

    next_number = database.execute(
        text(
            f"""
            SELECT COALESCE(
                MAX(SPLIT_PART(shipment_id, '-', 3)::INTEGER),
                0
            ) + 1
            FROM {DATABASE_SCHEMA}.shipments
            WHERE shipment_id ~ :pattern;
            """
        ),
        {"pattern": pattern},
    ).scalar_one()

    return f"SST-{year}-{int(next_number):04d}"


def next_pickup_id(database: Any, year: int) -> str:
    """Generate the next pickup request ID, such as PU-2026-0026."""

    pattern = rf"^PU-{year}-[0-9]+$"

    database.execute(
        text(
            """
            SELECT PG_ADVISORY_XACT_LOCK(
                HASHTEXT(:lock_name)
            );
            """
        ),
        {"lock_name": f"solomon_shipping.pickup_id.{year}"},
    )

    next_number = database.execute(
        text(
            f"""
            SELECT COALESCE(
                MAX(SPLIT_PART(pickup_id, '-', 3)::INTEGER),
                0
            ) + 1
            FROM {DATABASE_SCHEMA}.pickup_schedule
            WHERE pickup_id ~ :pattern;
            """
        ),
        {"pattern": pattern},
    ).scalar_one()

    return f"PU-{year}-{int(next_number):04d}"


def find_existing_customer_id(
    database: Any,
    customer_name: str,
    phone: str,
    email: str,
) -> str | None:
    """Find a returning customer by email or by matching name and phone."""

    clean_email = email.strip()
    clean_name = customer_name.strip()
    clean_phone = phone.strip()

    if clean_email:
        email_match = database.execute(
            text(
                f"""
                SELECT customer_id
                FROM {DATABASE_SCHEMA}.customers
                WHERE LOWER(BTRIM(email)) = LOWER(BTRIM(:email))
                LIMIT 1;
                """
            ),
            {"email": clean_email},
        ).scalar_one_or_none()

        if email_match:
            return str(email_match)

    name_phone_match = database.execute(
        text(
            f"""
            SELECT customer_id
            FROM {DATABASE_SCHEMA}.customers
            WHERE LOWER(BTRIM(customer_name))
                    = LOWER(BTRIM(:customer_name))
              AND REGEXP_REPLACE(
                    COALESCE(phone, ''),
                    '[^0-9]',
                    '',
                    'g'
                  )
                  =
                  REGEXP_REPLACE(
                    :phone,
                    '[^0-9]',
                    '',
                    'g'
                  )
            LIMIT 1;
            """
        ),
        {
            "customer_name": clean_name,
            "phone": clean_phone,
        },
    ).scalar_one_or_none()

    return str(name_phone_match) if name_phone_match else None


def build_shipment_notes(data: dict[str, Any]) -> str:
    """Combine intake details that do not yet have dedicated table columns."""

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
    """Save the complete request in one Neon transaction."""

    engine, connection_source = resolve_database_engine()

    with engine.begin() as database:
        verify_required_tables(database)
        acquire_customer_lock(database)

        customer_id = find_existing_customer_id(
            database=database,
            customer_name=data["customer_name"],
            phone=data["phone"],
            email=data["email"],
        )

        if customer_id is None:
            customer_id = next_customer_id(database)

            database.execute(
                text(
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
                        :customer_id,
                        :customer_name,
                        :phone,
                        NULLIF(:email, ''),
                        :origin_city,
                        :origin_state,
                        :destination_country,
                        :destination_city,
                        :customer_type,
                        :notes
                    );
                    """
                ),
                {
                    "customer_id": customer_id,
                    "customer_name": data["customer_name"],
                    "phone": data["phone"],
                    "email": data["email"],
                    "origin_city": data["pickup_city"],
                    "origin_state": data["pickup_state"],
                    "destination_country": data["destination_country"],
                    "destination_city": data["destination_city"],
                    "customer_type": data["customer_type"],
                    "notes": f"Preferred contact method: {data['preferred_contact']}",
                },
            )

        else:
            database.execute(
                text(
                    f"""
                    UPDATE {DATABASE_SCHEMA}.customers
                    SET
                        customer_name = :customer_name,
                        phone = :phone,
                        email = COALESCE(NULLIF(:email, ''), email),
                        origin_city = :origin_city,
                        origin_state = :origin_state,
                        destination_country = :destination_country,
                        destination_city = :destination_city,
                        customer_type = :customer_type,
                        notes = :notes
                    WHERE customer_id = :customer_id;
                    """
                ),
                {
                    "customer_name": data["customer_name"],
                    "phone": data["phone"],
                    "email": data["email"],
                    "origin_city": data["pickup_city"],
                    "origin_state": data["pickup_state"],
                    "destination_country": data["destination_country"],
                    "destination_city": data["destination_city"],
                    "customer_type": data["customer_type"],
                    "notes": f"Preferred contact method: {data['preferred_contact']}",
                    "customer_id": customer_id,
                },
            )

        current_year = datetime.now().year
        shipment_id = next_shipment_id(database, current_year)
        pickup_id = next_pickup_id(database, current_year)
        shipment_mode = "Air" if "Air" in data["shipping_option"] else "Sea"

        database.execute(
            text(
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
                    :shipment_id,
                    :customer_id,
                    :customer_name,
                    :shipment_date,
                    :item_type,
                    :quantity,
                    :origin_city,
                    :origin_state,
                    :destination_country,
                    :destination_city,
                    'Request Received',
                    0,
                    0,
                    0,
                    'Unpaid',
                    :notes,
                    :service_type,
                    :shipment_mode,
                    'Pending Review'
                );
                """
            ),
            {
                "shipment_id": shipment_id,
                "customer_id": customer_id,
                "customer_name": data["customer_name"],
                "shipment_date": date.today(),
                "item_type": data["item_type"],
                "quantity": data["quantity"],
                "origin_city": data["pickup_city"],
                "origin_state": data["pickup_state"],
                "destination_country": data["destination_country"],
                "destination_city": data["destination_city"],
                "notes": build_shipment_notes(data),
                "service_type": data["shipping_option"],
                "shipment_mode": shipment_mode,
            },
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

        database.execute(
            text(
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
                    :pickup_id,
                    :shipment_id,
                    :customer_id,
                    :customer_name,
                    :pickup_date,
                    :pickup_time_window,
                    :pickup_address,
                    NULL,
                    'Pending Confirmation',
                    :notes
                );
                """
            ),
            {
                "pickup_id": pickup_id,
                "shipment_id": shipment_id,
                "customer_id": customer_id,
                "customer_name": data["customer_name"],
                "pickup_date": data["preferred_pickup_date"],
                "pickup_time_window": data["preferred_pickup_window"],
                "pickup_address": full_pickup_address,
                "notes": pickup_notes,
            },
        )

        shipment_sequence = shipment_id.rsplit("-", 1)[-1]
        status_id = f"STAT-{current_year}-{shipment_sequence}-01"

        database.execute(
            text(
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
                    :status_id,
                    :shipment_id,
                    'Request Received',
                    CURRENT_TIMESTAMP,
                    :updated_by,
                    :notes
                );
                """
            ),
            {
                "status_id": status_id,
                "shipment_id": shipment_id,
                "updated_by": data["requested_by"],
                "notes": "Shipment request submitted through the Request Shipment page.",
            },
        )

    return {
        "shipment_id": shipment_id,
        "customer_id": customer_id,
        "pickup_id": pickup_id,
        "request_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "request_status": "Request Received",
        "pickup_status": "Pending Confirmation",
        "database_connection": connection_source,
    }


def safe_error_message(error: Exception) -> str:
    """Remove credentials if a driver includes a URL in an error message."""

    message = str(error)

    message = re.sub(
        r"postgres(?:ql)?(?:\+\w+)?://[^@\s]+@",
        "postgresql://***:***@",
        message,
        flags=re.IGNORECASE,
    )

    message = re.sub(
        r"password\s*=\s*[^,\s]+",
        "password=***",
        message,
        flags=re.IGNORECASE,
    )

    return message


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

                st.caption(
                    "Database connection used: "
                    f"{request_record['database_connection']}"
                )

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
                    "The shipment request was not saved, so no Shipment ID was issued."
                )
                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: {safe_error_message(exc)}"
                )

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