from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL

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


def _to_plain_mapping(value: Any) -> Any:
    """
    Convert Streamlit secrets objects into ordinary Python dictionaries/lists
    without exposing any values on the page.
    """

    if hasattr(value, "items"):
        return {
            str(key): _to_plain_mapping(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_to_plain_mapping(item) for item in value]

    return value


def _walk_secret_values(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any]]:
    """Return every nested secret value together with its key path."""

    results: list[tuple[tuple[str, ...], Any]] = []

    if isinstance(value, dict):
        for key, item in value.items():
            results.extend(
                _walk_secret_values(
                    item,
                    (*path, str(key)),
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            results.extend(
                _walk_secret_values(
                    item,
                    (*path, str(index)),
                )
            )
    else:
        results.append((path, value))

    return results


def _looks_like_postgres_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    clean_value = value.strip().lower()

    return clean_value.startswith(
        (
            "postgresql://",
            "postgres://",
            "postgresql+psycopg2://",
        )
    )


def _normalise_postgres_url(database_url: str) -> str:
    """
    SQLAlchemy prefers postgresql://. Neon may provide postgres:// in some
    interfaces, so normalize it before creating the engine.
    """

    clean_url = database_url.strip()

    if clean_url.startswith("postgres://"):
        clean_url = "postgresql://" + clean_url[len("postgres://"):]

    return clean_url


def _secret_key_paths(secret_data: dict[str, Any]) -> list[str]:
    """
    Return key paths only, never secret values. This is safe diagnostic
    information when a configuration cannot be resolved.
    """

    paths: list[str] = []

    for path, _ in _walk_secret_values(secret_data):
        if path:
            paths.append(".".join(path))

    return sorted(set(paths))


def _find_url_in_secrets(
    secret_data: dict[str, Any],
) -> tuple[str, str] | None:
    """
    Find a PostgreSQL URL anywhere in Streamlit Secrets.

    This supports:
      DATABASE_URL = "postgresql://..."
      NEON_DATABASE_URL = "postgresql://..."
      [connections.neon]
      url = "postgresql://..."
      [database]
      connection_string = "postgresql://..."
      and other nested layouts.
    """

    preferred_names = {
        "database_url",
        "neon_database_url",
        "postgres_url",
        "postgresql_url",
        "url",
        "connection_string",
        "connection_url",
        "uri",
    }

    all_values = _walk_secret_values(secret_data)

    # Prefer recognized key names first.
    for path, value in all_values:
        final_key = path[-1].lower() if path else ""

        if final_key in preferred_names and _looks_like_postgres_url(value):
            return (
                _normalise_postgres_url(str(value)),
                f"Streamlit secret: {'.'.join(path)}",
            )

    # Then accept any nested secret value that is clearly a PostgreSQL URL.
    for path, value in all_values:
        if _looks_like_postgres_url(value):
            return (
                _normalise_postgres_url(str(value)),
                f"Streamlit secret: {'.'.join(path)}",
            )

    return None


def _candidate_mappings(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    """Return every nested dictionary as a possible connection configuration."""

    candidates: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    if isinstance(value, dict):
        candidates.append((path, value))

        for key, item in value.items():
            candidates.extend(
                _candidate_mappings(
                    item,
                    (*path, str(key)),
                )
            )

    return candidates


def _mapping_value(
    mapping: dict[str, Any],
    names: tuple[str, ...],
) -> Any:
    """Read a configuration value using case-insensitive aliases."""

    lower_mapping = {
        str(key).lower(): value
        for key, value in mapping.items()
    }

    for name in names:
        if name.lower() in lower_mapping:
            value = lower_mapping[name.lower()]

            if value is not None and str(value).strip():
                return value

    return None


def _find_structured_connection(
    secret_data: dict[str, Any],
) -> tuple[URL, str] | None:
    """
    Support secrets saved as individual fields rather than one URL.

    Examples:
      host, database, username, password, port
      server, dbname, user, password
    """

    for path, mapping in _candidate_mappings(secret_data):
        host = _mapping_value(
            mapping,
            (
                "host",
                "hostname",
                "server",
                "db_host",
                "database_host",
                "neon_host",
            ),
        )
        username = _mapping_value(
            mapping,
            (
                "username",
                "user",
                "db_user",
                "database_user",
                "neon_user",
            ),
        )
        password = _mapping_value(
            mapping,
            (
                "password",
                "pass",
                "db_password",
                "database_password",
                "neon_password",
            ),
        )
        database = _mapping_value(
            mapping,
            (
                "database",
                "dbname",
                "db_name",
                "database_name",
                "neon_database",
            ),
        )

        if not all((host, username, password, database)):
            continue

        port_value = _mapping_value(
            mapping,
            ("port", "db_port", "database_port"),
        )
        sslmode = _mapping_value(
            mapping,
            ("sslmode", "ssl_mode"),
        ) or "require"

        try:
            port = int(port_value) if port_value else 5432
        except (TypeError, ValueError):
            port = 5432

        database_url = URL.create(
            drivername="postgresql+psycopg2",
            username=str(username).strip(),
            password=str(password),
            host=str(host).strip(),
            port=port,
            database=str(database).strip(),
            query={"sslmode": str(sslmode).strip()},
        )

        source_path = ".".join(path) if path else "top level"

        return (
            database_url,
            f"Structured Streamlit secrets: {source_path}",
        )

    return None


@st.cache_resource(show_spinner=False)
def create_database_engine(
    database_url: str | URL,
) -> Engine:
    """Create and cache a resilient Neon/PostgreSQL SQLAlchemy engine."""

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
    """Confirm the resolved connection can execute a PostgreSQL query."""

    with engine.connect() as database:
        database.execute(text("SELECT 1;"))


def resolve_database_engine() -> tuple[Engine, str]:
    """
    Resolve the Neon connection without assuming a specific secret key name.

    The earlier version checked only a short list of Streamlit connection names
    and discarded the underlying errors. This version searches all nested
    Streamlit secrets, supports URL and field-based configurations, and reports
    only secret key paths—not credentials—if it still cannot resolve them.
    """

    # Environment variables are useful locally and on some hosts.
    for environment_key in (
        "DATABASE_URL",
        "NEON_DATABASE_URL",
        "POSTGRES_URL",
        "POSTGRESQL_URL",
    ):
        environment_value = os.getenv(environment_key, "").strip()

        if not environment_value:
            continue

        engine = create_database_engine(
            _normalise_postgres_url(environment_value)
        )
        test_engine(engine)

        return (
            engine,
            f"Environment variable: {environment_key}",
        )

    try:
        secret_data = _to_plain_mapping(st.secrets)
    except FileNotFoundError:
        secret_data = {}
    except Exception as exc:
        raise RuntimeError(
            "Streamlit could not read its secrets configuration. "
            f"{type(exc).__name__}: {safe_error_message(exc)}"
        ) from exc

    url_result = _find_url_in_secrets(secret_data)

    if url_result:
        database_url, source = url_result
        engine = create_database_engine(database_url)
        test_engine(engine)

        return engine, source

    structured_result = _find_structured_connection(secret_data)

    if structured_result:
        database_url, source = structured_result
        engine = create_database_engine(database_url)
        test_engine(engine)

        return engine, source

    available_paths = _secret_key_paths(secret_data)
    path_text = ", ".join(available_paths) if available_paths else "none"

    raise RuntimeError(
        "No PostgreSQL credential was found in the secrets available to this "
        "running app. Available secret key paths (values hidden): "
        f"{path_text}. "
        "A CSV file does not provide a database connection."
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