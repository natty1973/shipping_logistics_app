from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from src.styles import (
    apply_custom_styles,
    hero,
    sidebar_shipping_options,
)


st.set_page_config(
    page_title="Shipment Status",
    page_icon="📦",
    layout="wide",
)

SCHEMA = "solomon_shipping"

STATUS_ORDER = [
    "Request Received",
    "Pickup Scheduled",
    "Picked Up",
    "Warehouse Received",
    "Booking Confirmed",
    "Container Loaded",
    "Departed",
    "Customs Clearance",
    "Arrived",
    "Ready for Pickup",
    "Delivered",
]

STATUS_ALIASES = {
    "at warehouse": "Warehouse Received",
    "in transit": "Departed",
    "arrived at destination": "Arrived",
    "out for delivery": "Ready for Pickup",
    "completed": "Delivered",
}


def secret(
    name: str,
) -> str:
    value = os.getenv(
        name,
        "",
    ).strip()

    if value:
        return value

    try:
        return str(
            st.secrets.get(
                name,
                "",
            )
        ).strip()

    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        return ""


@st.cache_resource(
    show_spinner=False
)
def db_engine() -> Engine:
    database_url = secret(
        "DATABASE_URL"
    )

    if database_url:
        if database_url.startswith(
            "postgres://"
        ):
            database_url = (
                "postgresql://"
                + database_url[
                    len("postgres://"):
                ]
            )

        target: str | URL = (
            database_url
        )

    else:
        values = {
            "user": secret("DB_USER"),
            "password": secret(
                "DB_PASSWORD"
            ),
            "host": secret("DB_HOST"),
            "port": (
                secret("DB_PORT")
                or "5432"
            ),
            "database": secret(
                "DB_NAME"
            ),
            "sslmode": (
                secret("DB_SSLMODE")
                or "require"
            ),
        }

        missing = [
            name
            for key, name in {
                "user": "DB_USER",
                "password": "DB_PASSWORD",
                "host": "DB_HOST",
                "database": "DB_NAME",
            }.items()
            if not values[key]
        ]

        if missing:
            raise RuntimeError(
                "Missing Streamlit Secrets: "
                + ", ".join(missing)
            )

        try:
            port = int(
                values["port"]
            )
        except ValueError:
            port = 5432

        target = URL.create(
            "postgresql+psycopg2",
            username=values["user"],
            password=values["password"],
            host=values["host"],
            port=port,
            database=values["database"],
            query={
                "sslmode": (
                    values["sslmode"]
                )
            },
        )

    engine = create_engine(
        target,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 15,
            "application_name": (
                "solomon_shipping_status"
            ),
        },
    )

    with engine.connect() as connection:
        connection.execute(
            text("SELECT 1")
        )

    return engine


