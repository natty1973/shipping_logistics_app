from __future__ import annotations

import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(page_title="Payments", page_icon="💳", layout="wide")

SCHEMA = "solomon_shipping"
PAYMENT_LOCATIONS = ["New Jersey Branch", "Guyana Office"]
PAYMENT_METHODS = ["Cash", "Card", "Zelle", "Bank Transfer", "Mobile Money", "Other"]
PAYMENT_TERMS = [
    "Sender Paid / Prepaid",
    "Receiver Paid / Freight Collect",
    "Split Payment",
    "Not Sure Yet",
]
CURRENCIES = ["USD", "GYD", "CAD", "GBP"]


def get_secret(name: str) -> str:
    """Read a database setting from the environment or Streamlit Secrets."""
    value = os.getenv(name, "").strip()
    if value:
        return value

    try:
        value = st.secrets.get(name, "")
    except (FileNotFoundError, KeyError, TypeError, AttributeError):
        return ""

    return str(value).strip() if value is not None else ""


@st.cache_resource(show_spinner=False)
def get_database_engine() -> Engine:
    """Create a reusable Neon/PostgreSQL engine."""
    database_url = get_secret("DATABASE_URL")

    if database_url:
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://") :]
        target: str | URL = database_url
    else:
        values = {
            "user": get_secret("DB_USER"),
            "password": get_secret("DB_PASSWORD"),
            "host": get_secret("DB_HOST"),
            "port": get_secret("DB_PORT") or "5432",
            "database": get_secret("DB_NAME"),
            "sslmode": get_secret("DB_SSLMODE") or "require",
        }

        missing = [
            label
            for key, label in {
                "user": "DB_USER",
                "password": "DB_PASSWORD",
                "host": "DB_HOST",
                "database": "DB_NAME",
            }.items()
            if not values[key]
        ]

        if missing:
            raise RuntimeError("Missing Streamlit Secrets: " + ", ".join(missing))

        try:
            port = int(values["port"])
        except ValueError:
            port = 5432

        target = URL.create(
            "postgresql+psycopg2",
            username=values["user"],
            password=values["password"],
            host=values["host"],
            port=port,
            database=values["database"],
            query={"sslmode": values["sslmode"]},
        )

    engine = create_engine(
        target,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 15,
            "application_name": "solomon_shipping_payments_page",
        },
    )

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return engine


def safe_error_message(error: Exception) -> str:
    """Hide credentials if an error includes a database URL."""
    message = str(error)
    message = re.sub(
        r"postgres(?:ql)?(?:\+\w+)?://[^@\s]+@",
        "postgresql://***:***@",
        message,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"password\s*=\s*[^,\s]+",
        "password=***",
        message,
        flags=re.IGNORECASE,
    )


def safe_text(value: Any, default: str = "Not Available") -> str:
    """Return a clean display string."""
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    value = str(value).strip()
    return value or default


def to_decimal(value: Any) -> Decimal:
    """Convert values to a two-decimal Decimal."""
    if value is None:
        return Decimal("0.00")

    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def format_currency(value: Any, currency: str = "USD") -> str:
    """Format money with a currency symbol."""
    amount = to_decimal(value)
    symbol = {
        "USD": "$",
        "GYD": "G$",
        "CAD": "C$",
        "GBP": "£",
    }.get(currency.upper(), f"{currency.upper()} ")
    return f"{symbol}{amount:,.2f}"


def verify_required_tables(engine: Engine) -> None:
    """Confirm all Payments-page tables exist in Neon."""
    required = [
        f"{SCHEMA}.shipments",
        f"{SCHEMA}.customers",
        f"{SCHEMA}.payments",
        f"{SCHEMA}.branch_payments",
    ]

    missing: list[str] = []

    with engine.connect() as connection:
        for relation_name in required:
            exists = connection.execute(
                text("SELECT TO_REGCLASS(:relation_name)"),
                {"relation_name": relation_name},
            ).scalar_one_or_none()
            if exists is None:
                missing.append(relation_name)

    if missing:
        raise RuntimeError("Required Neon tables are missing: " + ", ".join(missing))


