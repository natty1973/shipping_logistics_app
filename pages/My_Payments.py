from __future__ import annotations

import html
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(
    page_title="My Payments",
    page_icon="💳",
    layout="wide",
)

SCHEMA = "solomon_shipping"

COMPANY_NAME = "Solomon Shipping and Trading Inc."
COMPANY_ADDRESS_LINE_1 = "200 Main St Rear"
COMPANY_ADDRESS_LINE_2 = "City of Orange, NJ 07050"
COMPANY_PHONE = "973-675-4921"


def get_secret(name: str) -> str:
    """Read a setting from the environment or Streamlit Secrets."""

    environment_value = os.getenv(name, "").strip()

    if environment_value:
        return environment_value

    try:
        secret_value = st.secrets.get(name, "")
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        return ""

    return str(secret_value).strip() if secret_value is not None else ""


@st.cache_resource(show_spinner=False)
def get_database_engine() -> Engine:
    """Create a reusable Neon/PostgreSQL connection."""

    database_url = get_secret("DATABASE_URL")

    if database_url:
        if database_url.startswith("postgres://"):
            database_url = (
                "postgresql://"
                + database_url[len("postgres://"):]
            )

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
            raise RuntimeError(
                "Missing Streamlit Secrets: "
                + ", ".join(missing)
            )

        try:
            port = int(settings["port"])
        except ValueError:
            port = 5432

        database_target = URL.create(
            drivername="postgresql+psycopg2",
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
            "application_name": "solomon_shipping_my_payments",
        },
    )

    with engine.connect() as connection:
        connection.execute(text("SELECT 1;"))

    return engine


def safe_error_message(error: Exception) -> str:
    """Remove credentials if a database error includes them."""

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


def verify_required_tables(engine: Engine) -> None:
    """Confirm the customer payment tables exist in Neon."""

    required_tables = [
        f"{SCHEMA}.shipments",
        f"{SCHEMA}.branch_payments",
        f"{SCHEMA}.payments",
    ]

    missing_tables: list[str] = []

    with engine.connect() as connection:
        for relation_name in required_tables:
            existing_relation = connection.execute(
                text("SELECT TO_REGCLASS(:relation_name);"),
                {"relation_name": relation_name},
            ).scalar_one_or_none()

            if existing_relation is None:
                missing_tables.append(relation_name)

    if missing_tables:
        raise RuntimeError(
            "Required Neon tables are missing: "
            + ", ".join(missing_tables)
        )


def safe_text(
    value: Any,
    default: str = "Not Available",
) -> str:
    """Return a clean display value for nullable fields."""

    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    clean_value = str(value).strip()

    return clean_value or default


def pdf_text(
    value: Any,
    default: str = "Not Available",
) -> str:
    """Escape dynamic values before placing them in ReportLab paragraphs."""

    return html.escape(
        safe_text(value, default)
    ).replace("\n", "<br/>")


def to_decimal(value: Any) -> Decimal:
    """Convert a value into a two-decimal Decimal."""

    if value is None:
        return Decimal("0.00")

    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def format_currency(
    value: Any,
    currency: str = "USD",
) -> str:
    """Format a payment amount using its recorded currency."""

    amount = to_decimal(value)

    symbol = {
        "USD": "$",
        "GYD": "G$",
        "CAD": "C$",
        "GBP": "£",
    }.get(
        currency.upper(),
        f"{currency.upper()} ",
    )

    return f"{symbol}{amount:,.2f}"


def format_date(
    value: Any,
    default: str = "Not Available",
) -> str:
    """Format a database date or datetime for display."""

    if value is None:
        return default

    try:
        timestamp = pd.to_datetime(value)
    except (TypeError, ValueError):
        return safe_text(value, default)

    if pd.isna(timestamp):
        return default

    if timestamp.hour or timestamp.minute or timestamp.second:
        return timestamp.strftime("%B %d, %Y at %I:%M %p")

    return timestamp.strftime("%B %d, %Y")


