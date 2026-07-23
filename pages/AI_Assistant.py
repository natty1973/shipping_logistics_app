from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(
    page_title="AI Assistant",
    page_icon="🤖",
    layout="wide",
)

SCHEMA = "solomon_shipping"

REQUIRED_TABLES = [
    "shipments",
    "pickup_schedule",
    "branch_payments",
    "pickup_capacity",
    "drivers",
    "shipment_change_history",
]


def get_secret(name: str) -> str:
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
            "application_name": "solomon_shipping_ai_assistant",
        },
    )

    with engine.connect() as connection:
        connection.execute(text("SELECT 1;"))

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


def verify_required_tables(engine: Engine) -> None:
    missing: list[str] = []

    with engine.connect() as connection:
        for table_name in REQUIRED_TABLES:
            relation_name = f"{SCHEMA}.{table_name}"

            exists = connection.execute(
                text("SELECT TO_REGCLASS(:relation_name);"),
                {"relation_name": relation_name},
            ).scalar_one_or_none()

            if exists is None:
                missing.append(relation_name)

    if missing:
        raise RuntimeError(
            "Required Neon tables are missing: "
            + ", ".join(missing)
        )


def load_table(
    engine: Engine,
    table_name: str,
) -> pd.DataFrame:
    with engine.connect() as connection:
        return pd.read_sql_query(
            text(
                f"""
                SELECT *
                FROM {SCHEMA}.{table_name};
                """
            ),
            connection,
        )


def format_currency(
    value: Any,
    currency: str = "USD",
) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
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


def safe_sum(
    dataframe: pd.DataFrame,
    column: str,
) -> float:
    if (
        dataframe.empty
        or column not in dataframe.columns
    ):
        return 0.0

    return float(
        pd.to_numeric(
            dataframe[column],
            errors="coerce",
        )
        .fillna(0)
        .sum()
    )


def display_table_if_available(
    dataframe: pd.DataFrame,
    title: str,
) -> None:
    if dataframe.empty:
        st.info(
            f"No records found for: {title}"
        )
        return

    st.markdown(
        f"### {title}"
    )

    st.dataframe(
        dataframe,
        use_container_width=True,
    )


