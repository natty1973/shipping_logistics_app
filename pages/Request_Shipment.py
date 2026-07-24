from __future__ import annotations

import os
import re
from datetime import date, datetime
from html import escape
from io import BytesIO
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.styles import (
    apply_custom_styles,
    hero,
    render_back_to_home,
    sidebar_shipping_options,
)


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

PREFERRED_WINDOWS = [
    "Morning",
    "Afternoon",
    "Evening",
    "Flexible",
]

# ------------------------------------------------------------------
# PLACEHOLDER STARTING RATES
# ------------------------------------------------------------------
# These sample rates are intentionally labeled as estimates. They are
# benchmarked against publicly advertised Caribbean shipping rates and
# should be replaced with Solomon Shipping's approved commercial rate card.
GYD_PER_USD = 210.45

GUYANA_DESTINATION_ZONES = [
    "Georgetown",
    "East Bank Demerara",
    "East Coast Demerara",
    "West Demerara",
    "Linden",
    "Berbice",
    "Essequibo",
    "Other / Manual Quote",
]

DELIVERY_METHODS = [
    "Warehouse Pickup in Guyana",
    "Door-to-Door Delivery in Guyana",
]

PICKUP_FEE_USD = {
    "Warehouse Drop-Off — Orange, NJ": 0.00,
    "New Jersey — Orange / Newark": 20.00,
    "New Jersey — Jersey City / Secaucus / Bayonne": 25.00,
    "New Jersey — Central NJ / Raritan": 40.00,
    "New York — Queens / Brooklyn": 35.00,
    "New York — Bronx / Manhattan": 45.00,
    "New York — Staten Island": 45.00,
    "New York — Long Island": 60.00,
    "Other": 75.00,
}

PICKUP_AREAS = list(PICKUP_FEE_USD.keys())

DOOR_DELIVERY_FEE_USD = {
    "Georgetown": 20.00,
    "East Bank Demerara": 30.00,
    "East Coast Demerara": 35.00,
    "West Demerara": 40.00,
    "Linden": 55.00,
    "Berbice": 70.00,
    "Essequibo": 85.00,
    "Other / Manual Quote": 0.00,
}

SEA_STARTING_RATES_USD = {
    "Standard Sea — 4–6 Weeks": {
        "Barrel": 125.00,
        "Box": 75.00,
        "Crate": 135.00,
        "Suitcase": 95.00,
        "Document": 35.00,
        "Household Goods": 150.00,
        "Electronics": 95.00,
        "Food Items": 75.00,
        "Clothing": 75.00,
        "Other": 100.00,
    },
    "Express Sea — Approx. 3 Weeks": {
        "Barrel": 150.00,
        "Box": 95.00,
        "Crate": 165.00,
        "Suitcase": 115.00,
        "Document": 50.00,
        "Household Goods": 185.00,
        "Electronics": 120.00,
        "Food Items": 95.00,
        "Clothing": 95.00,
        "Other": 125.00,
    },
}

AIR_RATE_PER_LB_USD = {
    "Standard Air — 7–10 Business Days": 3.00,
    "Express Air — 3–5 Business Days": 3.40,
}

AIR_MINIMUM_USD = {
    "Standard Air — 7–10 Business Days": 45.00,
    "Express Air — 3–5 Business Days": 55.00,
}

ASSUMED_WEIGHT_LBS = {
    "Barrel": 100.0,
    "Box": 25.0,
    "Crate": 75.0,
    "Suitcase": 40.0,
    "Document": 1.0,
    "Household Goods": 100.0,
    "Electronics": 30.0,
    "Food Items": 25.0,
    "Clothing": 25.0,
    "Other": 35.0,
}


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



def parse_number(value: Any) -> float:
    """Extract the first numeric value from a form or stored text value."""

    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        str(value).replace(",", ""),
    )

    if not match:
        return 0.0

    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def calculate_estimated_quote(
    *,
    shipping_option: str,
    item_type: str,
    quantity: int,
    estimated_weight_lbs: float,
    pickup_area: str,
    destination_country: str,
    destination_zone: str,
    delivery_method: str,
    special_handling: list[str],
    declared_value_usd: float,
) -> dict[str, Any]:
    """
    Calculate a transparent placeholder starting estimate.

    Air uses a public-rate benchmark per pound. Sea uses a practical
    item-based starting price, with a barrel benchmark of US$125 for
    standard sea and a modest premium for express sea.
    """

    quantity_value = max(int(quantity), 1)
    entered_weight = max(float(estimated_weight_lbs or 0), 0.0)

    assumed_weight = (
        ASSUMED_WEIGHT_LBS.get(
            item_type,
            35.0,
        )
        * quantity_value
    )

    billable_weight = (
        entered_weight
        if entered_weight > 0
        else assumed_weight
    )

    used_assumed_weight = entered_weight <= 0

    if "Air" in shipping_option:
        rate_per_lb = AIR_RATE_PER_LB_USD[
            shipping_option
        ]

        minimum_charge = AIR_MINIMUM_USD[
            shipping_option
        ]

        freight_usd = max(
            billable_weight * rate_per_lb,
            minimum_charge,
        )

        pricing_basis = (
            f"{billable_weight:,.1f} lb × "
            f"US${rate_per_lb:,.2f}/lb"
        )

    else:
        item_rates = SEA_STARTING_RATES_USD[
            shipping_option
        ]

        rate_per_item = item_rates.get(
            item_type,
            item_rates["Other"],
        )

        freight_usd = (
            rate_per_item
            * quantity_value
        )

        pricing_basis = (
            f"{quantity_value} × "
            f"{item_type} starting rate "
            f"of US${rate_per_item:,.2f}"
        )

    pickup_fee_usd = PICKUP_FEE_USD.get(
        pickup_area,
        PICKUP_FEE_USD["Other"],
    )

    if (
        destination_country == "Guyana"
        and delivery_method
        == "Door-to-Door Delivery in Guyana"
    ):
        destination_delivery_fee_usd = (
            DOOR_DELIVERY_FEE_USD.get(
                destination_zone,
                0.0,
            )
        )
    else:
        destination_delivery_fee_usd = 0.0

    handling_items = {
        item.strip()
        for item in special_handling
        if item.strip()
        and item != "No Special Handling"
    }

    special_handling_fee_usd = 0.0

    if "Fragile" in handling_items:
        special_handling_fee_usd += 15.0

    if "Heavy Item" in handling_items:
        special_handling_fee_usd += 20.0

    if "Keep Dry" in handling_items:
        special_handling_fee_usd += 5.0

    insurance_fee_usd = round(
        max(
            float(declared_value_usd or 0),
            0.0,
        )
        * 0.015,
        2,
    )

    manual_quote_required = (
        destination_country != "Guyana"
        or destination_zone
        == "Other / Manual Quote"
        or pickup_area == "Other"
    )

    subtotal_usd = (
        freight_usd
        + pickup_fee_usd
        + destination_delivery_fee_usd
        + special_handling_fee_usd
        + insurance_fee_usd
    )

    estimated_total_usd = round(
        subtotal_usd,
        2,
    )

    estimated_total_gyd = round(
        estimated_total_usd
        * GYD_PER_USD,
        2,
    )

    return {
        "freight_usd": round(
            freight_usd,
            2,
        ),
        "pickup_fee_usd": round(
            pickup_fee_usd,
            2,
        ),
        "destination_delivery_fee_usd": round(
            destination_delivery_fee_usd,
            2,
        ),
        "special_handling_fee_usd": round(
            special_handling_fee_usd,
            2,
        ),
        "insurance_fee_usd": insurance_fee_usd,
        "estimated_total_usd": estimated_total_usd,
        "estimated_total_gyd": estimated_total_gyd,
        "exchange_rate_gyd_per_usd": GYD_PER_USD,
        "pricing_basis": pricing_basis,
        "billable_weight_lbs": round(
            billable_weight,
            1,
        ),
        "used_assumed_weight": used_assumed_weight,
        "manual_quote_required": manual_quote_required,
        "quote_status": (
            "Manual Review Required"
            if manual_quote_required
            else "Starting Estimate"
        ),
    }