def first_available(
    *values: Any,
    default: Any = None,
) -> Any:
    """Return the first value that is not null or blank."""

    for value in values:
        if value is None:
            continue

        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return default


def find_customer_payment(
    engine: Engine,
    lookup_value: str,
) -> dict[str, Any] | None:
    """
    Find one shipment by exact Shipment ID or exact Invoice Number.

    Customer lookup is intentionally exact. Searching by customer, sender,
    or receiver name on a public page could expose another customer's records.
    """

    query = text(
        f"""
        SELECT
            s.shipment_id,
            s.customer_id,
            s.customer_name,
            s.shipment_date,
            s.destination_city,
            s.destination_country,
            s.current_status AS shipment_status,
            s.amount_charged AS shipment_amount_charged,
            s.amount_paid AS shipment_amount_paid,
            s.balance_due AS shipment_balance_due,
            s.payment_status AS shipment_payment_status,
            s.release_status AS shipment_release_status,
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
            bp.payment_date,
            bp.currency,
            bp.notes AS branch_payment_notes,
            bp.created_at AS invoice_created_at,
            bp.updated_at AS invoice_updated_at
        FROM {SCHEMA}.shipments AS s
        LEFT JOIN LATERAL (
            SELECT branch_record.*
            FROM {SCHEMA}.branch_payments AS branch_record
            WHERE branch_record.shipment_id = s.shipment_id
            ORDER BY branch_record.updated_at DESC
            LIMIT 1
        ) AS bp ON TRUE
        WHERE
            UPPER(BTRIM(s.shipment_id))
                = UPPER(BTRIM(:lookup_value))
            OR
            UPPER(BTRIM(COALESCE(bp.invoice_number, '')))
                = UPPER(BTRIM(:lookup_value))
        LIMIT 1;
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            query,
            {"lookup_value": lookup_value.strip()},
        ).mappings().first()

    return dict(row) if row else None


def load_customer_payment_history(
    engine: Engine,
    shipment_id: str,
) -> pd.DataFrame:
    """Load customer-safe payment transaction history."""

    query = text(
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
            collected_by
        FROM {SCHEMA}.payments
        WHERE
            UPPER(BTRIM(shipment_id))
                = UPPER(BTRIM(:shipment_id))
        ORDER BY
            payment_date DESC NULLS LAST,
            created_at DESC;
        """
    )

    with engine.connect() as connection:
        return pd.read_sql_query(
            query,
            connection,
            params={"shipment_id": shipment_id},
        )


def get_effective_payment_values(
    record: dict[str, Any],
) -> dict[str, Any]:
    """
    Use the branch-payment account when available and fall back to the
    shipment-level payment fields for newly requested shipments.
    """

    currency = safe_text(
        record.get("currency"),
        "USD",
    )

    amount_charged = first_available(
        record.get("amount_charged"),
        record.get("shipment_amount_charged"),
        default=Decimal("0.00"),
    )

    total_paid = first_available(
        record.get("total_amount_paid"),
        record.get("shipment_amount_paid"),
        default=Decimal("0.00"),
    )

    balance_due = first_available(
        record.get("balance_due"),
        record.get("shipment_balance_due"),
        default=Decimal("0.00"),
    )

    payment_status = safe_text(
        first_available(
            record.get("payment_status"),
            record.get("shipment_payment_status"),
            default="Pending Charge",
        ),
        "Pending Charge",
    )

    release_status = safe_text(
        first_available(
            record.get("release_status"),
            record.get("shipment_release_status"),
            default="Pending Review",
        ),
        "Pending Review",
    )

    return {
        "currency": currency,
        "amount_charged": to_decimal(amount_charged),
        "paid_nj": to_decimal(record.get("amount_paid_nj")),
        "paid_guyana": to_decimal(record.get("amount_paid_guyana")),
        "total_paid": to_decimal(total_paid),
        "balance_due": to_decimal(balance_due),
        "payment_status": payment_status,
        "release_status": release_status,
    }