def safe_error(
    error: Exception,
) -> str:
    message = str(error)

    message = re.sub(
        r"postgres(?:ql)?"
        r"(?:\+\w+)?://[^@\s]+@",
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


def clean(
    value: Any,
    default: str = "Not Available",
) -> str:
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default

    except (
        TypeError,
        ValueError,
    ):
        pass

    value = str(value).strip()

    return value or default


def money(
    value: Any,
    currency: str = "USD",
) -> str:
    try:
        amount = float(
            value or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        amount = 0.0

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


def staff_search() -> bool:
    portal_mode = str(
        st.session_state.get(
            "portal_mode",
            "customer",
        )
    ).lower()

    return portal_mode in {
        "staff",
        "admin",
        "owner",
    }


def verify_tables(
    engine: Engine,
) -> None:
    required = [
        "shipments",
        "status_history",
        "shipment_change_history",
        "branch_payments",
    ]

    with engine.connect() as connection:
        missing = [
            f"{SCHEMA}.{table_name}"
            for table_name in required
            if connection.execute(
                text(
                    "SELECT TO_REGCLASS(:name)"
                ),
                {
                    "name": (
                        f"{SCHEMA}.{table_name}"
                    )
                },
            ).scalar_one_or_none()
            is None
        ]

    if missing:
        raise RuntimeError(
            "Required Neon tables are missing: "
            + ", ".join(missing)
        )


def read_df(
    engine: Engine,
    query: str,
    params: dict[str, Any],
) -> pd.DataFrame:
    with engine.connect() as connection:
        return pd.read_sql_query(
            text(query),
            connection,
            params=params,
        )


def find_shipments(
    engine: Engine,
    lookup: str,
    broad: bool,
) -> pd.DataFrame:
    columns = """
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
        estimated_delivery_date,
        amount_charged,
        amount_paid,
        balance_due,
        payment_status,
        service_type,
        shipment_mode,
        booking_number,
        bill_of_lading_number,
        vessel_name,
        voyage_number,
        actual_departure_date,
        actual_arrival_date,
        release_status,
        notes
    """

    if broad:
        query = f"""
            SELECT
                {columns}
            FROM {SCHEMA}.shipments
            WHERE
                shipment_id
                    ILIKE :pattern
                OR customer_id
                    ILIKE :pattern
                OR customer_name
                    ILIKE :pattern
                OR destination_city
                    ILIKE :pattern
                OR destination_country
                    ILIKE :pattern
                OR COALESCE(
                    booking_number,
                    ''
                ) ILIKE :pattern
                OR COALESCE(
                    bill_of_lading_number,
                    ''
                ) ILIKE :pattern
            ORDER BY
                shipment_date DESC,
                shipment_id DESC
            LIMIT 50
        """

        params = {
            "pattern": (
                f"%{lookup.strip()}%"
            )
        }

    else:
        query = f"""
            SELECT
                {columns}
            FROM {SCHEMA}.shipments
            WHERE
                UPPER(
                    BTRIM(shipment_id)
                )
                =
                UPPER(
                    BTRIM(:shipment_id)
                )
            LIMIT 1
        """

        params = {
            "shipment_id": (
                lookup.strip()
            )
        }

    return read_df(
        engine,
        query,
        params,
    )


def branch_payment(
    engine: Engine,
    shipment_id: str,
) -> dict[str, Any] | None:
    frame = read_df(
        engine,
        f"""
        SELECT
            branch_payment_id,
            invoice_number,
            payment_terms,
            payment_responsibility,
            amount_charged,
            amount_paid_nj,
            amount_paid_guyana,
            total_amount_paid,
            balance_due,
            payment_status,
            release_status,
            payment_method,
            payment_date,
            currency,
            notes
        FROM {SCHEMA}.branch_payments
        WHERE
            UPPER(
                BTRIM(shipment_id)
            )
            =
            UPPER(
                BTRIM(:shipment_id)
            )
        ORDER BY
            payment_date DESC NULLS LAST,
            created_at DESC
        LIMIT 1
        """,
        {
            "shipment_id": shipment_id
        },
    )

    if frame.empty:
        return None

    return frame.iloc[0].to_dict()


def status_history(
    engine: Engine,
    shipment_id: str,
) -> pd.DataFrame:
    return read_df(
        engine,
        f"""
        SELECT
            status_id,
            status,
            status_date,
            updated_by,
            notes
        FROM {SCHEMA}.status_history
        WHERE
            UPPER(
                BTRIM(shipment_id)
            )
            =
            UPPER(
                BTRIM(:shipment_id)
            )
        ORDER BY
            status_date DESC
        """,
        {
            "shipment_id": shipment_id
        },
    )


def change_history(
    engine: Engine,
    shipment_id: str,
) -> pd.DataFrame:
    return read_df(
        engine,
        f"""
        SELECT
            change_id,
            change_date,
            change_type,
            old_value,
            new_value,
            request_reason,
            approval_status,
            approved_by,
            approved_date,
            notes
        FROM {SCHEMA}.shipment_change_history
        WHERE
            UPPER(
                BTRIM(shipment_id)
            )
            =
            UPPER(
                BTRIM(:shipment_id)
            )
        ORDER BY
            change_date DESC
        """,
        {
            "shipment_id": shipment_id
        },
    )


def milestones(
    engine: Engine,
    shipment_id: str,
) -> pd.DataFrame:
    with engine.connect() as connection:
        exists = connection.execute(
            text(
                """
                SELECT TO_REGCLASS(
                    'solomon_shipping.shipment_milestones'
                )
                """
            )
        ).scalar_one_or_none()

        if exists is None:
            return pd.DataFrame()

        return pd.read_sql_query(
            text(
                f"""
                SELECT
                    sm.milestone_code,
                    md.milestone_name,
                    md.display_order,
                    sm.milestone_status,
                    sm.scheduled_date,
                    sm.achieved_date,
                    sm.location,
                    sm.comments,
                    sm.updated_by
                FROM {SCHEMA}.shipment_milestones sm
                JOIN {SCHEMA}.milestone_definitions md
                    ON md.milestone_code =
                        sm.milestone_code
                WHERE
                    sm.shipment_id =
                        :shipment_id
                    AND md.customer_visible =
                        TRUE
                ORDER BY
                    md.display_order
                """
            ),
            connection,
            params={
                "shipment_id": shipment_id
            },
        )


def show_summary(
    record: dict[str, Any],
) -> None:
    values = [
        (
            "Shipment ID",
            clean(
                record.get(
                    "shipment_id"
                )
            ),
        ),
        (
            "Customer",
            clean(
                record.get(
                    "customer_name"
                )
            ),
        ),
        (
            "Current Status",
            clean(
                record.get(
                    "current_status"
                )
            ),
        ),
        (
            "Estimated Delivery",
            clean(
                record.get(
                    "estimated_delivery_date"
                ),
                "Pending confirmation",
            ),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        st.columns(4),
        values,
    ):
        with column:
            with st.container(
                border=True
            ):
                st.markdown(
                    f"#### {label}"
                )
                st.write(value)

    details = [
        (
            "Destination",
            (
                f"{clean(record.get('destination_city'))}, "
                f"{clean(record.get('destination_country'))}"
            ),
        ),
        (
            "Shipping Service",
            clean(
                record.get(
                    "service_type"
                ),
                "Pending selection",
            ),
        ),
        (
            "Shipment Mode",
            clean(
                record.get(
                    "shipment_mode"
                )
            ),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        st.columns(3),
        details,
    ):
        with column:
            with st.container(
                border=True
            ):
                st.markdown(
                    f"#### {label}"
                )
                st.write(value)


def show_timeline(
    current_status: str,
    milestone_frame: pd.DataFrame,
) -> None:
    st.subheader(
        "Shipment Progress"
    )

    normalized = STATUS_ALIASES.get(
        current_status.lower(),
        current_status,
    )

    achieved = set()

    if not milestone_frame.empty:
        achieved = set(
            milestone_frame[
                milestone_frame[
                    "milestone_status"
                ]
                .astype(str)
                .str.lower()
                .eq("achieved")
            ][
                "milestone_name"
            ].astype(str)
        )

    current_index = next(
        (
            index
            for index, status
            in enumerate(STATUS_ORDER)
            if status.lower()
            == normalized.lower()
        ),
        -1,
    )

    html = (
        "<div style='display:flex;"
        "flex-wrap:wrap;gap:.5rem;"
        "margin-top:.7rem'>"
    )

    for index, status in enumerate(
        STATUS_ORDER
    ):
        if (
            status.lower()
            == normalized.lower()
        ):
            background = "#FFF2B8"
            color = "#053B2D"
            border = "#F7D774"
            icon = "●"

        elif (
            status in achieved
            or (
                current_index >= 0
                and index < current_index
            )
        ):
            background = "#E6F4EF"
            color = "#0B6E4F"
            border = "#0B6E4F"
            icon = "✓"

        else:
            background = "#F3F4F6"
            color = "#6B7280"
            border = "#E5E7EB"
            icon = "○"

        html += (
            "<div style='"
            "padding:.7rem .9rem;"
            "border-radius:999px;"
            f"background:{background};"
            f"color:{color};"
            f"border:1px solid {border};"
            "font-weight:800;"
            "font-size:.86rem'>"
            f"{icon} {status}"
            "</div>"
        )

    st.markdown(
        html + "</div>",
        unsafe_allow_html=True,
    )


def show_payment(
    shipment: dict[str, Any],
    payment: dict[str, Any] | None,
) -> None:
    st.subheader(
        "Payment / Release Status"
    )

    if payment:
        currency = clean(
            payment.get("currency"),
            "USD",
        )

        charged = payment.get(
            "amount_charged",
            0,
        )

        paid = payment.get(
            "total_amount_paid",
            0,
        )

        balance = payment.get(
            "balance_due",
            0,
        )

        payment_status = clean(
            payment.get(
                "payment_status"
            )
        )

        release_status = clean(
            payment.get(
                "release_status"
            ),
            "Pending Review",
        )

        terms = clean(
            payment.get(
                "payment_terms"
            )
        )

    else:
        currency = "USD"

        charged = shipment.get(
            "amount_charged",
            0,
        )

        paid = shipment.get(
            "amount_paid",
            0,
        )

        balance = shipment.get(
            "balance_due",
            0,
        )

        payment_status = clean(
            shipment.get(
                "payment_status"
            ),
            "Unpaid",
        )

        release_status = clean(
            shipment.get(
                "release_status"
            ),
            "Pending Review",
        )

        terms = (
            "No branch-payment record "
            "has been entered yet."
        )

    values = [
        (
            "Amount Charged",
            money(
                charged,
                currency,
            ),
        ),
        (
            "Total Paid",
            money(
                paid,
                currency,
            ),
        ),
        (
            "Balance Due",
            money(
                balance,
                currency,
            ),
        ),
        (
            "Payment Status",
            payment_status,
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        st.columns(4),
        values,
    ):
        with column:
            st.metric(
                label,
                value,
            )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Release Status"
        )

        st.write(
            release_status
        )

        st.caption(
            terms
        )


def main() -> None:
    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Shipment Status",
        subtitle=(
            "Check the current shipment stage, "
            "payment and release status, milestones, "
            "and shipment history directly from Neon."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Shipment Lookup</span>
        <span class="badge-dark">Live Neon Status</span>
        <span class="badge-red">Payment Release Check</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = db_engine()
        verify_tables(engine)

    except Exception as exc:
        st.error(
            "The Shipment Status page could "
            "not load records from Neon."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error(exc)}"
        )

        return

    broad = staff_search()

    label = (
        "Enter Shipment ID, customer name, "
        "customer ID, destination, booking "
        "number, or bill of lading"
        if broad
        else "Enter Shipment ID"
    )

    lookup = st.text_input(
        label,
        placeholder=(
            "Example: SST-2026-0026"
        ),
    )

    if not lookup.strip():
        st.info(
            "Enter a Shipment ID to "
            "view the current status."
        )
        return

    try:
        matches = find_shipments(
            engine,
            lookup,
            broad,
        )

    except Exception as exc:
        st.error(
            "The shipment search could "
            "not be completed."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error(exc)}"
        )

        return

    if matches.empty:
        st.error(
            "No matching shipment was "
            "found in Neon."
        )
        return

    if broad and len(matches) > 1:
        st.dataframe(
            matches[
                [
                    "shipment_id",
                    "customer_name",
                    "shipment_date",
                    "destination_city",
                    "destination_country",
                    "current_status",
                ]
            ],
            use_container_width=True,
        )

        selected_id = st.selectbox(
            "Select Shipment ID",
            matches["shipment_id"]
            .astype(str)
            .tolist(),
        )

        record = matches[
            matches["shipment_id"]
            .astype(str)
            .eq(selected_id)
        ].iloc[0].to_dict()

    else:
        record = (
            matches.iloc[0].to_dict()
        )

    shipment_id = clean(
        record.get("shipment_id"),
        lookup.strip(),
    )

    try:
        payment = branch_payment(
            engine,
            shipment_id,
        )

        statuses = status_history(
            engine,
            shipment_id,
        )

        changes = change_history(
            engine,
            shipment_id,
        )

        milestone_frame = milestones(
            engine,
            shipment_id,
        )

    except Exception as exc:
        st.error(
            "The shipment was found, but "
            "its history could not be loaded."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error(exc)}"
        )

        return

    st.divider()

    show_summary(record)

    st.divider()

    show_timeline(
        clean(
            record.get(
                "current_status"
            ),
            "Request Received",
        ),
        milestone_frame,
    )

    st.divider()

    show_payment(
        record,
        payment,
    )

    st.divider()

    st.subheader(
        "Shipment History"
    )

    tabs = st.tabs(
        [
            "Status Updates",
            "Change Requests",
            "Milestones",
        ]
    )

    with tabs[0]:
        if statuses.empty:
            st.info(
                "No status-history records "
                "have been entered yet."
            )
        else:
            st.dataframe(
                statuses,
                use_container_width=True,
            )

    with tabs[1]:
        if changes.empty:
            st.info(
                "No shipment-change requests "
                "have been entered yet."
            )
        else:
            st.dataframe(
                changes,
                use_container_width=True,
            )

    with tabs[2]:
        if milestone_frame.empty:
            st.info(
                "No milestone records "
                "are available."
            )
        else:
            st.dataframe(
                milestone_frame,
                use_container_width=True,
            )


if __name__ == "__main__":
    main()