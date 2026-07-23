from __future__ import annotations

import html
import os
import re
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
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
    page_title="Contact Support",
    page_icon="☎️",
    layout="wide",
)

SCHEMA = "solomon_shipping"
SUPPORT_TABLE = "support_requests"

COMPANY_NAME = "Solomon Shipping and Trading Inc."
COMPANY_ADDRESS_LINE_1 = "200 Main St Rear"
COMPANY_ADDRESS_LINE_2 = "City of Orange, NJ 07050"
COMPANY_PHONE = "973-675-4921"

SUPPORT_TOPICS = [
    "Shipment Status",
    "Pickup Scheduling",
    "Payment Question",
    "Delivery Question",
    "Change Contact Information",
    "General Question",
]


def get_secret(name: str) -> str:
    """Read a database setting from the environment or Streamlit Secrets."""

    value = os.getenv(name, "").strip()

    if value:
        return value

    try:
        value = st.secrets.get(name, "")
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        return ""

    return str(value).strip() if value is not None else ""


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
            "application_name": "solomon_shipping_contact_support",
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

    return re.sub(
        r"password\s*=\s*[^,\s]+",
        "password=***",
        message,
        flags=re.IGNORECASE,
    )


def verify_required_tables(engine: Engine) -> None:
    """Confirm the shipment and support-request tables exist."""

    required_tables = [
        f"{SCHEMA}.shipments",
        f"{SCHEMA}.customers",
        f"{SCHEMA}.{SUPPORT_TABLE}",
    ]

    missing_tables: list[str] = []

    with engine.connect() as connection:
        for relation_name in required_tables:
            exists = connection.execute(
                text("SELECT TO_REGCLASS(:relation_name);"),
                {"relation_name": relation_name},
            ).scalar_one_or_none()

            if exists is None:
                missing_tables.append(relation_name)

    if missing_tables:
        raise RuntimeError(
            "Required Neon tables are missing: "
            + ", ".join(missing_tables)
            + ". Run the Contact Support SQL migration first."
        )


def safe_text(
    value: Any,
    default: str = "Not Available",
) -> str:
    """Return a clean display value."""

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
    """Escape dynamic values before placing them in a PDF paragraph."""

    return html.escape(
        safe_text(value, default)
    ).replace("\n", "<br/>")


def format_datetime(
    value: Any,
    default: str = "Not Available",
) -> str:
    """Format a ticket timestamp."""

    if value is None:
        return default

    try:
        timestamp = pd.to_datetime(value)
    except (TypeError, ValueError):
        return safe_text(value, default)

    if pd.isna(timestamp):
        return default

    return timestamp.strftime("%B %d, %Y at %I:%M %p")


def normalize_shipment_id(value: str) -> str:
    """Normalize an optional shipment ID."""

    return value.strip().upper()


def is_valid_email(value: str) -> bool:
    """Perform a lightweight email-format check."""

    if not value.strip():
        return True

    return bool(
        re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            value.strip(),
        )
    )


def next_support_request_id(
    connection: Any,
    year: int,
) -> str:
    """Generate a readable support ID inside a locked transaction."""

    connection.execute(
        text(
            """
            SELECT PG_ADVISORY_XACT_LOCK(
                HASHTEXT(:lock_name)
            );
            """
        ),
        {
            "lock_name": (
                f"{SCHEMA}.{SUPPORT_TABLE}."
                f"support_request_id.{year}"
            )
        },
    )

    pattern = f"^SUP-{year}-[0-9]+$"

    next_number = connection.execute(
        text(
            f"""
            SELECT
                COALESCE(
                    MAX(
                        SPLIT_PART(
                            support_request_id,
                            '-',
                            3
                        )::INTEGER
                    ),
                    0
                ) + 1
            FROM {SCHEMA}.{SUPPORT_TABLE}
            WHERE support_request_id ~ :pattern;
            """
        ),
        {"pattern": pattern},
    ).scalar_one()

    return f"SUP-{year}-{int(next_number):04d}"