def read_dataframe(
    engine: Engine,
    query: str,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run a read-only SQL query."""
    with engine.connect() as connection:
        return pd.read_sql_query(text(query), connection, params=params or {})


def load_branch_payments(engine: Engine) -> pd.DataFrame:
    """Load branch-payment accounts from Neon."""
    return read_dataframe(
        engine,
        f"""
        SELECT
            bp.branch_payment_id,
            bp.shipment_id,
            bp.invoice_number,
            bp.sender_name,
            bp.receiver_name,
            bp.origin_branch,
            bp.destination_branch,
            bp.payment_terms,
            bp.payment_responsibility,
            bp.amount_charged,
            bp.amount_paid_nj,
            bp.amount_paid_guyana,
            bp.total_amount_paid,
            bp.balance_due,
            bp.payment_collected_at,
            bp.payment_method,
            bp.payment_status,
            bp.release_status,
            bp.collected_by,
            bp.payment_date,
            bp.currency,
            bp.notes,
            bp.created_at,
            bp.updated_at,
            s.customer_id,
            s.customer_name,
            s.current_status AS shipment_status,
            s.destination_city,
            s.destination_country
        FROM {SCHEMA}.branch_payments AS bp
        JOIN {SCHEMA}.shipments AS s
          ON s.shipment_id = bp.shipment_id
        ORDER BY bp.updated_at DESC, bp.shipment_id DESC
        """,
    )


def load_payment_history(engine: Engine) -> pd.DataFrame:
    """Load individual payment transactions from Neon."""
    return read_dataframe(
        engine,
        f"""
        SELECT
            payment_id,
            shipment_id,
            invoice_number,
            customer_id,
            customer_name,
            amount_charged,
            amount_paid,
            balance_due,
            payment_method,
            payment_status,
            payment_date,
            currency,
            transaction_reference,
            collected_by,
            notes,
            created_at
        FROM {SCHEMA}.payments
        ORDER BY payment_date DESC NULLS LAST, created_at DESC
        LIMIT 500
        """,
    )


def load_shipments_for_payment(engine: Engine) -> pd.DataFrame:
    """
    Load every shipment, including new shipments without a branch-payment row.
    """
    return read_dataframe(
        engine,
        f"""
        SELECT
            s.shipment_id,
            s.customer_id,
            s.customer_name,
            s.shipment_date,
            s.destination_city,
            s.destination_country,
            s.current_status,
            s.amount_charged AS shipment_amount_charged,
            s.amount_paid AS shipment_amount_paid,
            s.balance_due AS shipment_balance_due,
            s.payment_status AS shipment_payment_status,
            s.release_status AS shipment_release_status,
            s.notes AS shipment_notes,
            bp.branch_payment_id,
            bp.invoice_number,
            bp.sender_name,
            bp.receiver_name,
            bp.origin_branch,
            bp.destination_branch,
            bp.payment_terms,
            bp.payment_responsibility,
            bp.amount_charged,
            bp.amount_paid_nj,
            bp.amount_paid_guyana,
            bp.total_amount_paid,
            bp.balance_due,
            bp.payment_collected_at,
            bp.payment_method,
            bp.payment_status,
            bp.release_status,
            bp.collected_by,
            bp.payment_date,
            bp.currency,
            bp.notes AS branch_payment_notes
        FROM {SCHEMA}.shipments AS s
        LEFT JOIN LATERAL (
            SELECT branch_record.*
            FROM {SCHEMA}.branch_payments AS branch_record
            WHERE branch_record.shipment_id = s.shipment_id
            ORDER BY branch_record.updated_at DESC
            LIMIT 1
        ) AS bp ON TRUE
        ORDER BY s.shipment_date DESC, s.shipment_id DESC
        """,
    )


def get_numeric_sum(dataframe: pd.DataFrame, column: str) -> float:
    """Safely total a numeric dataframe column."""
    if dataframe.empty or column not in dataframe.columns:
        return 0.0

    return float(
        pd.to_numeric(dataframe[column], errors="coerce").fillna(0).sum()
    )


def filter_dataframe(
    dataframe: pd.DataFrame,
    payment_terms: list[str],
    payment_statuses: list[str],
    release_statuses: list[str],
    branches: list[str],
) -> pd.DataFrame:
    """Apply dashboard filters."""
    filtered = dataframe.copy()

    if payment_terms:
        filtered = filtered[
            filtered["payment_terms"].astype(str).isin(payment_terms)
        ]

    if payment_statuses:
        filtered = filtered[
            filtered["payment_status"].astype(str).isin(payment_statuses)
        ]

    if release_statuses:
        filtered = filtered[
            filtered["release_status"].astype(str).isin(release_statuses)
        ]

    if branches:
        filtered = filtered[
            filtered["payment_collected_at"].astype(str).isin(branches)
        ]

    return filtered


def render_summary_metrics(branch_payments: pd.DataFrame) -> None:
    """Render the payment overview cards."""
    total_charged = get_numeric_sum(branch_payments, "amount_charged")
    paid_nj = get_numeric_sum(branch_payments, "amount_paid_nj")
    paid_guyana = get_numeric_sum(branch_payments, "amount_paid_guyana")
    total_paid = get_numeric_sum(branch_payments, "total_amount_paid")
    balance_due = get_numeric_sum(branch_payments, "balance_due")

    first_row = st.columns(4)
    first_metrics = [
        ("Total Charged", format_currency(total_charged)),
        ("Paid in New Jersey", format_currency(paid_nj)),
        ("Paid in Guyana", format_currency(paid_guyana)),
        ("Balance Due", format_currency(balance_due)),
    ]

    for column, (label, value) in zip(first_row, first_metrics):
        with column:
            st.metric(label, value)

    freight_collect_count = int(
        branch_payments["payment_terms"]
        .astype(str)
        .str.contains("Receiver Paid|Freight Collect", case=False, na=False)
        .sum()
    )

    hold_count = int(
        branch_payments["release_status"]
        .astype(str)
        .str.contains("Hold", case=False, na=False)
        .sum()
    )

    second_row = st.columns(3)
    second_metrics = [
        ("Total Paid", format_currency(total_paid)),
        ("Freight Collect Shipments", freight_collect_count),
        ("Held Until Paid", hold_count),
    ]

    for column, (label, value) in zip(second_row, second_metrics):
        with column:
            st.metric(label, value)


def render_branch_breakdown(branch_payments: pd.DataFrame) -> None:
    """Render grouped payment summaries."""
    st.subheader("Branch Payment Breakdown")

    tabs = st.tabs(
        [
            "By Payment Terms",
            "By Payment Status",
            "By Release Status",
            "By Collection Location",
        ]
    )

    settings = [
        (
            tabs[0],
            "payment_terms",
            [
                "amount_charged",
                "amount_paid_nj",
                "amount_paid_guyana",
                "total_amount_paid",
                "balance_due",
            ],
        ),
        (
            tabs[1],
            "payment_status",
            ["amount_charged", "total_amount_paid", "balance_due"],
        ),
        (
            tabs[2],
            "release_status",
            ["amount_charged", "total_amount_paid", "balance_due"],
        ),
        (
            tabs[3],
            "payment_collected_at",
            [
                "amount_charged",
                "amount_paid_nj",
                "amount_paid_guyana",
                "total_amount_paid",
                "balance_due",
            ],
        ),
    ]

    for tab, group_column, numeric_columns in settings:
        with tab:
            if branch_payments.empty:
                st.info("No branch-payment records are available.")
                continue

            aggregation: dict[str, tuple[str, str]] = {
                "shipments": ("shipment_id", "count")
            }

            for numeric_column in numeric_columns:
                aggregation[numeric_column] = (numeric_column, "sum")

            summary = (
                branch_payments.groupby(group_column, dropna=False)
                .agg(**aggregation)
                .reset_index()
            )

            st.dataframe(summary, use_container_width=True)


def render_payment_lookup(branch_payments: pd.DataFrame) -> None:
    """Search payment accounts."""
    st.subheader("Payment Lookup")

    lookup_value = st.text_input(
        (
            "Search by shipment ID, invoice number, sender, receiver, "
            "customer, payment status, or release status"
        ),
        placeholder=(
            "Example: SST-2026-0026, INV-2026-0026, "
            "receiver paid, hold until paid"
        ),
        key="payment_lookup",
    )

    filtered = branch_payments.copy()

    if lookup_value.strip() and not filtered.empty:
        search_columns = [
            "shipment_id",
            "invoice_number",
            "sender_name",
            "receiver_name",
            "customer_name",
            "payment_terms",
            "payment_responsibility",
            "payment_status",
            "release_status",
            "payment_collected_at",
            "collected_by",
            "notes",
        ]

        search_text = (
            filtered[search_columns]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
        )

        filtered = filtered[
            search_text.str.contains(
                lookup_value.strip(),
                case=False,
                na=False,
            )
        ]

    if filtered.empty:
        st.info("No payment records matched your search.")
    else:
        st.dataframe(filtered, use_container_width=True)


def render_release_queue(branch_payments: pd.DataFrame) -> None:
    """Show shipments on hold or cancelled."""
    st.subheader("Release / Hold Queue")

    if branch_payments.empty:
        st.info("No branch-payment records are available.")
        return

    queue = branch_payments[
        branch_payments["release_status"]
        .astype(str)
        .str.contains("Hold|Cancelled", case=False, na=False)
    ].copy()

    if queue.empty:
        st.success("No shipments are currently on hold for payment.")
        return

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

    st.warning("These shipments require payment or release review.")
    st.dataframe(queue[display_columns], use_container_width=True)


def recipient_from_notes(notes: Any) -> str:
    """Extract the recipient name stored in shipment notes."""
    match = re.search(
        r"Recipient:\s*([^\n\r]+)",
        safe_text(notes, ""),
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def get_payment_responsibility(payment_terms: str) -> str:
    """Translate payment terms into a responsibility label."""
    if payment_terms == "Sender Paid / Prepaid":
        return "Sender"
    if payment_terms == "Receiver Paid / Freight Collect":
        return "Receiver"
    if payment_terms == "Split Payment":
        return "Sender and Receiver"
    return "To Be Confirmed"


def combined_collection_location(existing_location: Any, new_location: str) -> str:
    """Preserve both branch locations for split payments."""
    current = safe_text(existing_location, "")

    if not current:
        return new_location

    if new_location.lower() in current.lower():
        return current

    if {current.lower(), new_location.lower()} == {
        "new jersey branch",
        "guyana office",
    }:
        return "New Jersey Branch and Guyana Office"

    return f"{current}; {new_location}"


def append_note(existing_notes: Any, new_note: str) -> str:
    """Append a payment note without deleting previous notes."""
    current = safe_text(existing_notes, "")
    return f"{current}\n\n{new_note}" if current else new_note


def next_readable_id(
    connection: Any,
    table_name: str,
    column_name: str,
    prefix: str,
    year: int,
    width: int = 4,
) -> str:
    """Generate a readable sequential ID inside a locked transaction."""
    lock_name = f"solomon_shipping.{table_name}.{column_name}.{year}"

    connection.execute(
        text("SELECT PG_ADVISORY_XACT_LOCK(HASHTEXT(:lock_name))"),
        {"lock_name": lock_name},
    )

    pattern = f"^{prefix}-{year}-[0-9]+$"

    next_number = connection.execute(
        text(
            f"""
            SELECT COALESCE(
                MAX(SPLIT_PART({column_name}, '-', 3)::INTEGER),
                0
            ) + 1
            FROM {SCHEMA}.{table_name}
            WHERE {column_name} ~ :pattern
            """
        ),
        {"pattern": pattern},
    ).scalar_one()

    return f"{prefix}-{year}-{int(next_number):0{width}d}"


def calculate_payment_status(
    amount_charged: Decimal,
    total_paid: Decimal,
) -> tuple[Decimal, str, str]:
    """Return balance, payment status, and release status."""
    balance_due = max(amount_charged - total_paid, Decimal("0.00"))

    if amount_charged <= 0:
        return balance_due, "Pending Charge", "Pending Review"

    if balance_due <= 0:
        return Decimal("0.00"), "Paid", "Cleared for Pickup"

    if total_paid > 0:
        return balance_due, "Partial", "Hold Until Balance Paid"

    return balance_due, "Unpaid", "Hold Until Paid"


def save_payment_update(
    engine: Engine,
    shipment_id: str,
    amount_charged: Decimal,
    amount_received: Decimal,
    payment_location: str,
    payment_method: str,
    payment_terms: str,
    currency: str,
    collected_by: str,
    payment_date: date,
    transaction_reference: str,
    notes: str,
) -> dict[str, Any]:
    """
    Save the branch-payment account, payment transaction, and shipment balance
    together in one database transaction.
    """
    year = datetime.now().year

    with engine.begin() as connection:
        shipment = connection.execute(
            text(
                f"""
                SELECT
                    shipment_id,
                    customer_id,
                    customer_name,
                    destination_country,
                    destination_city,
                    amount_charged,
                    amount_paid,
                    balance_due,
                    payment_status,
                    release_status,
                    notes
                FROM {SCHEMA}.shipments
                WHERE shipment_id = :shipment_id
                FOR UPDATE
                """
            ),
            {"shipment_id": shipment_id},
        ).mappings().first()

        if shipment is None:
            raise RuntimeError(
                "The selected shipment no longer exists in Neon."
            )

        branch_account = connection.execute(
            text(
                f"""
                SELECT *
                FROM {SCHEMA}.branch_payments
                WHERE shipment_id = :shipment_id
                ORDER BY updated_at DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"shipment_id": shipment_id},
        ).mappings().first()

        if branch_account:
            branch_payment_id = str(branch_account["branch_payment_id"])
            invoice_number = safe_text(branch_account.get("invoice_number"), "")

            if not invoice_number:
                invoice_number = next_readable_id(
                    connection,
                    "branch_payments",
                    "invoice_number",
                    "INV",
                    year,
                )

            current_paid_nj = to_decimal(branch_account.get("amount_paid_nj"))
            current_paid_guyana = to_decimal(
                branch_account.get("amount_paid_guyana")
            )
            sender_name = safe_text(
                branch_account.get("sender_name"),
                safe_text(shipment.get("customer_name"), ""),
            )
            receiver_name = safe_text(
                branch_account.get("receiver_name"),
                recipient_from_notes(shipment.get("notes")),
            )
            origin_branch = safe_text(
                branch_account.get("origin_branch"),
                "New Jersey",
            )
            destination_branch = safe_text(
                branch_account.get("destination_branch"),
                safe_text(
                    shipment.get("destination_country"),
                    "Destination Office",
                ),
            )
            existing_notes = branch_account.get("notes")
            existing_location = branch_account.get("payment_collected_at")
        else:
            branch_payment_id = next_readable_id(
                connection,
                "branch_payments",
                "branch_payment_id",
                "BP",
                year,
            )
            invoice_number = next_readable_id(
                connection,
                "branch_payments",
                "invoice_number",
                "INV",
                year,
            )
            current_paid_nj = Decimal("0.00")
            current_paid_guyana = Decimal("0.00")
            sender_name = safe_text(shipment.get("customer_name"), "")
            receiver_name = recipient_from_notes(shipment.get("notes"))
            origin_branch = "New Jersey"
            destination_branch = safe_text(
                shipment.get("destination_country"),
                "Destination Office",
            )
            existing_notes = ""
            existing_location = ""

        if payment_location == "New Jersey Branch":
            updated_paid_nj = current_paid_nj + amount_received
            updated_paid_guyana = current_paid_guyana
        else:
            updated_paid_nj = current_paid_nj
            updated_paid_guyana = current_paid_guyana + amount_received

        total_paid = updated_paid_nj + updated_paid_guyana
        balance_due, payment_status, release_status = calculate_payment_status(
            amount_charged,
            total_paid,
        )

        timestamped_note = (
            f"[{datetime.now():%Y-%m-%d %H:%M}] "
            f"{payment_location}: "
            f"{format_currency(amount_received, currency)} received by "
            f"{collected_by.strip() or 'Not recorded'}."
        )

        if transaction_reference.strip():
            timestamped_note += (
                "\nTransaction reference: " + transaction_reference.strip()
            )

        if notes.strip():
            timestamped_note += "\nPayment notes: " + notes.strip()

        account_values = {
            "branch_payment_id": branch_payment_id,
            "shipment_id": shipment_id,
            "invoice_number": invoice_number,
            "sender_name": sender_name,
            "receiver_name": receiver_name,
            "origin_branch": origin_branch,
            "destination_branch": destination_branch,
            "payment_terms": payment_terms,
            "payment_responsibility": get_payment_responsibility(payment_terms),
            "amount_charged": amount_charged,
            "amount_paid_nj": updated_paid_nj,
            "amount_paid_guyana": updated_paid_guyana,
            "total_amount_paid": total_paid,
            "balance_due": balance_due,
            "payment_collected_at": combined_collection_location(
                existing_location,
                payment_location,
            ),
            "payment_method": payment_method,
            "payment_status": payment_status,
            "release_status": release_status,
            "collected_by": collected_by.strip() or None,
            "payment_date": payment_date,
            "currency": currency,
            "notes": append_note(existing_notes, timestamped_note),
        }

        if branch_account:
            connection.execute(
                text(
                    f"""
                    UPDATE {SCHEMA}.branch_payments
                    SET
                        invoice_number = :invoice_number,
                        sender_name = :sender_name,
                        receiver_name = :receiver_name,
                        origin_branch = :origin_branch,
                        destination_branch = :destination_branch,
                        payment_terms = :payment_terms,
                        payment_responsibility = :payment_responsibility,
                        amount_charged = :amount_charged,
                        amount_paid_nj = :amount_paid_nj,
                        amount_paid_guyana = :amount_paid_guyana,
                        total_amount_paid = :total_amount_paid,
                        balance_due = :balance_due,
                        payment_collected_at = :payment_collected_at,
                        payment_method = :payment_method,
                        payment_status = :payment_status,
                        release_status = :release_status,
                        collected_by = :collected_by,
                        payment_date = :payment_date,
                        currency = :currency,
                        notes = :notes,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE branch_payment_id = :branch_payment_id
                    """
                ),
                account_values,
            )
        else:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.branch_payments (
                        branch_payment_id,
                        shipment_id,
                        invoice_number,
                        sender_name,
                        receiver_name,
                        origin_branch,
                        destination_branch,
                        payment_terms,
                        payment_responsibility,
                        amount_charged,
                        amount_paid_nj,
                        amount_paid_guyana,
                        total_amount_paid,
                        balance_due,
                        payment_collected_at,
                        payment_method,
                        payment_status,
                        release_status,
                        collected_by,
                        payment_date,
                        currency,
                        notes
                    )
                    VALUES (
                        :branch_payment_id,
                        :shipment_id,
                        :invoice_number,
                        :sender_name,
                        :receiver_name,
                        :origin_branch,
                        :destination_branch,
                        :payment_terms,
                        :payment_responsibility,
                        :amount_charged,
                        :amount_paid_nj,
                        :amount_paid_guyana,
                        :total_amount_paid,
                        :balance_due,
                        :payment_collected_at,
                        :payment_method,
                        :payment_status,
                        :release_status,
                        :collected_by,
                        :payment_date,
                        :currency,
                        :notes
                    )
                    """
                ),
                account_values,
            )

        payment_id = "Charge update only"

        if amount_received > 0:
            payment_id = next_readable_id(
                connection,
                "payments",
                "payment_id",
                "PAY",
                year,
            )

            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.payments (
                        payment_id,
                        shipment_id,
                        invoice_number,
                        customer_id,
                        customer_name,
                        amount_charged,
                        amount_paid,
                        balance_due,
                        payment_method,
                        payment_status,
                        payment_date,
                        notes,
                        currency,
                        transaction_reference,
                        collected_by
                    )
                    VALUES (
                        :payment_id,
                        :shipment_id,
                        :invoice_number,
                        :customer_id,
                        :customer_name,
                        :amount_charged,
                        :amount_paid,
                        :balance_due,
                        :payment_method,
                        :payment_status,
                        :payment_date,
                        :notes,
                        :currency,
                        NULLIF(:transaction_reference, ''),
                        NULLIF(:collected_by, '')
                    )
                    """
                ),
                {
                    "payment_id": payment_id,
                    "shipment_id": shipment_id,
                    "invoice_number": invoice_number,
                    "customer_id": shipment["customer_id"],
                    "customer_name": shipment["customer_name"],
                    "amount_charged": amount_charged,
                    "amount_paid": amount_received,
                    "balance_due": balance_due,
                    "payment_method": payment_method,
                    "payment_status": payment_status,
                    "payment_date": payment_date,
                    "notes": notes.strip(),
                    "currency": currency,
                    "transaction_reference": transaction_reference.strip(),
                    "collected_by": collected_by.strip(),
                },
            )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.shipments
                SET
                    amount_charged = :amount_charged,
                    amount_paid = :amount_paid,
                    balance_due = :balance_due,
                    payment_status = :payment_status,
                    release_status = :release_status,
                    updated_at = CURRENT_TIMESTAMP
                WHERE shipment_id = :shipment_id
                """
            ),
            {
                "amount_charged": amount_charged,
                "amount_paid": total_paid,
                "balance_due": balance_due,
                "payment_status": payment_status,
                "release_status": release_status,
                "shipment_id": shipment_id,
            },
        )

    return {
        "payment_id": payment_id,
        "branch_payment_id": branch_payment_id,
        "invoice_number": invoice_number,
        "shipment_id": shipment_id,
        "amount_received": amount_received,
        "total_amount_paid": total_paid,
        "balance_due": balance_due,
        "payment_status": payment_status,
        "release_status": release_status,
        "currency": currency,
    }


def safe_select_index(
    options: list[str],
    current_value: Any,
    fallback: int = 0,
) -> int:
    """Return a safe selectbox index."""
    current = safe_text(current_value, "")
    return options.index(current) if current in options else fallback


def render_record_payment_form(
    engine: Engine,
    shipments: pd.DataFrame,
) -> None:
    """Record a charge or branch payment directly in Neon."""
    st.subheader("Record Branch Payment")

    if shipments.empty:
        st.info("No shipment records are available in Neon.")
        return

    shipment_options = (
        shipments["shipment_id"].dropna().astype(str).tolist()
    )

    selected_shipment_id = st.selectbox(
        "Shipment ID",
        shipment_options,
        key="payment_shipment_id",
    )

    selected_frame = shipments[
        shipments["shipment_id"].astype(str).eq(selected_shipment_id)
    ]

    if selected_frame.empty:
        st.error("The selected shipment was not found.")
        return

    current = selected_frame.iloc[0]

    current_charge = to_decimal(
        current.get("amount_charged")
        if pd.notna(current.get("amount_charged"))
        else current.get("shipment_amount_charged")
    )

    current_paid = to_decimal(
        current.get("total_amount_paid")
        if pd.notna(current.get("total_amount_paid"))
        else current.get("shipment_amount_paid")
    )

    current_balance = to_decimal(
        current.get("balance_due")
        if pd.notna(current.get("balance_due"))
        else current.get("shipment_balance_due")
    )

    current_terms = safe_text(current.get("payment_terms"), "Not Sure Yet")
    current_currency = safe_text(current.get("currency"), "USD")

    summary = st.columns(4)
    summary_values = [
        ("Customer", safe_text(current.get("customer_name"))),
        ("Current Charge", format_currency(current_charge, current_currency)),
        ("Total Paid", format_currency(current_paid, current_currency)),
        ("Balance Due", format_currency(current_balance, current_currency)),
    ]

    for column, (label, value) in zip(summary, summary_values):
        with column:
            st.metric(label, value)

    with st.form("record_branch_payment_form", clear_on_submit=False):
        left, right = st.columns(2)

        with left:
            amount_charged_input = st.number_input(
                "Total Amount Charged",
                min_value=0.0,
                step=5.0,
                value=float(current_charge),
            )
            amount_received_input = st.number_input(
                "Amount Received Now",
                min_value=0.0,
                step=5.0,
                value=0.0,
            )
            payment_location = st.selectbox(
                "Payment Collected At",
                PAYMENT_LOCATIONS,
            )
            payment_method = st.selectbox(
                "Payment Method",
                PAYMENT_METHODS,
            )

        with right:
            payment_terms = st.selectbox(
                "Payment Terms",
                PAYMENT_TERMS,
                index=safe_select_index(
                    PAYMENT_TERMS,
                    current_terms,
                    fallback=3,
                ),
            )
            currency = st.selectbox(
                "Currency",
                CURRENCIES,
                index=safe_select_index(
                    CURRENCIES,
                    current_currency,
                    fallback=0,
                ),
            )
            collected_by = st.text_input("Collected By")
            payment_date_value = st.date_input(
                "Payment Date",
                value=date.today(),
            )

        transaction_reference = st.text_input(
            "Transaction / Receipt Reference",
            placeholder=(
                "Example: Zelle confirmation, card receipt, "
                "bank transfer reference, or cash receipt number"
            ),
        )

        notes = st.text_area(
            "Payment Notes",
            placeholder=(
                "Add a receipt note, branch note, "
                "or sender/receiver payment details."
            ),
            height=100,
        )

        submitted = st.form_submit_button(
            "Save Payment to Neon",
            use_container_width=True,
        )

    if not submitted:
        return

    amount_charged = to_decimal(amount_charged_input)
    amount_received = to_decimal(amount_received_input)

    if amount_charged <= 0:
        st.error(
            "Enter the total amount charged before saving the payment account."
        )
        return

    if amount_received <= 0 and current_charge == amount_charged:
        st.error(
            "Enter an amount received or change the total amount charged."
        )
        return

    try:
        with st.spinner(
            "Saving the payment and updating the shipment balance..."
        ):
            result = save_payment_update(
                engine=engine,
                shipment_id=selected_shipment_id,
                amount_charged=amount_charged,
                amount_received=amount_received,
                payment_location=payment_location,
                payment_method=payment_method,
                payment_terms=payment_terms,
                currency=currency,
                collected_by=collected_by,
                payment_date=payment_date_value,
                transaction_reference=transaction_reference,
                notes=notes,
            )

        st.success("Payment information saved successfully.")

        confirmation = pd.DataFrame(
            [
                {
                    **result,
                    "amount_received": format_currency(
                        result["amount_received"],
                        result["currency"],
                    ),
                    "total_amount_paid": format_currency(
                        result["total_amount_paid"],
                        result["currency"],
                    ),
                    "balance_due": format_currency(
                        result["balance_due"],
                        result["currency"],
                    ),
                }
            ]
        )

        st.dataframe(confirmation, use_container_width=True)

        st.info(
            "The branch-payment account, individual payment transaction, "
            "and shipment balance were updated together in Neon."
        )

        if st.button("Refresh Payment Dashboard", use_container_width=True):
            st.rerun()

    except Exception as exc:
        st.error("The payment could not be saved to Neon.")
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )


def main() -> None:
    """Owner-facing live Neon payment management page."""
    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Payments",
        subtitle=(
            "Monitor New Jersey and Guyana payments, sender-paid shipments, "
            "freight collect balances, split payments, and release status "
            "directly in Neon."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner Financial View</span>
        <span class="badge-dark">NJ + Guyana Branch Payments</span>
        <span class="badge-red">Live Release Control</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = get_database_engine()
        verify_required_tables(engine)
        branch_payments = load_branch_payments(engine)
        payment_history = load_payment_history(engine)
        shipments = load_shipments_for_payment(engine)
    except Exception as exc:
        st.error(
            "The Payments page could not load the Solomon Shipping "
            "records from Neon."
        )
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )
        return

    if branch_payments.empty:
        st.info(
            "No branch-payment accounts have been created yet. "
            "Use Record Payment to create the first account for a shipment."
        )
    else:
        render_summary_metrics(branch_payments)

    st.divider()

    if not branch_payments.empty:
        filter_columns = st.columns(4)

        payment_terms_options = sorted(
            branch_payments["payment_terms"]
            .dropna()
            .astype(str)
            .unique()
        )
        payment_status_options = sorted(
            branch_payments["payment_status"]
            .dropna()
            .astype(str)
            .unique()
        )
        release_status_options = sorted(
            branch_payments["release_status"]
            .dropna()
            .astype(str)
            .unique()
        )
        branch_options = sorted(
            branch_payments["payment_collected_at"]
            .dropna()
            .astype(str)
            .unique()
        )

        with filter_columns[0]:
            selected_payment_terms = st.multiselect(
                "Payment Terms",
                options=payment_terms_options,
                default=payment_terms_options,
            )

        with filter_columns[1]:
            selected_payment_statuses = st.multiselect(
                "Payment Status",
                options=payment_status_options,
                default=payment_status_options,
            )

        with filter_columns[2]:
            selected_release_statuses = st.multiselect(
                "Release Status",
                options=release_status_options,
                default=release_status_options,
            )

        with filter_columns[3]:
            selected_branches = st.multiselect(
                "Collected At",
                options=branch_options,
                default=branch_options,
            )

        filtered_payments = filter_dataframe(
            dataframe=branch_payments,
            payment_terms=selected_payment_terms,
            payment_statuses=selected_payment_statuses,
            release_statuses=selected_release_statuses,
            branches=selected_branches,
        )
    else:
        filtered_payments = branch_payments

    st.divider()

    tabs = st.tabs(
        [
            "Branch Payment Accounts",
            "Release / Hold Queue",
            "Branch Breakdown",
            "Payment Lookup",
            "Record Payment",
            "Payment History",
        ]
    )

    with tabs[0]:
        st.subheader("Branch Payment Accounts")

        if filtered_payments.empty:
            st.info("No branch-payment accounts match the current filters.")
        else:
            st.dataframe(filtered_payments, use_container_width=True)

    with tabs[1]:
        render_release_queue(filtered_payments)

    with tabs[2]:
        render_branch_breakdown(filtered_payments)

    with tabs[3]:
        render_payment_lookup(filtered_payments)

    with tabs[4]:
        render_record_payment_form(engine, shipments)

    with tabs[5]:
        st.subheader("Individual Payment History")

        if payment_history.empty:
            st.info("No payment transactions are stored in Neon.")
        else:
            st.dataframe(payment_history, use_container_width=True)


if __name__ == "__main__":
    main()