def render_quote_estimate(
    quote: dict[str, Any],
) -> None:
    """Render the customer-facing USD and GYD starting estimate."""

    st.markdown(
        "### Estimated Starting Price"
    )

    first, second, third = st.columns(3)

    with first:
        st.metric(
            "Estimated Total (USD)",
            f"US${quote['estimated_total_usd']:,.2f}",
        )

    with second:
        st.metric(
            "Estimated Equivalent (GYD)",
            f"G${quote['estimated_total_gyd']:,.2f}",
        )

    with third:
        st.metric(
            "Quote Status",
            quote["quote_status"],
        )

    breakdown = pd.DataFrame(
        [
            {
                "Price Component": "Base Freight",
                "Amount (USD)": (
                    quote["freight_usd"]
                ),
            },
            {
                "Price Component": "U.S. Pickup",
                "Amount (USD)": (
                    quote["pickup_fee_usd"]
                ),
            },
            {
                "Price Component": "Guyana Delivery",
                "Amount (USD)": (
                    quote[
                        "destination_delivery_fee_usd"
                    ]
                ),
            },
            {
                "Price Component": "Special Handling",
                "Amount (USD)": (
                    quote[
                        "special_handling_fee_usd"
                    ]
                ),
            },
            {
                "Price Component": "Declared-Value Protection",
                "Amount (USD)": (
                    quote["insurance_fee_usd"]
                ),
            },
        ]
    )

    st.dataframe(
        breakdown,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Pricing basis: "
        f"{quote['pricing_basis']}. "
        f"GYD conversion uses US$1 = "
        f"G${quote['exchange_rate_gyd_per_usd']:,.2f}."
    )

    if quote["used_assumed_weight"]:
        st.info(
            "No weight was entered, so the estimate uses a "
            "reasonable placeholder weight for the selected item."
        )

    if quote["manual_quote_required"]:
        st.warning(
            "This route needs staff review. The displayed amount is "
            "only a starting estimate and may change."
        )

    st.info(
        "This is a placeholder starting estimate, not the final invoice. "
        "Solomon Shipping may adjust the price after inspecting, weighing, "
        "or measuring the shipment and confirming pickup, delivery, customs, "
        "and carrier requirements."
    )



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
        f"Destination zone: {data['destination_zone']}",
        f"Delivery method: {data['delivery_method']}",
        f"Quote status: {data['quote_status']}",
        f"Pricing basis: {data['pricing_basis']}",
        f"Estimated freight USD: {data['freight_usd']:.2f}",
        f"US pickup fee USD: {data['pickup_fee_usd']:.2f}",
        (
            "Guyana delivery fee USD: "
            f"{data['destination_delivery_fee_usd']:.2f}"
        ),
        (
            "Special handling fee USD: "
            f"{data['special_handling_fee_usd']:.2f}"
        ),
        f"Insurance fee USD: {data['insurance_fee_usd']:.2f}",
        f"Estimated total USD: {data['estimated_total_usd']:.2f}",
        f"Estimated total GYD: {data['estimated_total_gyd']:.2f}",
        (
            "Exchange rate GYD per USD: "
            f"{data['exchange_rate_gyd_per_usd']:.2f}"
        ),
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
                    :amount_charged,
                    0,
                    :balance_due,
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
                "amount_charged": data["estimated_total_usd"],
                "balance_due": data["estimated_total_usd"],
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
        "amount_charged": data["estimated_total_usd"],
        "balance_due": data["estimated_total_usd"],
        "payment_status": "Unpaid",
        "release_status": "Pending Review",
        "shipment_mode": shipment_mode,
    }



def _confirmation_value(
    value: Any,
    default: str = "Not provided",
) -> str:
    """Convert nullable values into clean confirmation text."""

    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    if isinstance(value, datetime):
        return value.strftime("%B %d, %Y at %I:%M %p")

    if isinstance(value, date):
        return value.strftime("%B %d, %Y")

    clean_value = str(value).strip()

    return clean_value or default


def _format_usd(value: Any) -> str:
    """Format a value as U.S. dollars for confirmations."""

    return f"US${parse_number(value):,.2f}"


def _format_gyd(value: Any) -> str:
    """Format a value as Guyana dollars for confirmations."""

    return f"G${parse_number(value):,.2f}"