def save_support_request(
    engine: Engine,
    customer_name: str,
    phone: str,
    email: str,
    shipment_id: str,
    support_topic: str,
    message: str,
) -> dict[str, Any]:
    """Save a customer support request to Neon."""

    normalized_shipment_id = normalize_shipment_id(shipment_id)
    current_year = datetime.now().year

    with engine.begin() as connection:
        customer_id: str | None = None
        stored_shipment_id: str | None = None

        if normalized_shipment_id:
            shipment = connection.execute(
                text(
                    f"""
                    SELECT
                        shipment_id,
                        customer_id,
                        customer_name
                    FROM {SCHEMA}.shipments
                    WHERE
                        UPPER(BTRIM(shipment_id))
                        =
                        UPPER(BTRIM(:shipment_id))
                    LIMIT 1;
                    """
                ),
                {
                    "shipment_id": (
                        normalized_shipment_id
                    )
                },
            ).mappings().first()

            if shipment is None:
                raise ValueError(
                    "The Shipment ID was not found. "
                    "Check the ID or leave the field blank."
                )

            stored_shipment_id = str(
                shipment["shipment_id"]
            )

            customer_id = (
                str(shipment["customer_id"])
                if shipment.get("customer_id")
                else None
            )

        support_request_id = (
            next_support_request_id(
                connection,
                current_year,
            )
        )

        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.{SUPPORT_TABLE} (
                    support_request_id,
                    shipment_id,
                    customer_id,
                    customer_name,
                    phone,
                    email,
                    support_topic,
                    message,
                    request_status,
                    priority,
                    source,
                    created_at,
                    updated_at
                )
                VALUES (
                    :support_request_id,
                    :shipment_id,
                    :customer_id,
                    :customer_name,
                    :phone,
                    NULLIF(:email, ''),
                    :support_topic,
                    :message,
                    'Open',
                    'Normal',
                    'Customer Portal',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                );
                """
            ),
            {
                "support_request_id": (
                    support_request_id
                ),
                "shipment_id": stored_shipment_id,
                "customer_id": customer_id,
                "customer_name": (
                    customer_name.strip()
                ),
                "phone": phone.strip(),
                "email": email.strip(),
                "support_topic": support_topic,
                "message": message.strip(),
            },
        )

        saved_record = connection.execute(
            text(
                f"""
                SELECT
                    support_request_id,
                    shipment_id,
                    customer_id,
                    customer_name,
                    phone,
                    email,
                    support_topic,
                    message,
                    request_status,
                    priority,
                    source,
                    assigned_to,
                    resolution_notes,
                    created_at,
                    updated_at,
                    closed_at
                FROM {SCHEMA}.{SUPPORT_TABLE}
                WHERE
                    support_request_id
                        = :support_request_id;
                """
            ),
            {
                "support_request_id": (
                    support_request_id
                )
            },
        ).mappings().first()

    if saved_record is None:
        raise RuntimeError(
            "The support request was saved, but the ticket "
            "could not be reloaded."
        )

    return dict(saved_record)


def find_support_ticket(
    engine: Engine,
    support_request_id: str,
    phone: str,
) -> dict[str, Any] | None:
    """Retrieve a permanent support ticket using its ID and phone number."""

    clean_ticket_id = support_request_id.strip().upper()
    clean_phone = phone.strip()

    if not clean_ticket_id or not clean_phone:
        return None

    with engine.connect() as connection:
        record = connection.execute(
            text(
                f"""
                SELECT
                    support_request_id,
                    shipment_id,
                    customer_id,
                    customer_name,
                    phone,
                    email,
                    support_topic,
                    message,
                    request_status,
                    priority,
                    source,
                    assigned_to,
                    resolution_notes,
                    created_at,
                    updated_at,
                    closed_at
                FROM {SCHEMA}.{SUPPORT_TABLE}
                WHERE
                    UPPER(BTRIM(support_request_id))
                    =
                    UPPER(BTRIM(:support_request_id))
                    AND
                    REGEXP_REPLACE(
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
                "support_request_id": (
                    clean_ticket_id
                ),
                "phone": clean_phone,
            },
        ).mappings().first()

    return dict(record) if record else None