def find_shipment_id(
    question: str,
) -> str | None:
    match = re.search(
        r"\bSST-\d{4}-\d{4,}\b",
        question,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(0).upper()


def answer_specific_shipment_question(
    question: str,
    shipments: pd.DataFrame,
    pickups: pd.DataFrame,
    branch_payments: pd.DataFrame,
    change_history: pd.DataFrame,
) -> bool:
    shipment_id = find_shipment_id(
        question
    )

    if not shipment_id:
        return False

    shipment = shipments[
        shipments["shipment_id"]
        .astype(str)
        .str.upper()
        .eq(shipment_id)
    ]

    if shipment.empty:
        st.error(
            f"No shipment was found for {shipment_id}."
        )
        return True

    record = shipment.iloc[0]

    st.success(
        f"Shipment {shipment_id} was found."
    )

    summary_columns = st.columns(4)

    summary_values = [
        (
            "Customer",
            str(
                record.get(
                    "customer_name",
                    "Not Available",
                )
            ),
        ),
        (
            "Current Status",
            str(
                record.get(
                    "current_status",
                    "Not Available",
                )
            ),
        ),
        (
            "Destination",
            (
                f"{record.get('destination_city', '')}, "
                f"{record.get('destination_country', '')}"
            ),
        ),
        (
            "Payment Status",
            str(
                record.get(
                    "payment_status",
                    "Not Available",
                )
            ),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        summary_columns,
        summary_values,
    ):
        with column:
            st.metric(
                label,
                value,
            )

    shipment_pickups = (
        pickups[
            pickups["shipment_id"]
            .astype(str)
            .str.upper()
            .eq(shipment_id)
        ]
        if (
            not pickups.empty
            and "shipment_id"
            in pickups.columns
        )
        else pd.DataFrame()
    )

    shipment_payments = (
        branch_payments[
            branch_payments["shipment_id"]
            .astype(str)
            .str.upper()
            .eq(shipment_id)
        ]
        if (
            not branch_payments.empty
            and "shipment_id"
            in branch_payments.columns
        )
        else pd.DataFrame()
    )

    shipment_changes = (
        change_history[
            change_history["shipment_id"]
            .astype(str)
            .str.upper()
            .eq(shipment_id)
        ]
        if (
            not change_history.empty
            and "shipment_id"
            in change_history.columns
        )
        else pd.DataFrame()
    )

    detail_tabs = st.tabs(
        [
            "Shipment Record",
            "Pickup Record",
            "Payment Record",
            "Change History",
        ]
    )

    with detail_tabs[0]:
        st.dataframe(
            shipment,
            use_container_width=True,
        )

    with detail_tabs[1]:
        display_table_if_available(
            shipment_pickups,
            "Pickup Record",
        )

    with detail_tabs[2]:
        display_table_if_available(
            shipment_payments,
            "Payment Record",
        )

    with detail_tabs[3]:
        display_table_if_available(
            shipment_changes,
            "Change History",
        )

    return True


def answer_payment_question(
    question: str,
    branch_payments: pd.DataFrame,
) -> bool:
    q = question.lower()

    if branch_payments.empty:
        return False

    if (
        "new jersey" in q
        or re.search(r"\bnj\b", q)
    ):
        total = safe_sum(
            branch_payments,
            "amount_paid_nj",
        )

        st.success(
            "Total collected in New Jersey: "
            f"{format_currency(total)}"
        )

        records = branch_payments[
            pd.to_numeric(
                branch_payments[
                    "amount_paid_nj"
                ],
                errors="coerce",
            )
            .fillna(0)
            .gt(0)
        ]

        display_table_if_available(
            records,
            "Payments Collected in New Jersey",
        )

        return True

    if "guyana" in q:
        total = safe_sum(
            branch_payments,
            "amount_paid_guyana",
        )

        st.success(
            "Total collected in Guyana: "
            f"{format_currency(total)}"
        )

        records = branch_payments[
            pd.to_numeric(
                branch_payments[
                    "amount_paid_guyana"
                ],
                errors="coerce",
            )
            .fillna(0)
            .gt(0)
        ]

        display_table_if_available(
            records,
            "Payments Collected in Guyana",
        )

        return True

    if any(
        term in q
        for term in [
            "balance",
            "outstanding",
            "owed",
        ]
    ):
        balance = safe_sum(
            branch_payments,
            "balance_due",
        )

        st.warning(
            "Total outstanding balance: "
            f"{format_currency(balance)}"
        )

        records = branch_payments[
            pd.to_numeric(
                branch_payments[
                    "balance_due"
                ],
                errors="coerce",
            )
            .fillna(0)
            .gt(0)
        ]

        display_table_if_available(
            records,
            "Shipments with Outstanding Balances",
        )

        return True

    if (
        "freight collect" in q
        or "receiver paid" in q
    ):
        records = branch_payments[
            branch_payments[
                "payment_terms"
            ]
            .astype(str)
            .str.contains(
                "Receiver Paid|Freight Collect",
                case=False,
                na=False,
            )
        ]

        st.info(
            "Freight collect or receiver-paid "
            f"shipments found: {len(records)}"
        )

        display_table_if_available(
            records,
            (
                "Freight Collect / "
                "Receiver-Paid Shipments"
            ),
        )

        return True

    if any(
        term in q
        for term in [
            "hold",
            "release",
            "cleared",
        ]
    ):
        if "cleared" in q:
            records = branch_payments[
                branch_payments[
                    "release_status"
                ]
                .astype(str)
                .str.contains(
                    "Cleared",
                    case=False,
                    na=False,
                )
            ]

            st.success(
                "Shipments cleared for release: "
                f"{len(records)}"
            )

            title = "Cleared Shipments"

        else:
            records = branch_payments[
                branch_payments[
                    "release_status"
                ]
                .astype(str)
                .str.contains(
                    "Hold",
                    case=False,
                    na=False,
                )
            ]

            st.warning(
                "Shipments currently on payment hold: "
                f"{len(records)}"
            )

            title = "Shipments on Hold"

        display_table_if_available(
            records,
            title,
        )

        return True

    if any(
        term in q
        for term in [
            "paid",
            "payment",
            "money",
            "revenue",
        ]
    ):
        total_charged = safe_sum(
            branch_payments,
            "amount_charged",
        )

        total_paid = safe_sum(
            branch_payments,
            "total_amount_paid",
        )

        balance = safe_sum(
            branch_payments,
            "balance_due",
        )

        paid_nj = safe_sum(
            branch_payments,
            "amount_paid_nj",
        )

        paid_guyana = safe_sum(
            branch_payments,
            "amount_paid_guyana",
        )

        values = [
            (
                "Total Charged",
                format_currency(
                    total_charged
                ),
            ),
            (
                "Total Paid",
                format_currency(
                    total_paid
                ),
            ),
            (
                "Paid in NJ",
                format_currency(
                    paid_nj
                ),
            ),
            (
                "Paid in Guyana",
                format_currency(
                    paid_guyana
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
                st.metric(label, value)

        st.warning(
            "Outstanding balance: "
            f"{format_currency(balance)}"
        )

        return True

    return False


def answer_pickup_question(
    question: str,
    pickup_capacity: pd.DataFrame,
    drivers: pd.DataFrame,
    pickups: pd.DataFrame,
) -> bool:
    q = question.lower()

    if "driver" in q:
        st.info(
            "Total drivers in the system: "
            f"{len(drivers)}"
        )

        display_columns = [
            "driver_id",
            "driver_name",
            "phone",
            "service_areas",
            "primary_area",
            "max_pickups_per_day",
            "active_status",
        ]

        available_columns = [
            column
            for column in display_columns
            if column in drivers.columns
        ]

        display_table_if_available(
            drivers[available_columns],
            "Driver Directory",
        )

        return True

    if any(
        term in q
        for term in [
            "capacity",
            "available slot",
            "slots",
            "full",
            "limited",
        ]
    ):
        if pickup_capacity.empty:
            return False

        values = [
            (
                "Max Pickups",
                int(
                    safe_sum(
                        pickup_capacity,
                        "max_pickups",
                    )
                ),
            ),
            (
                "Scheduled Pickups",
                int(
                    safe_sum(
                        pickup_capacity,
                        "scheduled_pickups",
                    )
                ),
            ),
            (
                "Available Slots",
                int(
                    safe_sum(
                        pickup_capacity,
                        "available_slots",
                    )
                ),
            ),
        ]

        for column, (
            label,
            value,
        ) in zip(
            st.columns(3),
            values,
        ):
            with column:
                st.metric(label, value)

        if "full" in q:
            records = pickup_capacity[
                pickup_capacity[
                    "capacity_status"
                ]
                .astype(str)
                .str.contains(
                    "Full",
                    case=False,
                    na=False,
                )
            ]

            title = "Full Pickup Routes"

        elif "limited" in q:
            records = pickup_capacity[
                pickup_capacity[
                    "capacity_status"
                ]
                .astype(str)
                .str.contains(
                    "Limited",
                    case=False,
                    na=False,
                )
            ]

            title = "Limited Pickup Routes"

        else:
            records = pickup_capacity
            title = "Pickup Capacity Board"

        display_table_if_available(
            records,
            title,
        )

        return True

    if (
        "pickup" in q
        or "schedule" in q
    ):
        if pickups.empty:
            return False

        st.info(
            "Total pickup records: "
            f"{len(pickups)}"
        )

        display_table_if_available(
            pickups,
            "Pickup Schedule Records",
        )

        return True

    return False


def answer_change_question(
    question: str,
    change_history: pd.DataFrame,
) -> bool:
    q = question.lower()

    if change_history.empty:
        return False

    if any(
        term in q
        for term in [
            "pending",
            "change request",
            "reschedule",
            "cancel",
        ]
    ):
        records = change_history.copy()

        if (
            "approval_status"
            in records.columns
        ):
            records = records[
                records[
                    "approval_status"
                ]
                .astype(str)
                .str.lower()
                .eq("pending")
            ]

        if "change_date" in records.columns:
            records = records.sort_values(
                "change_date",
                ascending=False,
            )

        st.warning(
            "Pending customer change requests: "
            f"{len(records)}"
        )

        display_table_if_available(
            records,
            "Pending Change Requests",
        )

        return True

    if (
        "history" in q
        or "audit" in q
    ):
        records = change_history.copy()

        if "change_date" in records.columns:
            records = records.sort_values(
                "change_date",
                ascending=False,
            )

        display_table_if_available(
            records,
            "Full Shipment Change History",
        )

        return True

    return False


def answer_shipment_question(
    question: str,
    shipments: pd.DataFrame,
) -> bool:
    q = question.lower()

    if shipments.empty:
        return False

    if any(
        term in q
        for term in [
            "shipment",
            "status",
            "delivered",
            "transit",
            "request received",
        ]
    ):
        st.info(
            "Total shipment records: "
            f"{len(shipments)}"
        )

        summary = (
            shipments.groupby(
                "current_status",
                dropna=False,
            )
            .size()
            .reset_index(name="count")
            .sort_values(
                "count",
                ascending=False,
            )
        )

        st.markdown(
            "### Shipment Status Summary"
        )

        st.dataframe(
            summary,
            use_container_width=True,
        )

        display_table_if_available(
            shipments,
            "Shipment Records",
        )

        return True

    return False


def render_suggested_questions() -> None:
    st.markdown(
        "### Suggested Questions"
    )

    suggestions = [
        (
            "What is the status of "
            "SST-2026-0026?"
        ),
        (
            "How much money was collected "
            "in New Jersey?"
        ),
        (
            "How much money was collected "
            "in Guyana?"
        ),
        (
            "Which shipments are on hold "
            "because of payment?"
        ),
        (
            "Which freight collect shipments "
            "still have balances?"
        ),
        (
            "Which pickup routes are full?"
        ),
        (
            "How many pickup slots "
            "are available?"
        ),
        "Which drivers are active?",
        (
            "Which customer change requests "
            "are pending?"
        ),
        "Show shipment status summary.",
    ]

    for question in suggestions:
        st.caption(
            f"• {question}"
        )


def main() -> None:
    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="AI Assistant",
        subtitle=(
            "Ask owner-level questions about live Neon "
            "payments, held shipments, pickup capacity, "
            "drivers, customer changes, and shipment status."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner AI Assistant</span>
        <span class="badge-dark">Neon-Grounded Insights</span>
        <span class="badge-red">Rule-Based MVP</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = get_database_engine()

        verify_required_tables(
            engine
        )

        shipments = load_table(
            engine,
            "shipments",
        )

        pickups = load_table(
            engine,
            "pickup_schedule",
        )

        branch_payments = load_table(
            engine,
            "branch_payments",
        )

        pickup_capacity = load_table(
            engine,
            "pickup_capacity",
        )

        drivers = load_table(
            engine,
            "drivers",
        )

        change_history = load_table(
            engine,
            "shipment_change_history",
        )

    except Exception as exc:
        st.error(
            "The AI Assistant could not load "
            "the Solomon Shipping records "
            "from Neon."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    render_suggested_questions()

    st.divider()

    question = st.text_input(
        (
            "Ask a question about "
            "Solomon Shipping operations"
        ),
        placeholder=(
            "Example: What is the status "
            "of SST-2026-0026?"
        ),
    )

    if not question.strip():
        st.info(
            "Enter a question above or use "
            "one of the suggested questions."
        )
        return

    st.markdown(
        "## Assistant Answer"
    )

    handled = (
        answer_specific_shipment_question(
            question,
            shipments,
            pickups,
            branch_payments,
            change_history,
        )
        or answer_payment_question(
            question,
            branch_payments,
        )
        or answer_pickup_question(
            question,
            pickup_capacity,
            drivers,
            pickups,
        )
        or answer_change_question(
            question,
            change_history,
        )
        or answer_shipment_question(
            question,
            shipments,
        )
    )

    if not handled:
        st.warning(
            "I could not match that question to "
            "the current MVP rules. Ask about a "
            "Shipment ID, payments, New Jersey or "
            "Guyana collections, held shipments, "
            "drivers, pickup capacity, pending "
            "changes, or shipment status."
        )

    st.divider()

    with st.expander(
        "What this AI Assistant can answer"
    ):
        st.markdown(
            """
            This MVP assistant is rule-based and reads live
            data from Neon. It can answer questions about:

            - A specific Shipment ID
            - New Jersey and Guyana payments
            - Freight collect shipments
            - Outstanding balances and release holds
            - Pickup capacity and route availability
            - Drivers
            - Pending change requests
            - Shipment status summaries

            It does not yet call a paid language-model API.
            """
        )


if __name__ == "__main__":
    main()