def _pdf_safe_text(value: Any) -> str:
    """Prepare text for ReportLab's built-in fonts and Paragraph markup."""

    clean_value = _confirmation_value(value)

    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
    }

    for original, replacement in replacements.items():
        clean_value = clean_value.replace(original, replacement)

    return escape(clean_value).replace("\n", "<br/>")


def _pdf_paragraph(
    value: Any,
    style: ParagraphStyle,
) -> Paragraph:
    return Paragraph(
        _pdf_safe_text(value),
        style,
    )


def _pdf_section_table(
    title: str,
    rows: list[tuple[str, Any]],
    label_style: ParagraphStyle,
    value_style: ParagraphStyle,
    section_style: ParagraphStyle,
) -> list[Any]:
    """Build a branded two-column section for the confirmation PDF."""

    section_rows: list[list[Any]] = [
        [
            Paragraph(
                _pdf_safe_text(title),
                section_style,
            ),
            "",
        ]
    ]

    for label, value in rows:
        section_rows.append(
            [
                _pdf_paragraph(label, label_style),
                _pdf_paragraph(value, value_style),
            ]
        )

    table = Table(
        section_rows,
        colWidths=[1.75 * inch, 5.05 * inch],
        repeatRows=1,
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                (
                    "SPAN",
                    (0, 0),
                    (1, 0),
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (1, 0),
                    colors.HexColor("#0B6E4F"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (1, 0),
                    colors.white,
                ),
                (
                    "BACKGROUND",
                    (0, 1),
                    (0, -1),
                    colors.HexColor("#F1F7F4"),
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#D6E4DE"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    return [
        table,
        Spacer(1, 0.14 * inch),
    ]


def _draw_confirmation_footer(
    canvas: Any,
    document: Any,
) -> None:
    """Draw a consistent footer on every PDF page."""

    canvas.saveState()
    page_width, _ = letter

    canvas.setStrokeColor(
        colors.HexColor("#D6E4DE")
    )
    canvas.line(
        0.55 * inch,
        0.48 * inch,
        page_width - 0.55 * inch,
        0.48 * inch,
    )

    canvas.setFont(
        "Helvetica",
        8,
    )
    canvas.setFillColor(
        colors.HexColor("#4B5563")
    )
    canvas.drawString(
        0.55 * inch,
        0.29 * inch,
        "Solomon Shipping and Trading Inc. | 973-675-4921",
    )
    canvas.drawRightString(
        page_width - 0.55 * inch,
        0.29 * inch,
        f"Page {document.page}",
    )

    canvas.setFont(
        "Helvetica-Oblique",
        7,
    )
    canvas.setFillColor(
        colors.HexColor("#0B6E4F")
    )
    canvas.drawRightString(
        page_width - 0.55 * inch,
        0.16 * inch,
        "Developed by Niota Labs LLC",
    )

    canvas.restoreState()


def build_shipment_confirmation_pdf(
    record: dict[str, Any],
) -> bytes:
    """Create a polished Shipment Request Confirmation PDF in memory."""

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.65 * inch,
        title=(
            "Shipment Request Confirmation - "
            f"{record.get('shipment_id', '')}"
        ),
        author="Solomon Shipping and Trading Inc.",
        subject="Shipment Request Confirmation",
    )

    styles = getSampleStyleSheet()

    company_style = ParagraphStyle(
        "ConfirmationCompany",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        textColor=colors.HexColor("#0B6E4F"),
        alignment=TA_LEFT,
        spaceAfter=2,
    )

    contact_style = ParagraphStyle(
        "ConfirmationContact",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#4B5563"),
    )

    title_style = ParagraphStyle(
        "ConfirmationTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=17,
        textColor=colors.HexColor("#111827"),
        alignment=TA_CENTER,
    )

    shipment_id_style = ParagraphStyle(
        "ConfirmationShipmentId",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#B42318"),
        alignment=TA_CENTER,
    )

    notice_style = ParagraphStyle(
        "ConfirmationNotice",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#5B4300"),
        alignment=TA_LEFT,
    )

    section_style = ParagraphStyle(
        "ConfirmationSection",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.white,
    )

    label_style = ParagraphStyle(
        "ConfirmationLabel",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1F2937"),
    )

    value_style = ParagraphStyle(
        "ConfirmationValue",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#111827"),
    )

    small_style = ParagraphStyle(
        "ConfirmationSmall",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#4B5563"),
    )

    story: list[Any] = []

    header_table = Table(
        [
            [
                Paragraph(
                    "Solomon Shipping and Trading Inc.",
                    company_style,
                ),
                Paragraph(
                    "SHIPMENT REQUEST<br/>CONFIRMATION",
                    title_style,
                ),
            ],
            [
                Paragraph(
                    (
                        "200 Main St Rear<br/>"
                        "City of Orange, NJ 07050<br/>"
                        "Phone: 973-675-4921"
                    ),
                    contact_style,
                ),
                Paragraph(
                    _pdf_safe_text(
                        record.get("shipment_id")
                    ),
                    shipment_id_style,
                ),
            ],
        ],
        colWidths=[3.85 * inch, 2.95 * inch],
        hAlign="LEFT",
    )

    header_table.setStyle(
        TableStyle(
            [
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    1,
                    colors.HexColor("#0B6E4F"),
                ),
                (
                    "LINEBELOW",
                    (0, 0),
                    (-1, 0),
                    0.5,
                    colors.HexColor("#D6E4DE"),
                ),
                (
                    "BACKGROUND",
                    (1, 0),
                    (1, -1),
                    colors.HexColor("#FFF7D6"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    story.append(header_table)
    story.append(Spacer(1, 0.14 * inch))

    notice_table = Table(
        [
            [
                Paragraph(
                    (
                        "This document confirms that Solomon Shipping received "
                        "the shipment request and records the starting estimate "
                        "shown below. It is not the final invoice and it does not "
                        "confirm the official pickup window. Staff may adjust the "
                        "price after inspection, weighing, measurement, customs, "
                        "carrier, pickup, and delivery review."
                    ),
                    notice_style,
                )
            ]
        ],
        colWidths=[6.8 * inch],
    )

    notice_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor("#FFF4C2"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.75,
                    colors.HexColor("#E0B400"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    story.append(notice_table)
    story.append(Spacer(1, 0.14 * inch))

    price_summary_table = Table(
        [
            [
                Paragraph(
                    "<b>ESTIMATED STARTING PRICE</b>",
                    section_style,
                ),
                Paragraph(
                    (
                        "<b>"
                        f"{_pdf_safe_text(_format_usd(record.get('estimated_total_usd')))}"
                        "</b>"
                    ),
                    shipment_id_style,
                ),
                Paragraph(
                    (
                        "<b>"
                        f"{_pdf_safe_text(_format_gyd(record.get('estimated_total_gyd')))}"
                        "</b><br/>"
                        "<font size='7.5'>Estimated GYD equivalent</font>"
                    ),
                    title_style,
                ),
            ]
        ],
        colWidths=[
            2.65 * inch,
            2.0 * inch,
            2.15 * inch,
        ],
    )

    price_summary_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, 0),
                    colors.HexColor("#0B6E4F"),
                ),
                (
                    "BACKGROUND",
                    (1, 0),
                    (-1, 0),
                    colors.HexColor("#E6F4EF"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.9,
                    colors.HexColor("#0B6E4F"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#B8D7CB"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "ALIGN",
                    (1, 0),
                    (-1, -1),
                    "CENTER",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]
        )
    )

    story.append(price_summary_table)
    story.append(Spacer(1, 0.14 * inch))

    key_information = [
        [
            _pdf_paragraph(
                "Request Date",
                label_style,
            ),
            _pdf_paragraph(
                record.get("request_date"),
                value_style,
            ),
            _pdf_paragraph(
                "Shipment Status",
                label_style,
            ),
            _pdf_paragraph(
                record.get("request_status"),
                value_style,
            ),
        ],
        [
            _pdf_paragraph(
                "Customer ID",
                label_style,
            ),
            _pdf_paragraph(
                record.get("customer_id"),
                value_style,
            ),
            _pdf_paragraph(
                "Pickup Status",
                label_style,
            ),
            _pdf_paragraph(
                record.get("pickup_status"),
                value_style,
            ),
        ],
        [
            _pdf_paragraph(
                "Pickup Request ID",
                label_style,
            ),
            _pdf_paragraph(
                record.get("pickup_id"),
                value_style,
            ),
            _pdf_paragraph(
                "Entered From",
                label_style,
            ),
            _pdf_paragraph(
                record.get("entered_from_portal"),
                value_style,
            ),
        ],
    ]

    key_table = Table(
        key_information,
        colWidths=[1.25 * inch, 2.15 * inch, 1.25 * inch, 2.15 * inch],
    )

    key_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#F1F7F4"),
                ),
                (
                    "BACKGROUND",
                    (2, 0),
                    (2, -1),
                    colors.HexColor("#F1F7F4"),
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#D6E4DE"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    story.append(key_table)
    story.append(Spacer(1, 0.14 * inch))

    pickup_full_address = record.get("pickup_full_address")

    if not _confirmation_value(
        pickup_full_address,
        "",
    ):
        pickup_full_address = ", ".join(
            part
            for part in [
                _confirmation_value(
                    record.get("pickup_address"),
                    "",
                ),
                _confirmation_value(
                    record.get("pickup_city"),
                    "",
                ),
                _confirmation_value(
                    record.get("pickup_state"),
                    "",
                ),
                _confirmation_value(
                    record.get("pickup_zip"),
                    "",
                ),
            ]
            if part
        )

    sections = [
        (
            "Customer Information",
            [
                (
                    "Customer Name",
                    record.get("customer_name"),
                ),
                (
                    "Phone Number",
                    record.get("phone"),
                ),
                (
                    "Email Address",
                    record.get("email"),
                ),
                (
                    "Customer Type",
                    record.get("customer_type"),
                ),
                (
                    "Preferred Contact",
                    record.get("preferred_contact"),
                ),
                (
                    "Request Entered By",
                    record.get("requested_by"),
                ),
            ],
        ),
        (
            "Preferred Pickup Information",
            [
                (
                    "Pickup Address",
                    pickup_full_address,
                ),
                (
                    "Pickup Area / Route",
                    record.get("pickup_area"),
                ),
                (
                    "Preferred Pickup Date",
                    record.get("preferred_pickup_date"),
                ),
                (
                    "Preferred Pickup Window",
                    record.get("preferred_pickup_window"),
                ),
                (
                    "Pickup Flexibility",
                    record.get("pickup_flexibility"),
                ),
                (
                    "Pickup Notes",
                    record.get("pickup_notes"),
                ),
            ],
        ),
        (
            "Destination and Recipient",
            [
                (
                    "Destination Country",
                    record.get("destination_country"),
                ),
                (
                    "Destination City / Area",
                    record.get("destination_city"),
                ),
                (
                    "Recipient Name",
                    record.get("recipient_name"),
                ),
                (
                    "Recipient Phone",
                    record.get("recipient_phone"),
                ),
            ],
        ),
        (
            "Shipment Details",
            [
                (
                    "Item Type",
                    record.get("item_type"),
                ),
                (
                    "Quantity",
                    record.get("quantity"),
                ),
                (
                    "Estimated Weight",
                    record.get("estimated_weight"),
                ),
                (
                    "Preferred Shipping Option",
                    record.get("shipping_option"),
                ),
                (
                    "Shipment Mode",
                    record.get("shipment_mode"),
                ),
                (
                    "Declared Value",
                    record.get("declared_value"),
                ),
                (
                    "Special Handling",
                    record.get("special_handling"),
                ),
                (
                    "Additional Shipment Notes",
                    record.get("shipment_notes"),
                ),
            ],
        ),
        (
            "Estimated Starting Price",
            [
                (
                    "Quote Status",
                    record.get("quote_status"),
                ),
                (
                    "Pricing Basis",
                    record.get("pricing_basis"),
                ),
                (
                    "Base Freight",
                    _format_usd(
                        record.get("freight_usd")
                    ),
                ),
                (
                    "U.S. Pickup Fee",
                    _format_usd(
                        record.get("pickup_fee_usd")
                    ),
                ),
                (
                    "Guyana Delivery Fee",
                    _format_usd(
                        record.get(
                            "destination_delivery_fee_usd"
                        )
                    ),
                ),
                (
                    "Special Handling Fee",
                    _format_usd(
                        record.get(
                            "special_handling_fee_usd"
                        )
                    ),
                ),
                (
                    "Declared-Value Protection",
                    _format_usd(
                        record.get("insurance_fee_usd")
                    ),
                ),
                (
                    "Estimated Total (USD)",
                    _format_usd(
                        record.get("estimated_total_usd")
                    ),
                ),
                (
                    "Estimated Equivalent (GYD)",
                    _format_gyd(
                        record.get("estimated_total_gyd")
                    ),
                ),
                (
                    "Exchange Rate Used",
                    (
                        "US$1 = G$"
                        f"{parse_number(record.get('exchange_rate_gyd_per_usd')):,.2f}"
                    ),
                ),
                (
                    "Destination Zone",
                    record.get("destination_zone"),
                ),
                (
                    "Delivery Method",
                    record.get("delivery_method"),
                ),
            ],
        ),
        (
            "Payment Preference",
            [
                (
                    "Payment Preference",
                    record.get("payment_terms"),
                ),
                (
                    "Payment Notes",
                    record.get("payment_notes"),
                ),
                (
                    "Current Payment Status",
                    record.get("payment_status"),
                ),
                (
                    "Current Release Status",
                    record.get("release_status"),
                ),
            ],
        ),
    ]

    for section_title, section_rows in sections:
        story.extend(
            _pdf_section_table(
                section_title,
                section_rows,
                label_style,
                value_style,
                section_style,
            )
        )

    story.append(
        Paragraph(
            (
                "Keep this confirmation for your records. Use the Shipment ID "
                "when contacting Solomon Shipping, checking shipment status, "
                "reviewing payment information, or requesting changes."
            ),
            small_style,
        )
    )

    document.build(
        story,
        onFirstPage=_draw_confirmation_footer,
        onLaterPages=_draw_confirmation_footer,
    )

    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


def _parse_labeled_notes(notes: Any) -> dict[str, str]:
    """Parse the labeled lines stored in the shipment notes column."""

    parsed: dict[str, str] = {}
    clean_notes = _confirmation_value(
        notes,
        "",
    )

    for line in clean_notes.splitlines():
        if ":" not in line:
            continue

        label, value = line.split(
            ":",
            1,
        )

        parsed[label.strip().lower()] = (
            value.strip()
        )

    return parsed


def load_saved_shipment_confirmation(
    shipment_id: str,
    phone: str,
) -> dict[str, Any] | None:
    """
    Retrieve a previously saved request using an exact Shipment ID and phone.

    Requiring both values prevents a public user from downloading another
    customer's confirmation by guessing only a Shipment ID.
    """

    engine, _ = resolve_database_engine()

    with engine.connect() as database:
        verify_required_tables(database)

        row = database.execute(
            text(
                f"""
                SELECT
                    s.shipment_id,
                    s.customer_id,
                    s.customer_name,
                    s.shipment_date,
                    s.item_type,
                    s.quantity,
                    s.origin_city,
                    s.origin_state,
                    s.destination_country,
                    s.destination_city,
                    s.current_status,
                    s.amount_charged,
                    s.amount_paid,
                    s.balance_due,
                    s.payment_status,
                    s.release_status,
                    s.notes AS shipment_notes,
                    s.service_type,
                    s.shipment_mode,
                    c.phone,
                    c.email,
                    c.customer_type,
                    p.pickup_id,
                    p.pickup_date,
                    p.pickup_time_window,
                    p.pickup_address,
                    p.pickup_status,
                    p.notes AS pickup_record_notes,
                    (
                        SELECT sh.status_date
                        FROM {DATABASE_SCHEMA}.status_history sh
                        WHERE sh.shipment_id = s.shipment_id
                        ORDER BY sh.status_date ASC
                        LIMIT 1
                    ) AS submitted_at,
                    (
                        SELECT sh.updated_by
                        FROM {DATABASE_SCHEMA}.status_history sh
                        WHERE sh.shipment_id = s.shipment_id
                        ORDER BY sh.status_date ASC
                        LIMIT 1
                    ) AS requested_by
                FROM {DATABASE_SCHEMA}.shipments s
                LEFT JOIN {DATABASE_SCHEMA}.customers c
                    ON c.customer_id = s.customer_id
                LEFT JOIN LATERAL (
                    SELECT pickup_record.*
                    FROM {DATABASE_SCHEMA}.pickup_schedule pickup_record
                    WHERE pickup_record.shipment_id = s.shipment_id
                    ORDER BY
                        pickup_record.pickup_date DESC NULLS LAST,
                        pickup_record.pickup_id DESC
                    LIMIT 1
                ) p ON TRUE
                WHERE
                    UPPER(BTRIM(s.shipment_id))
                    = UPPER(BTRIM(:shipment_id))
                    AND REGEXP_REPLACE(
                        COALESCE(c.phone, ''),
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
                "shipment_id": (
                    shipment_id.strip().upper()
                ),
                "phone": phone.strip(),
            },
        ).mappings().first()

    if row is None:
        return None

    row_data = dict(row)
    note_fields = _parse_labeled_notes(
        row_data.get("shipment_notes")
    )

    return {
        "shipment_id": row_data.get("shipment_id"),
        "customer_id": row_data.get("customer_id"),
        "pickup_id": row_data.get("pickup_id"),
        "request_date": (
            row_data.get("submitted_at")
            or row_data.get("shipment_date")
        ),
        "request_status": row_data.get("current_status"),
        "pickup_status": row_data.get("pickup_status"),
        "entered_from_portal": "Customer Portal",
        "requested_by": (
            row_data.get("requested_by")
            or "Customer"
        ),
        "customer_name": row_data.get("customer_name"),
        "phone": row_data.get("phone"),
        "email": row_data.get("email"),
        "customer_type": row_data.get("customer_type"),
        "preferred_contact": note_fields.get(
            "preferred contact"
        ),
        "pickup_full_address": row_data.get(
            "pickup_address"
        ),
        "pickup_city": row_data.get("origin_city"),
        "pickup_state": row_data.get("origin_state"),
        "pickup_area": note_fields.get("pickup area"),
        "preferred_pickup_date": row_data.get("pickup_date"),
        "preferred_pickup_window": (
            row_data.get("pickup_time_window")
            or note_fields.get(
                "preferred pickup window"
            )
        ),
        "pickup_flexibility": note_fields.get(
            "pickup flexibility"
        ),
        "pickup_notes": (
            note_fields.get("pickup notes")
            or row_data.get("pickup_record_notes")
        ),
        "destination_country": row_data.get(
            "destination_country"
        ),
        "destination_city": row_data.get(
            "destination_city"
        ),
        "recipient_name": note_fields.get("recipient"),
        "recipient_phone": note_fields.get(
            "recipient phone"
        ),
        "item_type": row_data.get("item_type"),
        "quantity": row_data.get("quantity"),
        "estimated_weight": note_fields.get(
            "estimated weight"
        ),
        "shipping_option": row_data.get("service_type"),
        "shipment_mode": row_data.get("shipment_mode"),
        "declared_value": note_fields.get(
            "declared value"
        ),
        "special_handling": note_fields.get(
            "special handling"
        ),
        "shipment_notes": note_fields.get(
            "shipment notes"
        ),
        "payment_terms": note_fields.get(
            "payment preference"
        ),
        "payment_notes": note_fields.get(
            "payment notes"
        ),
        "destination_zone": note_fields.get(
            "destination zone"
        ),
        "delivery_method": note_fields.get(
            "delivery method"
        ),
        "quote_status": note_fields.get(
            "quote status"
        ),
        "pricing_basis": note_fields.get(
            "pricing basis"
        ),
        "freight_usd": parse_number(
            note_fields.get(
                "estimated freight usd"
            )
        ),
        "pickup_fee_usd": parse_number(
            note_fields.get(
                "us pickup fee usd"
            )
        ),
        "destination_delivery_fee_usd": parse_number(
            note_fields.get(
                "guyana delivery fee usd"
            )
        ),
        "special_handling_fee_usd": parse_number(
            note_fields.get(
                "special handling fee usd"
            )
        ),
        "insurance_fee_usd": parse_number(
            note_fields.get(
                "insurance fee usd"
            )
        ),
        "estimated_total_usd": parse_number(
            note_fields.get(
                "estimated total usd"
            )
        ) or parse_number(
            row_data.get("amount_charged")
        ),
        "estimated_total_gyd": parse_number(
            note_fields.get(
                "estimated total gyd"
            )
        ),
        "exchange_rate_gyd_per_usd": parse_number(
            note_fields.get(
                "exchange rate gyd per usd"
            )
        ) or GYD_PER_USD,
        "amount_charged": row_data.get(
            "amount_charged"
        ),
        "amount_paid": row_data.get(
            "amount_paid"
        ),
        "balance_due": row_data.get(
            "balance_due"
        ),
        "payment_status": row_data.get("payment_status"),
        "release_status": row_data.get("release_status"),
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

    if "retrieved_shipment_confirmation" not in st.session_state:
        st.session_state.retrieved_shipment_confirmation = None

    if "last_shipping_quote" not in st.session_state:
        st.session_state.last_shipping_quote = None

    if "show_saved_confirmation" not in st.session_state:
        st.session_state.show_saved_confirmation = False


def display_confirmation(
    record: dict[str, Any],
    key_prefix: str,
    success_message: str = (
        "Your shipment request was saved successfully."
    ),
) -> None:
    """Show the confirmation and provide a compact customer receipt button."""

    st.success(success_message)

    heading_left, heading_right = st.columns(
        [3.8, 1.2],
        vertical_alignment="bottom",
    )

    with heading_left:
        st.markdown("### Your Shipment ID")
        st.code(
            record["shipment_id"],
            language=None,
        )

    with heading_right:
        pdf_bytes = build_shipment_confirmation_pdf(
            record
        )

        with st.container(
            key=(
                "customer_receipt_download_"
                f"{key_prefix}"
            )
        ):
            st.download_button(
                label="Download Customer Receipt — Price Included",
                data=pdf_bytes,
                file_name=(
                    f"{record['shipment_id']}_"
                    "customer_receipt.pdf"
                ),
                mime="application/pdf",
                key=f"{key_prefix}_pdf_download",
                use_container_width=True,
            )

    st.caption(
        "Keep the Shipment ID and receipt for tracking, "
        "payment lookup, shipment changes, and support."
    )

    first, second, third, fourth = st.columns(4)

    with first:
        st.metric(
            "Shipment Status",
            _confirmation_value(
                record.get("request_status")
            ),
        )

    with second:
        st.metric(
            "Pickup Status",
            _confirmation_value(
                record.get("pickup_status")
            ),
        )

    with third:
        st.metric(
            "Estimated Total (USD)",
            _format_usd(
                record.get("estimated_total_usd")
            ),
        )

    with fourth:
        st.metric(
            "Estimated Equivalent (GYD)",
            _format_gyd(
                record.get("estimated_total_gyd")
            ),
        )

    st.info(
        "The price shown is a placeholder starting estimate. "
        "It is not the final invoice. Solomon Shipping may adjust "
        "the amount after reviewing the shipment, route, pickup, "
        "delivery, customs, weight, and dimensions."
    )


def render_confirmation_retrieval() -> None:
    """Allow a customer to re-download a prior confirmation from Neon."""

    st.subheader(
        "Re-download an Existing Confirmation"
    )

    st.caption(
        "Enter the exact Shipment ID and the phone number "
        "used on the request. Both are required for privacy."
    )

    with st.form(
        "retrieve_shipment_confirmation_form"
    ):
        lookup_left, lookup_right = st.columns(2)

        with lookup_left:
            lookup_shipment_id = st.text_input(
                "Shipment ID",
                placeholder="Example: SST-2026-0026",
            )

        with lookup_right:
            lookup_phone = st.text_input(
                "Phone Number Used on Request"
            )

        retrieve_submitted = st.form_submit_button(
            "Find My Confirmation",
            use_container_width=True,
        )

    if retrieve_submitted:
        if not lookup_shipment_id.strip():
            st.error(
                "Enter the Shipment ID."
            )

        elif not lookup_phone.strip():
            st.error(
                "Enter the phone number used on the request."
            )

        else:
            try:
                with st.spinner(
                    "Finding the saved shipment request..."
                ):
                    saved_record = (
                        load_saved_shipment_confirmation(
                            lookup_shipment_id,
                            lookup_phone,
                        )
                    )

                if saved_record is None:
                    st.session_state.retrieved_shipment_confirmation = None
                    st.error(
                        "No matching request was found. Check the "
                        "Shipment ID and phone number and try again."
                    )

                else:
                    st.session_state.retrieved_shipment_confirmation = (
                        saved_record
                    )

            except Exception as exc:
                st.session_state.retrieved_shipment_confirmation = None
                st.error(
                    "The saved confirmation could not be retrieved."
                )
                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error_message(exc)}"
                )

    if st.session_state.retrieved_shipment_confirmation:
        display_confirmation(
            st.session_state.retrieved_shipment_confirmation,
            key_prefix="retrieved_confirmation",
            success_message=(
                "Your saved shipment request was found."
            ),
        )


def main() -> None:
    apply_custom_styles()
    sidebar_shipping_options()
    initialize_request_storage()

    portal_label = get_portal_label()

    hero(
        title="Request Shipment",
        subtitle=(
            "Enter the shipment details, review a realistic placeholder "
            "starting estimate in U.S. and Guyana dollars, submit the request, "
            "and download a permanent customer receipt."
        ),
    )

    st.markdown(
        f"""
        <span class="badge-green">{portal_label}</span>
        <span class="badge-dark">Instant Starting Estimate</span>
        <span class="badge-red">Final Review Required</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    st.info(
        "Pickup times are preferred availability only. The displayed price "
        "is a placeholder starting estimate and may change after staff reviews "
        "the shipment, route, weight, dimensions, pickup, delivery, customs, "
        "and carrier requirements."
    )

    just_showed_confirmation = bool(
        st.session_state.pop(
            "show_saved_confirmation",
            False,
        )
    )

    if (
        just_showed_confirmation
        and st.session_state.last_shipment_confirmation
    ):
        display_confirmation(
            st.session_state.last_shipment_confirmation,
            key_prefix="saved_confirmation",
            success_message=(
                "Your shipment request was saved successfully. "
                "The customer receipt, including the complete "
                "price calculation, is ready below."
            ),
        )
        st.divider()

    st.subheader("Shipment Request Form")

    with st.form(
        "shipment_request_form",
        clear_on_submit=False,
    ):
        st.markdown("### Customer Information")
        customer_col1, customer_col2 = st.columns(2)

        with customer_col1:
            customer_name = st.text_input(
                "Full Name *"
            )
            phone = st.text_input(
                "Phone Number *"
            )
            email = st.text_input(
                "Email Address"
            )

        with customer_col2:
            customer_type = st.selectbox(
                "Customer Type",
                [
                    "New Customer",
                    "Returning Customer",
                ],
            )
            preferred_contact = st.selectbox(
                "Preferred Contact Method",
                [
                    "Phone",
                    "Email",
                    "WhatsApp",
                    "Text Message",
                ],
            )
            requested_by = st.text_input(
                "Request Entered By",
                value=(
                    "Customer"
                    if portal_label
                    == "Customer Portal"
                    else portal_label
                ),
            )

        st.divider()
        st.markdown(
            "### Preferred U.S. Pickup Information"
        )
        st.caption(
            "Staff will confirm the official two-hour pickup window "
            "after checking route and driver capacity."
        )

        pickup_col1, pickup_col2 = st.columns(2)

        with pickup_col1:
            pickup_address = st.text_input(
                "Pickup Address *"
            )
            pickup_city = st.text_input(
                "Pickup City *"
            )
            pickup_state = st.text_input(
                "Pickup State *",
                value="NJ",
            )
            pickup_zip = st.text_input(
                "Pickup ZIP Code"
            )

        with pickup_col2:
            pickup_area = st.selectbox(
                "U.S. Pickup Zone",
                PICKUP_AREAS,
            )
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
                (
                    "If this time is unavailable, "
                    "can we offer another window?"
                ),
                [
                    "Yes, any available time that day",
                    "Yes, but contact me first",
                    "No, only this window works",
                ],
            )

        pickup_notes = st.text_area(
            "Pickup Notes",
            placeholder=(
                "Add gate code, apartment number, "
                "parking instructions, or best contact person."
            ),
            height=90,
        )

        st.divider()
        st.markdown(
            "### Destination and Delivery"
        )

        destination_col1, destination_col2 = (
            st.columns(2)
        )

        with destination_col1:
            destination_country = st.selectbox(
                "Destination Country *",
                DESTINATION_COUNTRIES,
            )
            destination_city = st.text_input(
                "Destination City / Area *"
            )
            destination_zone = st.selectbox(
                "Guyana Destination Zone",
                GUYANA_DESTINATION_ZONES,
            )

        with destination_col2:
            recipient_name = st.text_input(
                "Recipient Name *"
            )
            recipient_phone = st.text_input(
                "Recipient Phone Number *"
            )
            delivery_method = st.selectbox(
                "Delivery Method in Guyana",
                DELIVERY_METHODS,
            )

        st.divider()
        st.markdown("### Shipment Details")

        shipment_col1, shipment_col2 = (
            st.columns(2)
        )

        with shipment_col1:
            item_type = st.selectbox(
                "Item Type",
                ITEM_TYPES,
            )
            quantity = st.number_input(
                "Quantity",
                min_value=1,
                step=1,
                value=1,
            )
            estimated_weight_lbs = st.number_input(
                "Estimated Total Weight (lb)",
                min_value=0.0,
                step=1.0,
                value=0.0,
                help=(
                    "Leave at 0 when unknown. "
                    "The calculator will use a placeholder "
                    "weight for the selected item."
                ),
            )

        with shipment_col2:
            shipping_option = st.selectbox(
                "Preferred Shipping Option",
                SHIPPING_OPTIONS,
            )
            declared_value_usd = st.number_input(
                "Declared Value (USD), if applicable",
                min_value=0.0,
                step=25.0,
                value=0.0,
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
                default=[
                    "No Special Handling"
                ],
            )

        shipment_notes = st.text_area(
            "Additional Shipment Notes",
            placeholder=(
                "Add item details, delivery notes, "
                "or special requests."
            ),
            height=100,
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
            placeholder=(
                "Example: Sender pays deposit in New Jersey; "
                "receiver pays the balance in Guyana."
            ),
            height=75,
        )

        estimate_acknowledgement = st.checkbox(
            (
                "I understand that the displayed amount is a "
                "starting estimate and not the final invoice."
            )
        )

        button_left, button_right = st.columns(
            [1, 1]
        )

        with button_left:
            calculate_submitted = (
                st.form_submit_button(
                    "Calculate Starting Price",
                    use_container_width=True,
                )
            )

        with button_right:
            submitted = (
                st.form_submit_button(
                    "Submit Shipment Request",
                    use_container_width=True,
                    type="primary",
                )
            )

    quote = calculate_estimated_quote(
        shipping_option=shipping_option,
        item_type=item_type,
        quantity=int(quantity),
        estimated_weight_lbs=(
            float(estimated_weight_lbs)
        ),
        pickup_area=pickup_area,
        destination_country=(
            destination_country
        ),
        destination_zone=(
            destination_zone
        ),
        delivery_method=delivery_method,
        special_handling=(
            special_handling
        ),
        declared_value_usd=(
            float(declared_value_usd)
        ),
    )

    if calculate_submitted:
        st.session_state.last_shipping_quote = (
            quote
        )
        render_quote_estimate(quote)

    if submitted:
        required_fields = {
            "Full Name": customer_name,
            "Phone Number": phone,
            "Pickup Address": pickup_address,
            "Pickup City": pickup_city,
            "Pickup State": pickup_state,
            "Destination City": destination_city,
            "Recipient Name": recipient_name,
            "Recipient Phone Number": (
                recipient_phone
            ),
        }

        missing_fields = [
            label
            for label, value
            in required_fields.items()
            if not str(value).strip()
        ]

        if missing_fields:
            st.error(
                "Please complete these required fields: "
                + ", ".join(missing_fields)
                + "."
            )

        elif not estimate_acknowledgement:
            st.error(
                "Please acknowledge that this is "
                "a starting estimate before submitting."
            )

        else:
            estimated_weight_text = (
                f"{float(estimated_weight_lbs):,.1f} lb"
                if estimated_weight_lbs > 0
                else (
                    f"Assumed "
                    f"{quote['billable_weight_lbs']:,.1f} lb "
                    "for estimate"
                )
            )

            declared_value_text = (
                f"US${float(declared_value_usd):,.2f}"
                if declared_value_usd > 0
                else ""
            )

            form_data = {
                "entered_from_portal": (
                    portal_label
                ),
                "requested_by": (
                    requested_by.strip()
                    or portal_label
                ),
                "customer_name": (
                    customer_name.strip()
                ),
                "phone": phone.strip(),
                "email": email.strip(),
                "customer_type": customer_type,
                "preferred_contact": (
                    preferred_contact
                ),
                "pickup_address": (
                    pickup_address.strip()
                ),
                "pickup_city": (
                    pickup_city.strip()
                ),
                "pickup_state": (
                    pickup_state.strip()
                ),
                "pickup_zip": (
                    pickup_zip.strip()
                ),
                "pickup_area": pickup_area,
                "preferred_pickup_date": (
                    preferred_pickup_date
                ),
                "preferred_pickup_window": (
                    preferred_pickup_window
                ),
                "pickup_flexibility": (
                    pickup_flexibility
                ),
                "pickup_notes": (
                    pickup_notes.strip()
                ),
                "destination_country": (
                    destination_country
                ),
                "destination_city": (
                    destination_city.strip()
                ),
                "destination_zone": (
                    destination_zone
                ),
                "delivery_method": (
                    delivery_method
                ),
                "recipient_name": (
                    recipient_name.strip()
                ),
                "recipient_phone": (
                    recipient_phone.strip()
                ),
                "item_type": item_type,
                "quantity": int(quantity),
                "estimated_weight": (
                    estimated_weight_text
                ),
                "shipping_option": (
                    shipping_option
                ),
                "declared_value": (
                    declared_value_text
                ),
                "special_handling": (
                    ", ".join(
                        special_handling
                    )
                ),
                "shipment_notes": (
                    shipment_notes.strip()
                ),
                "payment_terms": payment_terms,
                "payment_notes": (
                    payment_notes.strip()
                ),
                **quote,
            }

            try:
                render_quote_estimate(quote)

                with st.spinner(
                    "Saving the shipment request "
                    "and generating the Shipment ID..."
                ):
                    database_result = (
                        save_shipment_request(
                            form_data
                        )
                    )

                request_record = {
                    **database_result,
                    **form_data,
                }

                st.session_state.shipment_request_records.append(
                    request_record
                )
                st.session_state.last_shipment_confirmation = (
                    request_record
                )
                st.session_state.last_shipping_quote = (
                    quote
                )

                st.session_state.show_saved_confirmation = True

                # Explicitly remain on the registered Request Shipment page.
                # This prevents Streamlit from returning to the portal's
                # default Home page during the post-submit rerun.
                st.switch_page(
                    "pages/Request_Shipment.py"
                )

            except Exception as exc:
                st.session_state.last_shipment_confirmation = None
                st.error(
                    "The shipment request was not saved, "
                    "so no Shipment ID was issued."
                )
                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error_message(exc)}"
                )

    elif (
        st.session_state.last_shipment_confirmation
        and not just_showed_confirmation
    ):
        with st.expander(
            "View and download the most recent "
            "shipment confirmation"
        ):
            display_confirmation(
                st.session_state[
                    "last_shipment_confirmation"
                ],
                key_prefix=(
                    "recent_confirmation"
                ),
                success_message=(
                    "Your most recent shipment "
                    "confirmation is ready."
                ),
            )

    st.divider()

    render_confirmation_retrieval()

    st.divider()

    if st.session_state.shipment_request_records:
        with st.expander(
            "View submitted requests from this session"
        ):
            session_df = pd.DataFrame(
                st.session_state.shipment_request_records
            )
            st.dataframe(
                session_df,
                use_container_width=True,
            )

    render_back_to_home(
        key="request_shipment_back_to_home"
    )


if __name__ == "__main__":
    main()