def build_support_ticket_pdf(
    record: dict[str, Any],
) -> bytes:
    """Generate a permanent support-ticket confirmation PDF."""

    ticket_id = safe_text(
        record.get("support_request_id")
    )

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"Support Ticket {ticket_id}",
        author=COMPANY_NAME,
        subject="Customer support request confirmation",
    )

    styles = getSampleStyleSheet()

    company_style = ParagraphStyle(
        "Company",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=HexColor("#053B2D"),
        alignment=TA_LEFT,
    )

    title_style = ParagraphStyle(
        "TicketTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=HexColor("#0B6E4F"),
        alignment=TA_LEFT,
        spaceAfter=4,
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

    center_style = ParagraphStyle(
        "Center",
        parent=body_style,
        alignment=TA_CENTER,
    )

    story: list[Any] = []

    story.append(
        Paragraph(
            (
                f"<b>{pdf_text(COMPANY_NAME)}</b><br/>"
                f"{pdf_text(COMPANY_ADDRESS_LINE_1)}<br/>"
                f"{pdf_text(COMPANY_ADDRESS_LINE_2)}<br/>"
                f"Phone: {pdf_text(COMPANY_PHONE)}"
            ),
            company_style,
        )
    )

    story.append(Spacer(1, 0.14 * inch))

    story.append(
        Paragraph(
            "SUPPORT TICKET CONFIRMATION",
            title_style,
        )
    )

    story.append(
        Paragraph(
            (
                "This document confirms that Solomon Shipping received "
                "the support request shown below."
            ),
            body_style,
        )
    )

    story.append(Spacer(1, 0.14 * inch))

    ticket_rows = [
        [
            Paragraph("<b>Support Ticket ID</b>", body_bold_style),
            Paragraph(pdf_text(ticket_id), body_style),
            Paragraph("<b>Status</b>", body_bold_style),
            Paragraph(
                pdf_text(record.get("request_status")),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Submitted</b>", body_bold_style),
            Paragraph(
                pdf_text(
                    format_datetime(
                        record.get("created_at")
                    )
                ),
                body_style,
            ),
            Paragraph("<b>Priority</b>", body_bold_style),
            Paragraph(
                pdf_text(record.get("priority")),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Shipment ID</b>", body_bold_style),
            Paragraph(
                pdf_text(
                    record.get("shipment_id"),
                    "Not provided",
                ),
                body_style,
            ),
            Paragraph("<b>Support Topic</b>", body_bold_style),
            Paragraph(
                pdf_text(record.get("support_topic")),
                body_style,
            ),
        ],
    ]

    ticket_table = Table(
        ticket_rows,
        colWidths=[
            1.25 * inch,
            2.1 * inch,
            1.05 * inch,
            2.3 * inch,
        ],
    )

    ticket_table.setStyle(
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

    story.append(ticket_table)
    story.append(Spacer(1, 0.15 * inch))

    story.append(
        Paragraph(
            "Customer Contact Information",
            section_style,
        )
    )

    customer_rows = [
        [
            Paragraph("<b>Full Name</b>", body_bold_style),
            Paragraph(
                pdf_text(record.get("customer_name")),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Phone Number</b>", body_bold_style),
            Paragraph(
                pdf_text(record.get("phone")),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Email Address</b>", body_bold_style),
            Paragraph(
                pdf_text(
                    record.get("email"),
                    "Not provided",
                ),
                body_style,
            ),
        ],
    ]

    customer_table = Table(
        customer_rows,
        colWidths=[
            1.5 * inch,
            5.2 * inch,
        ],
    )

    customer_table.setStyle(
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

    story.append(customer_table)
    story.append(Spacer(1, 0.15 * inch))

    story.append(
        Paragraph(
            "Customer Message",
            section_style,
        )
    )

    message_table = Table(
        [
            [
                Paragraph(
                    pdf_text(
                        record.get("message")
                    ),
                    body_style,
                )
            ]
        ],
        colWidths=[6.7 * inch],
    )

    message_table.setStyle(
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
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.white,
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

    story.append(message_table)

    assigned_to = safe_text(
        record.get("assigned_to"),
        "",
    )

    resolution_notes = safe_text(
        record.get("resolution_notes"),
        "",
    )

    if assigned_to or resolution_notes:
        story.append(Spacer(1, 0.15 * inch))
        story.append(
            Paragraph(
                "Current Support Update",
                section_style,
            )
        )

        update_rows = [
            [
                Paragraph("<b>Assigned To</b>", body_bold_style),
                Paragraph(
                    pdf_text(
                        assigned_to,
                        "Not assigned",
                    ),
                    body_style,
                ),
            ],
            [
                Paragraph("<b>Resolution Notes</b>", body_bold_style),
                Paragraph(
                    pdf_text(
                        resolution_notes,
                        "No resolution notes yet",
                    ),
                    body_style,
                ),
            ],
        ]

        update_table = Table(
            update_rows,
            colWidths=[
                1.5 * inch,
                5.2 * inch,
            ],
        )

        update_table.setStyle(
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

        story.append(update_table)

    story.append(Spacer(1, 0.16 * inch))

    story.append(
        KeepTogether(
            [
                Paragraph(
                    (
                        "<b>Keep this document:</b> Use the Support Ticket ID "
                        "when contacting Solomon Shipping. This confirmation "
                        "is not a shipping invoice, receipt, pickup approval, "
                        "or delivery guarantee."
                    ),
                    note_style,
                ),
                Paragraph(
                    (
                        f"Questions? Call {pdf_text(COMPANY_PHONE)}."
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
            0.6 * inch,
            0.3 * inch,
            f"{COMPANY_NAME} - Support Ticket {ticket_id}",
        )
        canvas.drawRightString(
            7.9 * inch,
            0.3 * inch,
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


def render_contact_information() -> None:
    """Show Solomon Shipping contact details."""

    st.subheader(
        "Solomon Shipping and Trading Inc."
    )

    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.markdown(
                "### 📍 Office Address"
            )
            st.write(
                COMPANY_ADDRESS_LINE_1
            )
            st.write(
                COMPANY_ADDRESS_LINE_2
            )

    with right:
        with st.container(border=True):
            st.markdown(
                "### ☎️ Phone"
            )
            st.write(
                COMPANY_PHONE
            )


def render_support_ticket(
    record: dict[str, Any],
    download_key: str,
) -> None:
    """Show a ticket on screen and provide its permanent PDF."""

    ticket_id = safe_text(
        record.get("support_request_id")
    )

    st.markdown(
        "### Support Ticket"
    )

    ticket_columns = st.columns(3)

    ticket_values = [
        (
            "Support Ticket ID",
            ticket_id,
        ),
        (
            "Shipment ID",
            safe_text(
                record.get("shipment_id"),
                "Not provided",
            ),
        ),
        (
            "Status",
            safe_text(
                record.get("request_status")
            ),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        ticket_columns,
        ticket_values,
    ):
        with column:
            with st.container(border=True):
                st.markdown(
                    f"#### {label}"
                )
                st.write(value)

    summary_record = {
        "support_request_id": ticket_id,
        "shipment_id": safe_text(
            record.get("shipment_id"),
            "Not provided",
        ),
        "customer_name": safe_text(
            record.get("customer_name")
        ),
        "phone": safe_text(
            record.get("phone")
        ),
        "email": safe_text(
            record.get("email"),
            "Not provided",
        ),
        "support_topic": safe_text(
            record.get("support_topic")
        ),
        "request_status": safe_text(
            record.get("request_status")
        ),
        "priority": safe_text(
            record.get("priority")
        ),
        "submitted_at": format_datetime(
            record.get("created_at")
        ),
    }

    st.markdown(
        "### Request Summary"
    )

    st.dataframe(
        pd.DataFrame(
            [summary_record]
        ),
        use_container_width=True,
    )

    with st.container(border=True):
        st.markdown(
            "#### Customer Message"
        )
        st.write(
            safe_text(
                record.get("message")
            )
        )

    ticket_pdf = build_support_ticket_pdf(
        record
    )

    st.download_button(
        label=(
            "Download Support Ticket "
            "Confirmation PDF"
        ),
        data=ticket_pdf,
        file_name=(
            f"{ticket_id}_Support_Ticket.pdf"
        ),
        mime="application/pdf",
        use_container_width=True,
        key=download_key,
    )

    st.info(
        "Keep the Support Ticket ID for follow-up. "
        "The PDF can also be retrieved later using "
        "the ticket ID and phone number."
    )


def render_ticket_retrieval(
    engine: Engine,
) -> None:
    """Allow the customer to retrieve a previously submitted ticket."""

    st.subheader(
        "Retrieve an Existing Support Ticket"
    )

    st.caption(
        "Enter the exact Support Ticket ID and the phone "
        "number used when the request was submitted."
    )

    with st.form(
        "retrieve_support_ticket_form"
    ):
        left, right = st.columns(2)

        with left:
            ticket_id = st.text_input(
                "Support Ticket ID",
                placeholder="Example: SUP-2026-0001",
            )

        with right:
            ticket_phone = st.text_input(
                "Phone Number Used on Request"
            )

        retrieve_submitted = (
            st.form_submit_button(
                "Retrieve Support Ticket",
                use_container_width=True,
            )
        )

    if not retrieve_submitted:
        return

    if not ticket_id.strip():
        st.error(
            "Enter the Support Ticket ID."
        )
        return

    if not ticket_phone.strip():
        st.error(
            "Enter the phone number used "
            "on the support request."
        )
        return

    try:
        record = find_support_ticket(
            engine,
            ticket_id,
            ticket_phone,
        )
    except Exception as exc:
        st.error(
            "The support ticket lookup could "
            "not be completed."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    if record is None:
        st.error(
            "No support ticket matched that "
            "ticket ID and phone number."
        )
        return

    st.success(
        "Support ticket found."
    )

    render_support_ticket(
        record,
        download_key=(
            "download_retrieved_support_ticket"
        ),
    )


def render_common_topics() -> None:
    """Show common support categories."""

    st.subheader(
        "Common Support Topics"
    )

    first, second, third = st.columns(3)

    with first:
        with st.container(border=True):
            st.markdown(
                "### 📦 Shipment Updates"
            )
            st.write(
                "Ask about shipment movement, "
                "delivery status, or estimated arrival."
            )

    with second:
        with st.container(border=True):
            st.markdown(
                "### 🚚 Pickup Questions"
            )
            st.write(
                "Request help with pickup dates, "
                "pickup windows, or address updates."
            )

    with third:
        with st.container(border=True):
            st.markdown(
                "### 💳 Payment Support"
            )
            st.write(
                "Ask about invoices, balances, "
                "payment confirmation, or receipts."
            )


def render_footer() -> None:
    """Render the Niota Labs development footer."""

    st.markdown(
        """
        <div style="
            text-align:right;
            color:#0B6E4F;
            font-weight:700;
            margin-top:2rem;
            padding-bottom:1rem;
        ">
            Developed by Niota Labs LLC
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """Customer-facing support request page backed by Neon."""

    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Contact Support",
        subtitle=(
            "Need help with a shipment, pickup, "
            "payment, or delivery? Send a support "
            "request and download a permanent "
            "support-ticket confirmation."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Customer Support</span>
        <span class="badge-dark">Permanent Ticket PDF</span>
        <span class="badge-red">Shipment Assistance</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    render_contact_information()

    st.divider()

    try:
        engine = get_database_engine()
        verify_required_tables(engine)
    except Exception as exc:
        st.error(
            "The support form could not connect "
            "to the Solomon Shipping support records."
        )
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )
        render_common_topics()
        render_footer()
        return

    st.subheader(
        "Support Request Form"
    )

    with st.form(
        "support_request_form",
        clear_on_submit=False,
    ):
        left, right = st.columns(2)

        with left:
            customer_name = st.text_input(
                "Full Name"
            )

            phone = st.text_input(
                "Phone Number"
            )

            email = st.text_input(
                "Email Address"
            )

        with right:
            shipment_id = st.text_input(
                "Shipment ID, if available",
                placeholder="Example: SST-2026-0026",
            )

            support_topic = st.selectbox(
                "Support Topic",
                SUPPORT_TOPICS,
            )

        message = st.text_area(
            "How can we help?",
            placeholder=(
                "Write your message here..."
            ),
            height=140,
        )

        submitted = st.form_submit_button(
            "Submit Support Request",
            use_container_width=True,
        )

    if submitted:
        if not customer_name.strip():
            st.error(
                "Enter your full name."
            )

        elif not phone.strip():
            st.error(
                "Enter your phone number."
            )

        elif not message.strip():
            st.error(
                "Enter a message describing "
                "how Solomon Shipping can help."
            )

        elif not is_valid_email(email):
            st.error(
                "Enter a valid email address "
                "or leave the email field blank."
            )

        else:
            try:
                with st.spinner(
                    "Saving your support request..."
                ):
                    support_record = (
                        save_support_request(
                            engine=engine,
                            customer_name=(
                                customer_name
                            ),
                            phone=phone,
                            email=email,
                            shipment_id=(
                                shipment_id
                            ),
                            support_topic=(
                                support_topic
                            ),
                            message=message,
                        )
                    )

                st.success(
                    "Your support request "
                    "has been received."
                )

                render_support_ticket(
                    support_record,
                    download_key=(
                        "download_new_support_ticket"
                    ),
                )

            except ValueError as exc:
                st.error(str(exc))

            except Exception as exc:
                st.error(
                    "The support request could "
                    "not be saved to Neon."
                )

                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error_message(exc)}"
                )

    st.divider()

    render_ticket_retrieval(
        engine
    )

    st.divider()

    render_common_topics()
    render_footer()


if __name__ == "__main__":
    main()