def invoice_is_available(
    record: dict[str, Any],
) -> bool:
    """Return True only after staff has created a priced invoice record."""

    invoice_number = safe_text(
        record.get("invoice_number"),
        "",
    )

    branch_payment_id = safe_text(
        record.get("branch_payment_id"),
        "",
    )

    values = get_effective_payment_values(record)

    return bool(
        invoice_number
        and branch_payment_id
        and values["amount_charged"] > 0
    )


def build_invoice_pdf(
    record: dict[str, Any],
    payment_history: pd.DataFrame,
) -> bytes:
    """Generate a professional invoice PDF from the current Neon record."""

    values = get_effective_payment_values(record)

    invoice_number = safe_text(
        record.get("invoice_number"),
        "Not issued",
    )

    shipment_id = safe_text(
        record.get("shipment_id")
    )

    currency = values["currency"]

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.55 * inch,
        title=f"Invoice {invoice_number}",
        author=COMPANY_NAME,
        subject=f"Shipment invoice for {shipment_id}",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=HexColor("#0B6E4F"),
        alignment=TA_RIGHT,
        spaceAfter=4,
    )

    company_style = ParagraphStyle(
        "Company",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=HexColor("#053B2D"),
        alignment=TA_LEFT,
    )

    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=HexColor("#374151"),
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=HexColor("#111827"),
    )

    body_bold_style = ParagraphStyle(
        "BodyBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )

    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=HexColor("#0B6E4F"),
        spaceBefore=8,
        spaceAfter=5,
    )

    note_style = ParagraphStyle(
        "Note",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=HexColor("#4B5563"),
        backColor=HexColor("#F3F4F6"),
        borderColor=HexColor("#D1D5DB"),
        borderWidth=0.5,
        borderPadding=7,
        spaceBefore=7,
        spaceAfter=7,
    )

    right_style = ParagraphStyle(
        "Right",
        parent=body_style,
        alignment=TA_RIGHT,
    )

    center_style = ParagraphStyle(
        "Center",
        parent=body_style,
        alignment=TA_CENTER,
    )

    story: list[Any] = []

    company_block = Paragraph(
        (
            f"<b>{pdf_text(COMPANY_NAME)}</b><br/>"
            f"{pdf_text(COMPANY_ADDRESS_LINE_1)}<br/>"
            f"{pdf_text(COMPANY_ADDRESS_LINE_2)}<br/>"
            f"Phone: {pdf_text(COMPANY_PHONE)}"
        ),
        company_style,
    )

    invoice_block = Paragraph(
        (
            "INVOICE<br/>"
            f"<font size='10' color='#374151'>"
            f"{pdf_text(invoice_number)}</font>"
        ),
        title_style,
    )

    header_table = Table(
        [[company_block, invoice_block]],
        colWidths=[4.3 * inch, 2.6 * inch],
    )

    header_table.setStyle(
        TableStyle(
            [
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "LINEBELOW",
                    (0, 0),
                    (-1, -1),
                    1.5,
                    HexColor("#D4AF37"),
                ),
            ]
        )
    )

    story.append(header_table)
    story.append(Spacer(1, 0.16 * inch))

    invoice_date = first_available(
        record.get("invoice_created_at"),
        record.get("payment_date"),
        record.get("shipment_date"),
        default=datetime.now(),
    )

    metadata_data = [
        [
            Paragraph("<b>Invoice Number</b>", body_bold_style),
            Paragraph(pdf_text(invoice_number), body_style),
            Paragraph("<b>Invoice Date</b>", body_bold_style),
            Paragraph(
                pdf_text(format_date(invoice_date)),
                right_style,
            ),
        ],
        [
            Paragraph("<b>Shipment ID</b>", body_bold_style),
            Paragraph(pdf_text(shipment_id), body_style),
            Paragraph("<b>Shipment Status</b>", body_bold_style),
            Paragraph(
                pdf_text(record.get("shipment_status")),
                right_style,
            ),
        ],
    ]

    metadata_table = Table(
        metadata_data,
        colWidths=[
            1.15 * inch,
            2.25 * inch,
            1.3 * inch,
            2.2 * inch,
        ],
    )

    metadata_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    HexColor("#F8FAFC"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    HexColor("#D1D5DB"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    HexColor("#E5E7EB"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
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

    story.append(metadata_table)
    story.append(Spacer(1, 0.14 * inch))

    bill_to = Paragraph(
        (
            "<b>Bill To</b><br/>"
            f"{pdf_text(record.get('customer_name'))}<br/>"
            f"Customer ID: {pdf_text(record.get('customer_id'))}"
        ),
        body_style,
    )

    destination = Paragraph(
        (
            "<b>Shipment Destination</b><br/>"
            f"{pdf_text(record.get('destination_city'))}, "
            f"{pdf_text(record.get('destination_country'))}<br/>"
            f"Service status: {pdf_text(record.get('shipment_status'))}"
        ),
        body_style,
    )

    party_table = Table(
        [[bill_to, destination]],
        colWidths=[3.45 * inch, 3.45 * inch],
    )

    party_table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    HexColor("#D1D5DB"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    HexColor("#E5E7EB"),
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

    story.append(party_table)
    story.append(Spacer(1, 0.16 * inch))
    story.append(Paragraph("Invoice Summary", section_style))

    invoice_rows = [
        [
            Paragraph("<b>Description</b>", body_bold_style),
            Paragraph("<b>Amount</b>", body_bold_style),
        ],
        [
            Paragraph(
                (
                    f"Shipping services for Shipment "
                    f"{pdf_text(shipment_id)}"
                ),
                body_style,
            ),
            Paragraph(
                pdf_text(
                    format_currency(
                        values["amount_charged"],
                        currency,
                    )
                ),
                right_style,
            ),
        ],
        [
            Paragraph("Payments received in New Jersey", body_style),
            Paragraph(
                pdf_text(
                    format_currency(
                        values["paid_nj"],
                        currency,
                    )
                ),
                right_style,
            ),
        ],
        [
            Paragraph("Payments received in Guyana", body_style),
            Paragraph(
                pdf_text(
                    format_currency(
                        values["paid_guyana"],
                        currency,
                    )
                ),
                right_style,
            ),
        ],
        [
            Paragraph("<b>Total paid</b>", body_bold_style),
            Paragraph(
                (
                    f"<b>{pdf_text(format_currency(values['total_paid'], currency))}</b>"
                ),
                right_style,
            ),
        ],
        [
            Paragraph("<b>Balance due</b>", body_bold_style),
            Paragraph(
                (
                    f"<b>{pdf_text(format_currency(values['balance_due'], currency))}</b>"
                ),
                right_style,
            ),
        ],
    ]

    invoice_table = Table(
        invoice_rows,
        colWidths=[5.45 * inch, 1.45 * inch],
        repeatRows=1,
    )

    invoice_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    HexColor("#0B6E4F"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    HexColor("#D1D5DB"),
                ),
                (
                    "BACKGROUND",
                    (0, 1),
                    (-1, -1),
                    colors.white,
                ),
                (
                    "BACKGROUND",
                    (0, -1),
                    (-1, -1),
                    HexColor("#FFF7D6"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
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

    story.append(invoice_table)
    story.append(Spacer(1, 0.14 * inch))

    payment_detail_rows = [
        [
            Paragraph("<b>Payment Terms</b>", body_bold_style),
            Paragraph(
                pdf_text(
                    record.get("payment_terms"),
                    "Pending confirmation",
                ),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Payment Responsibility</b>", body_bold_style),
            Paragraph(
                pdf_text(
                    record.get("payment_responsibility"),
                    "Pending confirmation",
                ),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Payment Status</b>", body_bold_style),
            Paragraph(
                pdf_text(values["payment_status"]),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Release Status</b>", body_bold_style),
            Paragraph(
                pdf_text(values["release_status"]),
                body_style,
            ),
        ],
    ]

    payment_details_table = Table(
        payment_detail_rows,
        colWidths=[1.75 * inch, 5.15 * inch],
    )

    payment_details_table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    HexColor("#D1D5DB"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    HexColor("#E5E7EB"),
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

    story.append(payment_details_table)

    if not payment_history.empty:
        story.append(Spacer(1, 0.14 * inch))
        story.append(Paragraph("Payment History", section_style))

        history_rows: list[list[Any]] = [
            [
                Paragraph("<b>Date</b>", body_bold_style),
                Paragraph("<b>Payment ID</b>", body_bold_style),
                Paragraph("<b>Method</b>", body_bold_style),
                Paragraph("<b>Amount</b>", body_bold_style),
                Paragraph("<b>Balance</b>", body_bold_style),
            ]
        ]

        for _, payment in payment_history.iterrows():
            payment_currency = safe_text(
                payment.get("currency"),
                currency,
            )

            history_rows.append(
                [
                    Paragraph(
                        pdf_text(
                            format_date(
                                payment.get("payment_date")
                            )
                        ),
                        small_style,
                    ),
                    Paragraph(
                        pdf_text(
                            payment.get("payment_id")
                        ),
                        small_style,
                    ),
                    Paragraph(
                        pdf_text(
                            payment.get("payment_method")
                        ),
                        small_style,
                    ),
                    Paragraph(
                        pdf_text(
                            format_currency(
                                payment.get("amount_paid"),
                                payment_currency,
                            )
                        ),
                        right_style,
                    ),
                    Paragraph(
                        pdf_text(
                            format_currency(
                                payment.get("balance_due"),
                                payment_currency,
                            )
                        ),
                        right_style,
                    ),
                ]
            )

        history_table = Table(
            history_rows,
            colWidths=[
                1.25 * inch,
                1.35 * inch,
                1.3 * inch,
                1.35 * inch,
                1.35 * inch,
            ],
            repeatRows=1,
        )

        history_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        HexColor("#E6F4EF"),
                    ),
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.4,
                        HexColor("#D1D5DB"),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "MIDDLE",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                ]
            )
        )

        story.append(history_table)

    story.append(Spacer(1, 0.16 * inch))

    story.append(
        KeepTogether(
            [
                Paragraph(
                    (
                        "<b>Important:</b> This invoice reflects the current "
                        "payment record in Solomon Shipping's system. A zero "
                        "balance does not override customs, shipment, identity, "
                        "or release requirements. The displayed release status "
                        "must also permit release."
                    ),
                    note_style,
                ),
                Paragraph(
                    (
                        f"Questions about this invoice? Call "
                        f"{pdf_text(COMPANY_PHONE)}."
                    ),
                    center_style,
                ),
            ]
        )
    )

    def draw_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(HexColor("#6B7280"))
        canvas.drawString(
            0.55 * inch,
            0.28 * inch,
            f"{COMPANY_NAME} - Invoice {invoice_number}",
        )
        canvas.drawRightString(
            7.95 * inch,
            0.28 * inch,
            f"Page {doc.page}",
        )
        canvas.restoreState()

    document.build(
        story,
        onFirstPage=draw_page,
        onLaterPages=draw_page,
    )

    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


def render_shipment_identity(
    record: dict[str, Any],
) -> None:
    """Show the shipment and invoice being viewed."""

    shipment_id = safe_text(record.get("shipment_id"))

    invoice_number = safe_text(
        record.get("invoice_number"),
        "Not issued yet",
    )

    customer_name = safe_text(
        record.get("customer_name")
    )

    shipment_status = safe_text(
        record.get("shipment_status")
    )

    columns = st.columns(4)

    values = [
        ("Shipment ID", shipment_id),
        ("Invoice Number", invoice_number),
        ("Customer", customer_name),
        ("Shipment Status", shipment_status),
    ]

    for column, (label, value) in zip(
        columns,
        values,
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"#### {label}")
                st.write(value)

    destination_city = safe_text(
        record.get("destination_city")
    )

    destination_country = safe_text(
        record.get("destination_country")
    )

    with st.container(border=True):
        st.markdown("#### Destination")
        st.write(
            f"{destination_city}, "
            f"{destination_country}"
        )


def render_payment_details(
    record: dict[str, Any],
) -> None:
    """Display payment terms and branch collection details."""

    st.subheader("Payment Details")

    has_branch_account = bool(
        safe_text(
            record.get("branch_payment_id"),
            "",
        )
    )

    if not has_branch_account:
        st.info(
            "This shipment exists in Neon, but its invoice and "
            "branch-payment account have not been created yet."
        )

    columns = st.columns(3)

    values = [
        (
            "Payment Terms",
            safe_text(
                record.get("payment_terms"),
                "Pending confirmation",
            ),
        ),
        (
            "Payment Responsibility",
            safe_text(
                record.get("payment_responsibility"),
                "Pending confirmation",
            ),
        ),
        (
            "Where Payment Was Collected",
            safe_text(
                record.get("payment_collected_at"),
                "No payment recorded",
            ),
        ),
    ]

    for column, (label, value) in zip(
        columns,
        values,
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"#### {label}")
                st.write(value)


def render_payment_summary(
    record: dict[str, Any],
) -> None:
    """Render customer payment and release status."""

    values = get_effective_payment_values(
        record
    )

    amount_charged = values[
        "amount_charged"
    ]

    paid_nj = values["paid_nj"]

    paid_guyana = values[
        "paid_guyana"
    ]

    total_paid = values[
        "total_paid"
    ]

    balance_due = values[
        "balance_due"
    ]

    currency = values["currency"]

    payment_status = values[
        "payment_status"
    ]

    release_status = values[
        "release_status"
    ]

    columns = st.columns(4)

    summary_values = [
        (
            "Amount Charged",
            format_currency(
                amount_charged,
                currency,
            ),
        ),
        (
            "Total Paid",
            format_currency(
                total_paid,
                currency,
            ),
        ),
        (
            "Balance Due",
            format_currency(
                balance_due,
                currency,
            ),
        ),
        (
            "Payment Status",
            payment_status,
        ),
    ]

    for column, (label, value) in zip(
        columns,
        summary_values,
    ):
        with column:
            st.metric(label, value)

    branch_columns = st.columns(2)

    with branch_columns[0]:
        with st.container(border=True):
            st.markdown(
                "#### Paid in New Jersey"
            )

            st.write(
                format_currency(
                    paid_nj,
                    currency,
                )
            )

    with branch_columns[1]:
        with st.container(border=True):
            st.markdown(
                "#### Paid in Guyana"
            )

            st.write(
                format_currency(
                    paid_guyana,
                    currency,
                )
            )

    with st.container(border=True):
        st.markdown(
            "#### Release Status"
        )

        st.write(release_status)

    if amount_charged <= 0:
        st.info(
            "Charges have not been entered yet. "
            "Contact Solomon Shipping for pricing "
            "or invoice information."
        )

    elif (
        balance_due <= 0
        and payment_status.lower()
        in {
            "paid",
            "settled",
            "completed",
        }
    ):
        st.success(
            "This shipment is recorded as fully paid. "
            "Release is still subject to the displayed "
            "release status."
        )

    elif balance_due > 0:
        st.warning(
            "This shipment has a remaining balance. "
            "Payment may be required before release."
        )

    else:
        st.info(
            "Payment information is awaiting confirmation."
        )


def render_invoice_download(
    record: dict[str, Any],
    payment_history: pd.DataFrame,
) -> None:
    """Show the official invoice download when pricing is available."""

    st.subheader("Download Invoice")

    if not invoice_is_available(record):
        st.info(
            "The official invoice will appear here after Solomon "
            "Shipping confirms the charge and creates the invoice."
        )
        return

    invoice_number = safe_text(
        record.get("invoice_number")
    )

    invoice_pdf = build_invoice_pdf(
        record,
        payment_history,
    )

    st.download_button(
        label="Download Official Invoice PDF",
        data=invoice_pdf,
        file_name=f"{invoice_number}_Solomon_Shipping_Invoice.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    st.caption(
        "The PDF is generated from the current live Neon payment record, "
        "so the customer can return later and download the latest invoice."
    )


def render_payment_history(
    history: pd.DataFrame,
) -> None:
    """Show individual customer payment transactions."""

    st.subheader("Payment History")

    if history.empty:
        st.info(
            "No individual payment transactions "
            "have been recorded yet."
        )
        return

    display = history.copy()

    for column in [
        "amount_paid",
        "balance_due",
    ]:
        if column in display.columns:
            display[column] = display.apply(
                lambda row: format_currency(
                    row[column],
                    safe_text(
                        row.get("currency"),
                        "USD",
                    ),
                ),
                axis=1,
            )

    st.dataframe(
        display,
        use_container_width=True,
    )


def main() -> None:
    """Customer-facing live payment lookup and invoice page."""

    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="My Payments",
        subtitle=(
            "Look up your shipment invoice, payment terms, "
            "New Jersey and Guyana payment totals, balance due, "
            "release status, and downloadable official invoice."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Customer Payment Lookup</span>
        <span class="badge-dark">Live Neon Balance</span>
        <span class="badge-red">Downloadable Invoice</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = get_database_engine()

        verify_required_tables(
            engine
        )

    except Exception as exc:
        st.error(
            "The My Payments page could not connect "
            "to the Solomon Shipping payment records "
            "in Neon."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    st.subheader(
        "Find Your Payment"
    )

    lookup_value = st.text_input(
        "Enter your Shipment ID or Invoice Number",
        placeholder=(
            "Example: SST-2026-0026 "
            "or INV-2026-0026"
        ),
    )

    st.caption(
        "For customer privacy, this page accepts "
        "an exact Shipment ID or exact Invoice Number only."
    )

    if not lookup_value.strip():
        st.info(
            "Enter your Shipment ID or Invoice Number "
            "to view payment details."
        )

        return

    try:
        record = find_customer_payment(
            engine,
            lookup_value,
        )

    except Exception as exc:
        st.error(
            "The payment lookup could not be completed."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    if record is None:
        st.error(
            "No shipment or payment record was found "
            "with that exact ID."
        )

        return

    shipment_id = safe_text(
        record.get("shipment_id"),
        lookup_value.strip(),
    )

    try:
        payment_history = (
            load_customer_payment_history(
                engine,
                shipment_id,
            )
        )

    except Exception as exc:
        st.error(
            "The shipment was found, but its payment "
            "history could not be loaded."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    st.divider()

    render_shipment_identity(
        record
    )

    st.divider()

    render_payment_details(
        record
    )

    render_payment_summary(
        record
    )

    st.divider()

    render_invoice_download(
        record,
        payment_history,
    )

    st.divider()

    render_payment_history(
        payment_history
    )

    st.divider()

    st.subheader(
        "Payment Help"
    )

    with st.container(
        border=True
    ):
        st.markdown(
            """
            If the release status shows **Hold Until Paid**
            or **Hold Until Balance Paid**, contact Solomon
            Shipping and Trading Inc. to confirm payment
            instructions.

            **Phone:** 973-675-4921  
            **Address:** 200 Main St Rear, City of Orange, NJ 07050
            """
        )


if __name__ == "__main__":
    main()