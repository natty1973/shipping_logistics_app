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


st.set_page_config(page_title="Payment Lookup", page_icon="💳", layout="wide")

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
    database_url = get_secret("DATABASE_URL")

    if database_url:
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://") :]
        database_target: str | URL = database_url
    else:
        settings = {
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
            if not settings[key]
        ]
        if missing:
            raise RuntimeError("Missing Streamlit Secrets: " + ", ".join(missing))

        try:
            port = int(settings["port"])
        except ValueError:
            port = 5432

        database_target = URL.create(
            "postgresql+psycopg2",
            username=settings["user"],
            password=settings["password"],
            host=settings["host"],
            port=port,
            database=settings["database"],
            query={"sslmode": settings["sslmode"]},
        )

    engine = create_engine(
        database_target,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 15,
            "application_name": "solomon_shipping_payment_lookup",
        },
    )

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return engine


def safe_error_message(error: Exception) -> str:
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


def get_portal_label() -> str:
    mode = str(st.session_state.get("portal_mode", "staff")).lower()
    return {"owner": "Owner", "admin": "Admin", "staff": "Staff"}.get(mode, "Staff")


def safe_text(value: Any, default: str = "Not Available") -> str:
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
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def format_currency(value: Any, currency: str = "USD") -> str:
    amount = to_decimal(value)
    symbol = {"USD": "$", "GYD": "G$", "CAD": "C$", "GBP": "£"}.get(
        currency.upper(),
        f"{currency.upper()} ",
    )
    return f"{symbol}{amount:,.2f}"


def verify_required_tables(engine: Engine) -> None:
    required = ["shipments", "branch_payments", "payments"]
    missing: list[str] = []

    with engine.connect() as connection:
        for table_name in required:
            relation_name = f"{SCHEMA}.{table_name}"
            exists = connection.execute(
                text("SELECT TO_REGCLASS(:name)"),
                {"name": relation_name},
            ).scalar_one_or_none()
            if exists is None:
                missing.append(relation_name)

    if missing:
        raise RuntimeError("Required Neon tables are missing: " + ", ".join(missing))


def read_dataframe(
    engine: Engine,
    sql: str,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    with engine.connect() as connection:
        return pd.read_sql_query(text(sql), connection, params=params or {})


def search_payment_records(engine: Engine, lookup_value: str) -> pd.DataFrame:
    pattern = f"%{lookup_value.strip()}%"

    return read_dataframe(
        engine,
        f"""
        SELECT
            s.shipment_id,
            s.customer_id,
            s.customer_name,
            s.shipment_date,
            s.current_status AS shipment_status,
            s.destination_city,
            s.destination_country,
            s.notes AS shipment_notes,
            bp.branch_payment_id,
            bp.invoice_number,
            COALESCE(NULLIF(BTRIM(bp.sender_name), ''), s.customer_name)
                AS sender_name,
            bp.receiver_name,
            bp.payment_terms,
            bp.payment_responsibility,
            COALESCE(bp.amount_charged, s.amount_charged, 0)
                AS amount_charged,
            COALESCE(bp.amount_paid_nj, 0)
                AS amount_paid_nj,
            COALESCE(bp.amount_paid_guyana, 0)
                AS amount_paid_guyana,
            COALESCE(bp.total_amount_paid, s.amount_paid, 0)
                AS total_amount_paid,
            COALESCE(bp.balance_due, s.balance_due, 0)
                AS balance_due,
            bp.payment_collected_at,
            bp.payment_method,
            COALESCE(bp.payment_status, s.payment_status, 'Pending Charge')
                AS payment_status,
            COALESCE(bp.release_status, s.release_status, 'Pending Review')
                AS release_status,
            bp.collected_by,
            bp.payment_date,
            COALESCE(bp.currency, 'USD') AS currency,
            bp.notes
        FROM {SCHEMA}.shipments AS s
        LEFT JOIN LATERAL (
            SELECT branch_record.*
            FROM {SCHEMA}.branch_payments AS branch_record
            WHERE branch_record.shipment_id = s.shipment_id
            ORDER BY branch_record.updated_at DESC
            LIMIT 1
        ) AS bp ON TRUE
        WHERE
            s.shipment_id ILIKE :pattern
            OR s.customer_id ILIKE :pattern
            OR s.customer_name ILIKE :pattern
            OR s.destination_city ILIKE :pattern
            OR s.destination_country ILIKE :pattern
            OR COALESCE(bp.invoice_number, '') ILIKE :pattern
            OR COALESCE(bp.sender_name, '') ILIKE :pattern
            OR COALESCE(bp.receiver_name, '') ILIKE :pattern
            OR COALESCE(bp.payment_terms, '') ILIKE :pattern
            OR COALESCE(bp.payment_status, s.payment_status, '') ILIKE :pattern
            OR COALESCE(bp.release_status, s.release_status, '') ILIKE :pattern
        ORDER BY s.shipment_date DESC, s.shipment_id DESC
        LIMIT 100
        """,
        {"pattern": pattern},
    )


def load_payment_history(engine: Engine, shipment_id: str) -> pd.DataFrame:
    return read_dataframe(
        engine,
        f"""
        SELECT
            payment_id,
            invoice_number,
            payment_date,
            amount_paid,
            balance_due,
            payment_method,
            payment_status,
            currency,
            transaction_reference,
            collected_by,
            notes,
            created_at
        FROM {SCHEMA}.payments
        WHERE UPPER(BTRIM(shipment_id)) = UPPER(BTRIM(:shipment_id))
        ORDER BY payment_date DESC NULLS LAST, created_at DESC
        """,
        {"shipment_id": shipment_id},
    )


def recipient_from_notes(notes: Any) -> str:
    match = re.search(
        r"Recipient:\s*([^\n\r]+)",
        safe_text(notes, ""),
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def payment_responsibility(payment_terms: str) -> str:
    return {
        "Sender Paid / Prepaid": "Sender",
        "Receiver Paid / Freight Collect": "Receiver",
        "Split Payment": "Sender and Receiver",
    }.get(payment_terms, "To Be Confirmed")


def append_note(existing_notes: Any, new_note: str) -> str:
    current = safe_text(existing_notes, "")
    return f"{current}\n\n{new_note}" if current else new_note


def combined_collection_location(existing_location: Any, new_location: str) -> str:
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


def next_readable_id(
    connection: Any,
    table_name: str,
    column_name: str,
    prefix: str,
    year: int,
) -> str:
    connection.execute(
        text("SELECT PG_ADVISORY_XACT_LOCK(HASHTEXT(:lock_name))"),
        {
            "lock_name": (
                f"solomon_shipping.{table_name}.{column_name}.{year}"
            )
        },
    )

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
        {"pattern": f"^{prefix}-{year}-[0-9]+$"},
    ).scalar_one()

    return f"{prefix}-{year}-{int(next_number):04d}"


def save_staff_payment(
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
    receipt_number: str,
    payment_notes: str,
    role_label: str,
) -> dict[str, Any]:
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
                    notes
                FROM {SCHEMA}.shipments
                WHERE shipment_id = :shipment_id
                FOR UPDATE
                """
            ),
            {"shipment_id": shipment_id},
        ).mappings().first()

        if shipment is None:
            raise RuntimeError("The selected shipment no longer exists in Neon.")

        account = connection.execute(
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

        if account:
            branch_payment_id = str(account["branch_payment_id"])
            invoice_number = safe_text(account.get("invoice_number"), "") or (
                next_readable_id(
                    connection,
                    "branch_payments",
                    "invoice_number",
                    "INV",
                    year,
                )
            )
            paid_nj = to_decimal(account.get("amount_paid_nj"))
            paid_guyana = to_decimal(account.get("amount_paid_guyana"))
            existing_currency = safe_text(account.get("currency"), "USD")
            sender_name = safe_text(
                account.get("sender_name"),
                safe_text(shipment.get("customer_name"), ""),
            )
            receiver_name = safe_text(
                account.get("receiver_name"),
                recipient_from_notes(shipment.get("notes")),
            )
            existing_notes = account.get("notes")
            existing_location = account.get("payment_collected_at")
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
            paid_nj = Decimal("0.00")
            paid_guyana = Decimal("0.00")
            existing_currency = currency
            sender_name = safe_text(shipment.get("customer_name"), "")
            receiver_name = recipient_from_notes(shipment.get("notes"))
            existing_notes = ""
            existing_location = ""

        current_total_paid = paid_nj + paid_guyana

        if current_total_paid > 0 and currency != existing_currency:
            raise RuntimeError(
                f"This account already contains payments in {existing_currency}. "
                f"Keep the currency set to {existing_currency}."
            )

        updated_total_paid = current_total_paid + amount_received

        if updated_total_paid > amount_charged:
            raise RuntimeError(
                "This payment would exceed the total amount charged."
            )

        if payment_location == "New Jersey Branch":
            updated_paid_nj = paid_nj + amount_received
            updated_paid_guyana = paid_guyana
        else:
            updated_paid_nj = paid_nj
            updated_paid_guyana = paid_guyana + amount_received

        balance_due = max(
            amount_charged - updated_total_paid,
            Decimal("0.00"),
        )

        if balance_due <= 0:
            payment_status = "Paid"
            release_status = "Cleared for Pickup"
        elif updated_total_paid > 0:
            payment_status = "Partial"
            release_status = "Hold Until Balance Paid"
        else:
            payment_status = "Unpaid"
            release_status = "Hold Until Paid"

        note = (
            f"[{datetime.now():%Y-%m-%d %H:%M}] "
            f"{payment_location}: "
            f"{format_currency(amount_received, currency)} received by "
            f"{collected_by.strip() or role_label}."
        )

        if receipt_number.strip():
            note += "\nReceipt / transaction reference: " + receipt_number.strip()
        if payment_notes.strip():
            note += "\nPayment notes: " + payment_notes.strip()

        account_values = {
            "branch_payment_id": branch_payment_id,
            "shipment_id": shipment_id,
            "invoice_number": invoice_number,
            "sender_name": sender_name,
            "receiver_name": receiver_name,
            "origin_branch": "New Jersey",
            "destination_branch": safe_text(
                shipment.get("destination_country"),
                "Destination Office",
            ),
            "payment_terms": payment_terms,
            "payment_responsibility": payment_responsibility(payment_terms),
            "amount_charged": amount_charged,
            "amount_paid_nj": updated_paid_nj,
            "amount_paid_guyana": updated_paid_guyana,
            "total_amount_paid": updated_total_paid,
            "balance_due": balance_due,
            "payment_collected_at": combined_collection_location(
                existing_location,
                payment_location,
            ),
            "payment_method": payment_method,
            "payment_status": payment_status,
            "release_status": release_status,
            "collected_by": collected_by.strip() or role_label,
            "payment_date": payment_date,
            "currency": currency,
            "notes": append_note(existing_notes, note),
        }

        if account:
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
                    :collected_by
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
                "notes": payment_notes.strip(),
                "currency": currency,
                "transaction_reference": receipt_number.strip(),
                "collected_by": collected_by.strip() or role_label,
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
                "amount_paid": updated_total_paid,
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
        "paid_in_new_jersey": updated_paid_nj,
        "paid_in_guyana": updated_paid_guyana,
        "total_paid": updated_total_paid,
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
    value = safe_text(current_value, "")
    return options.index(value) if value in options else fallback


def render_payment_summary(record: dict[str, Any]) -> None:
    currency = safe_text(record.get("currency"), "USD")

    values = [
        (
            "Amount Charged",
            format_currency(record.get("amount_charged"), currency),
        ),
        (
            "Paid in NJ",
            format_currency(record.get("amount_paid_nj"), currency),
        ),
        (
            "Paid in Guyana",
            format_currency(record.get("amount_paid_guyana"), currency),
        ),
        (
            "Balance Due",
            format_currency(record.get("balance_due"), currency),
        ),
    ]

    for column, (label, value) in zip(st.columns(4), values):
        with column:
            st.metric(label, value)

    details = [
        (
            "Payment Terms",
            safe_text(record.get("payment_terms"), "Pending confirmation"),
        ),
        (
            "Payment Status",
            safe_text(record.get("payment_status"), "Pending Charge"),
        ),
        (
            "Release Status",
            safe_text(record.get("release_status"), "Pending Review"),
        ),
    ]

    for column, (label, value) in zip(st.columns(3), details):
        with column:
            with st.container(border=True):
                st.markdown(f"#### {label}")
                st.write(value)

    amount_charged = to_decimal(record.get("amount_charged"))
    balance_due = to_decimal(record.get("balance_due"))

    if amount_charged <= 0:
        st.info("The charge has not been entered yet.")
    elif balance_due <= 0:
        st.success(
            "This shipment is fully paid. Release still depends on "
            "the displayed release status."
        )
    else:
        st.warning(
            "This shipment has a remaining balance. Do not release it "
            "unless payment is completed or management authorizes release."
        )


def render_payment_history(history: pd.DataFrame) -> None:
    st.subheader("Payment History")

    if history.empty:
        st.info("No individual payment transactions have been recorded yet.")
        return

    display = history.copy()

    for money_column in ["amount_paid", "balance_due"]:
        display[money_column] = display.apply(
            lambda row: format_currency(
                row[money_column],
                safe_text(row.get("currency"), "USD"),
            ),
            axis=1,
        )

    st.dataframe(display, use_container_width=True)


def main() -> None:
    apply_custom_styles()
    sidebar_shipping_options()

    role_label = get_portal_label()

    hero(
        title="Payment Lookup",
        subtitle=(
            "Look up an individual shipment or invoice, check payment terms "
            "and balance, record a branch payment, and confirm release status."
        ),
    )

    st.markdown(
        f"""
        <span class="badge-green">{role_label} Payment Tool</span>
        <span class="badge-dark">Individual Shipment Lookup</span>
        <span class="badge-red">Live Neon Update</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = get_database_engine()
        verify_required_tables(engine)
    except Exception as exc:
        st.error("The Payment Lookup page could not connect to Neon.")
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )
        return

    st.subheader("Find Shipment Payment")

    lookup_value = st.text_input(
        (
            "Search by shipment ID, invoice number, customer, receiver, "
            "destination, payment status, or release status"
        ),
        placeholder=(
            "Example: SST-2026-0026, INV-2026-0026, "
            "receiver name, or freight collect"
        ),
    )

    if not lookup_value.strip():
        st.info("Enter shipment or payment information to begin.")
        return

    try:
        matched_payments = search_payment_records(engine, lookup_value)
    except Exception as exc:
        st.error("The payment search could not be completed.")
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )
        return

    if matched_payments.empty:
        st.error("No matching shipment or payment record was found in Neon.")
        return

    st.markdown("### Matching Records")

    display_columns = [
        "shipment_id",
        "invoice_number",
        "customer_name",
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
        "shipment_status",
    ]

    st.dataframe(
        matched_payments[display_columns],
        use_container_width=True,
    )

    shipment_options = (
        matched_payments["shipment_id"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    selected_shipment_id = st.selectbox(
        "Select Shipment ID",
        shipment_options,
    )

    selected_frame = matched_payments[
        matched_payments["shipment_id"]
        .astype(str)
        .eq(selected_shipment_id)
    ]

    if selected_frame.empty:
        st.error("The selected shipment could not be loaded.")
        return

    record = selected_frame.iloc[0].to_dict()

    st.divider()
    render_payment_summary(record)

    try:
        payment_history = load_payment_history(
            engine,
            selected_shipment_id,
        )
    except Exception as exc:
        st.error("The transaction history could not be loaded.")
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )
        payment_history = pd.DataFrame()

    st.divider()
    st.subheader("Record Payment")

    current_charge = to_decimal(record.get("amount_charged"))
    current_total_paid = to_decimal(record.get("total_amount_paid"))
    current_currency = safe_text(record.get("currency"), "USD")
    current_terms = safe_text(record.get("payment_terms"), "Not Sure Yet")

    with st.form("staff_record_payment_form", clear_on_submit=False):
        left, right = st.columns(2)

        with left:
            amount_charged_input = st.number_input(
                "Total Amount Charged",
                min_value=0.0,
                step=5.0,
                value=float(current_charge),
            )

            amount_received_input = st.number_input(
                "Amount Received",
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
                ),
            )

            collected_by = st.text_input(
                "Collected By",
                value=role_label,
            )

            payment_date_value = st.date_input(
                "Payment Date",
                value=date.today(),
            )

        receipt_number = st.text_input(
            "Receipt / Transaction Reference",
            placeholder=(
                "Example: RCPT-1001, Zelle reference, "
                "card receipt, or bank confirmation"
            ),
        )

        payment_notes = st.text_area(
            "Payment Notes",
            placeholder=(
                "Add payment details, sender or receiver notes, "
                "receipt notes, or release instructions."
            ),
            height=120,
        )

        submitted = st.form_submit_button(
            "Save Payment to Neon",
            use_container_width=True,
        )

    if submitted:
        amount_charged = to_decimal(amount_charged_input)
        amount_received = to_decimal(amount_received_input)

        if amount_charged <= 0:
            st.error("Enter the total amount charged.")
        elif amount_received <= 0:
            st.error("Enter an amount received greater than zero.")
        elif current_total_paid + amount_received > amount_charged:
            st.error("This payment would exceed the total amount charged.")
        else:
            try:
                with st.spinner(
                    "Saving the payment and updating the balance..."
                ):
                    result = save_staff_payment(
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
                        receipt_number=receipt_number,
                        payment_notes=payment_notes,
                        role_label=role_label,
                    )

                st.success("Payment saved successfully to Neon.")

                confirmation = {
                    **result,
                    "amount_received": format_currency(
                        result["amount_received"],
                        result["currency"],
                    ),
                    "paid_in_new_jersey": format_currency(
                        result["paid_in_new_jersey"],
                        result["currency"],
                    ),
                    "paid_in_guyana": format_currency(
                        result["paid_in_guyana"],
                        result["currency"],
                    ),
                    "total_paid": format_currency(
                        result["total_paid"],
                        result["currency"],
                    ),
                    "balance_due": format_currency(
                        result["balance_due"],
                        result["currency"],
                    ),
                }

                st.markdown("### Payment Confirmation")
                st.dataframe(
                    pd.DataFrame([confirmation]),
                    use_container_width=True,
                )

                st.info(
                    "The branch-payment account, payment history, "
                    "and shipment balance were updated together."
                )

                if st.button(
                    "Refresh Payment Record",
                    use_container_width=True,
                ):
                    st.rerun()

            except Exception as exc:
                st.error("The payment could not be saved to Neon.")
                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error_message(exc)}"
                )

    st.divider()
    render_payment_history(payment_history)


if __name__ == "__main__":
    main()