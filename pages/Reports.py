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
    page_title="Reports",
    page_icon="📄",
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
            "application_name": "solomon_shipping_reports",
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


def make_count_report(
    dataframe: pd.DataFrame,
    group_column: str,
    label: str,
) -> pd.DataFrame:
    if (
        dataframe.empty
        or group_column not in dataframe.columns
    ):
        return pd.DataFrame()

    return (
        dataframe.groupby(
            group_column,
            dropna=False,
        )
        .size()
        .reset_index(name="count")
        .rename(
            columns={
                group_column: label
            }
        )
        .sort_values(
            "count",
            ascending=False,
        )
    )


def make_payment_terms_report(
    branch_payments: pd.DataFrame,
) -> pd.DataFrame:
    if branch_payments.empty:
        return pd.DataFrame()

    return (
        branch_payments.groupby(
            "payment_terms",
            dropna=False,
        )
        .agg(
            shipments=("shipment_id", "count"),
            amount_charged=("amount_charged", "sum"),
            amount_paid_nj=("amount_paid_nj", "sum"),
            amount_paid_guyana=(
                "amount_paid_guyana",
                "sum",
            ),
            total_amount_paid=(
                "total_amount_paid",
                "sum",
            ),
            balance_due=("balance_due", "sum"),
        )
        .reset_index()
        .sort_values(
            "balance_due",
            ascending=False,
        )
    )


def make_release_report(
    branch_payments: pd.DataFrame,
) -> pd.DataFrame:
    if branch_payments.empty:
        return pd.DataFrame()

    return (
        branch_payments.groupby(
            "release_status",
            dropna=False,
        )
        .agg(
            shipments=("shipment_id", "count"),
            amount_charged=("amount_charged", "sum"),
            total_amount_paid=(
                "total_amount_paid",
                "sum",
            ),
            balance_due=("balance_due", "sum"),
        )
        .reset_index()
        .sort_values(
            "balance_due",
            ascending=False,
        )
    )


def make_collection_location_report(
    branch_payments: pd.DataFrame,
) -> pd.DataFrame:
    if branch_payments.empty:
        return pd.DataFrame()

    return (
        branch_payments.groupby(
            "payment_collected_at",
            dropna=False,
        )
        .agg(
            shipments=("shipment_id", "count"),
            amount_charged=("amount_charged", "sum"),
            amount_paid_nj=("amount_paid_nj", "sum"),
            amount_paid_guyana=(
                "amount_paid_guyana",
                "sum",
            ),
            total_amount_paid=(
                "total_amount_paid",
                "sum",
            ),
            balance_due=("balance_due", "sum"),
        )
        .reset_index()
        .sort_values(
            "total_amount_paid",
            ascending=False,
        )
    )


def make_capacity_report(
    pickup_capacity: pd.DataFrame,
) -> pd.DataFrame:
    if pickup_capacity.empty:
        return pd.DataFrame()

    return (
        pickup_capacity.groupby(
            "pickup_area",
            dropna=False,
        )
        .agg(
            route_days=("capacity_id", "count"),
            driver_count=("driver_count", "sum"),
            max_pickups=("max_pickups", "sum"),
            scheduled_pickups=(
                "scheduled_pickups",
                "sum",
            ),
            available_slots=(
                "available_slots",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            "available_slots",
            ascending=True,
        )
    )


def make_pending_change_report(
    change_history: pd.DataFrame,
) -> pd.DataFrame:
    if change_history.empty:
        return pd.DataFrame()

    report = change_history.copy()

    if "approval_status" in report.columns:
        report = report[
            report["approval_status"]
            .astype(str)
            .str.lower()
            .eq("pending")
        ]

    display_columns = [
        "change_id",
        "shipment_id",
        "customer_name",
        "change_date",
        "change_type",
        "old_value",
        "new_value",
        "requested_by",
        "requested_role",
        "request_reason",
        "approval_status",
        "notes",
    ]

    available_columns = [
        column
        for column in display_columns
        if column in report.columns
    ]

    if available_columns:
        report = report[available_columns]

    if "change_date" in report.columns:
        report = report.sort_values(
            "change_date",
            ascending=False,
        )

    return report


def download_report_button(
    dataframe: pd.DataFrame,
    file_name: str,
    label: str,
) -> None:
    if dataframe.empty:
        return

    st.download_button(
        label=label,
        data=dataframe.to_csv(
            index=False
        ).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
        use_container_width=True,
    )


def render_owner_kpis(
    shipments: pd.DataFrame,
    branch_payments: pd.DataFrame,
    pickup_capacity: pd.DataFrame,
    change_history: pd.DataFrame,
) -> None:
    total_shipments = len(shipments)

    total_charged = safe_sum(
        branch_payments,
        "amount_charged",
    )

    paid_nj = safe_sum(
        branch_payments,
        "amount_paid_nj",
    )

    paid_guyana = safe_sum(
        branch_payments,
        "amount_paid_guyana",
    )

    balance_due = safe_sum(
        branch_payments,
        "balance_due",
    )

    available_slots = safe_sum(
        pickup_capacity,
        "available_slots",
    )

    pending_changes = 0

    if (
        not change_history.empty
        and "approval_status"
        in change_history.columns
    ):
        pending_changes = int(
            change_history[
                "approval_status"
            ]
            .astype(str)
            .str.lower()
            .eq("pending")
            .sum()
        )

    first_row = st.columns(4)

    first_metrics = [
        ("Total Shipments", total_shipments),
        (
            "Total Charged",
            format_currency(
                total_charged
            ),
        ),
        (
            "Balance Due",
            format_currency(
                balance_due
            ),
        ),
        (
            "Pending Changes",
            pending_changes,
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        first_row,
        first_metrics,
    ):
        with column:
            st.metric(label, value)

    second_row = st.columns(3)

    second_metrics = [
        (
            "Paid in New Jersey",
            format_currency(paid_nj),
        ),
        (
            "Paid in Guyana",
            format_currency(paid_guyana),
        ),
        (
            "Available Pickup Slots",
            int(available_slots),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        second_row,
        second_metrics,
    ):
        with column:
            st.metric(label, value)


def render_financial_reports(
    branch_payments: pd.DataFrame,
) -> None:
    st.subheader("Financial Reports")

    if branch_payments.empty:
        st.warning(
            "No branch-payment records "
            "are stored in Neon."
        )
        return

    payment_terms_report = (
        make_payment_terms_report(
            branch_payments
        )
    )

    release_report = (
        make_release_report(
            branch_payments
        )
    )

    location_report = (
        make_collection_location_report(
            branch_payments
        )
    )

    tabs = st.tabs(
        [
            "Payment Terms",
            "Release Status",
            "Collection Location",
            "Outstanding Balances",
        ]
    )

    with tabs[0]:
        st.markdown(
            "### Payment Terms Summary"
        )

        st.dataframe(
            payment_terms_report,
            use_container_width=True,
        )

        download_report_button(
            payment_terms_report,
            "payment_terms_report.csv",
            "Download Payment Terms Report",
        )

    with tabs[1]:
        st.markdown(
            "### Release Status Summary"
        )

        st.dataframe(
            release_report,
            use_container_width=True,
        )

        download_report_button(
            release_report,
            "release_status_report.csv",
            "Download Release Status Report",
        )

    with tabs[2]:
        st.markdown(
            "### Collection Location Summary"
        )

        st.dataframe(
            location_report,
            use_container_width=True,
        )

        download_report_button(
            location_report,
            "collection_location_report.csv",
            (
                "Download Collection "
                "Location Report"
            ),
        )

    with tabs[3]:
        st.markdown(
            "### Outstanding Balance / Hold Queue"
        )

        balance_frame = (
            branch_payments.copy()
        )

        balance_frame = balance_frame[
            pd.to_numeric(
                balance_frame["balance_due"],
                errors="coerce",
            )
            .fillna(0)
            .gt(0)
        ]

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

        available_columns = [
            column
            for column in display_columns
            if column in balance_frame.columns
        ]

        if balance_frame.empty:
            st.success(
                "No outstanding branch-payment "
                "balances were found."
            )
        else:
            report = balance_frame[
                available_columns
            ]

            st.dataframe(
                report,
                use_container_width=True,
            )

            download_report_button(
                report,
                "outstanding_balances_report.csv",
                (
                    "Download Outstanding "
                    "Balances Report"
                ),
            )


def render_operations_reports(
    shipments: pd.DataFrame,
    pickups: pd.DataFrame,
    pickup_capacity: pd.DataFrame,
    drivers: pd.DataFrame,
) -> None:
    st.subheader("Operations Reports")

    tabs = st.tabs(
        [
            "Shipment Status",
            "Pickup Status",
            "Pickup Capacity",
            "Driver Directory",
        ]
    )

    with tabs[0]:
        shipment_report = (
            make_count_report(
                shipments,
                "current_status",
                "shipment_status",
            )
        )

        if shipment_report.empty:
            st.info(
                "No shipment-status "
                "records are available."
            )
        else:
            st.dataframe(
                shipment_report,
                use_container_width=True,
            )

            download_report_button(
                shipment_report,
                "shipment_status_report.csv",
                (
                    "Download Shipment "
                    "Status Report"
                ),
            )

    with tabs[1]:
        pickup_report = (
            make_count_report(
                pickups,
                "pickup_status",
                "pickup_status",
            )
        )

        if pickup_report.empty:
            st.info(
                "No pickup-status records "
                "are available."
            )
        else:
            st.dataframe(
                pickup_report,
                use_container_width=True,
            )

            download_report_button(
                pickup_report,
                "pickup_status_report.csv",
                (
                    "Download Pickup "
                    "Status Report"
                ),
            )

    with tabs[2]:
        capacity_report = (
            make_capacity_report(
                pickup_capacity
            )
        )

        if capacity_report.empty:
            st.info(
                "No pickup-capacity records "
                "are available."
            )
        else:
            st.dataframe(
                capacity_report,
                use_container_width=True,
            )

            download_report_button(
                capacity_report,
                "pickup_capacity_report.csv",
                (
                    "Download Pickup "
                    "Capacity Report"
                ),
            )

    with tabs[3]:
        if drivers.empty:
            st.info(
                "No driver records "
                "are available."
            )
        else:
            display_columns = [
                "driver_id",
                "driver_name",
                "phone",
                "home_base",
                "service_areas",
                "primary_area",
                "max_pickups_per_day",
                "vehicle_type",
                "vehicle_plate",
                "active_status",
                "notes",
            ]

            available_columns = [
                column
                for column in display_columns
                if column in drivers.columns
            ]

            report = drivers[
                available_columns
            ]

            st.dataframe(
                report,
                use_container_width=True,
            )

            download_report_button(
                report,
                "driver_directory_report.csv",
                "Download Driver Directory",
            )


def render_change_history_reports(
    change_history: pd.DataFrame,
) -> None:
    st.subheader(
        "Change History Reports"
    )

    if change_history.empty:
        st.info(
            "No shipment-change history "
            "records are available."
        )
        return

    pending_report = (
        make_pending_change_report(
            change_history
        )
    )

    change_type_report = (
        make_count_report(
            change_history,
            "change_type",
            "change_type",
        )
    )

    approval_status_report = (
        make_count_report(
            change_history,
            "approval_status",
            "approval_status",
        )
    )

    tabs = st.tabs(
        [
            "Pending Requests",
            "Change Types",
            "Approval Status",
            "Full Change History",
        ]
    )

    with tabs[0]:
        if pending_report.empty:
            st.success(
                "No pending customer "
                "change requests."
            )
        else:
            st.dataframe(
                pending_report,
                use_container_width=True,
            )

            download_report_button(
                pending_report,
                (
                    "pending_change_"
                    "requests_report.csv"
                ),
                (
                    "Download Pending "
                    "Requests Report"
                ),
            )

    with tabs[1]:
        if change_type_report.empty:
            st.info(
                "No change-type records "
                "are available."
            )
        else:
            st.dataframe(
                change_type_report,
                use_container_width=True,
            )

            download_report_button(
                change_type_report,
                "change_type_report.csv",
                (
                    "Download Change "
                    "Type Report"
                ),
            )

    with tabs[2]:
        if approval_status_report.empty:
            st.info(
                "No approval-status records "
                "are available."
            )
        else:
            st.dataframe(
                approval_status_report,
                use_container_width=True,
            )

            download_report_button(
                approval_status_report,
                "approval_status_report.csv",
                (
                    "Download Approval "
                    "Status Report"
                ),
            )

    with tabs[3]:
        full_history = (
            change_history.copy()
        )

        if "change_date" in (
            full_history.columns
        ):
            full_history = (
                full_history.sort_values(
                    "change_date",
                    ascending=False,
                )
            )

        st.dataframe(
            full_history,
            use_container_width=True,
        )

        download_report_button(
            full_history,
            "full_change_history_report.csv",
            (
                "Download Full "
                "Change History"
            ),
        )


def main() -> None:
    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Reports",
        subtitle=(
            "Review live owner-level reports across "
            "New Jersey and Guyana payments, freight "
            "collect balances, pickup capacity, drivers, "
            "shipment activity, and customer changes."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner Reports</span>
        <span class="badge-dark">Live Neon Data</span>
        <span class="badge-red">Operations + Finance</span>
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
            "The Reports page could not "
            "load the Solomon Shipping "
            "records from Neon."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    render_owner_kpis(
        shipments=shipments,
        branch_payments=branch_payments,
        pickup_capacity=pickup_capacity,
        change_history=change_history,
    )

    st.divider()

    report_tabs = st.tabs(
        [
            "Financial Reports",
            "Operations Reports",
            "Change History",
            "Raw Data Export",
        ]
    )

    with report_tabs[0]:
        render_financial_reports(
            branch_payments
        )

    with report_tabs[1]:
        render_operations_reports(
            shipments=shipments,
            pickups=pickups,
            pickup_capacity=pickup_capacity,
            drivers=drivers,
        )

    with report_tabs[2]:
        render_change_history_reports(
            change_history
        )

    with report_tabs[3]:
        st.subheader(
            "Raw Data Export"
        )

        raw_tabs = st.tabs(
            [
                "Shipments",
                "Pickups",
                "Branch Payments",
                "Pickup Capacity",
                "Drivers",
                "Change History",
            ]
        )

        raw_data = [
            (
                raw_tabs[0],
                shipments,
                "shipments_export.csv",
                "Download Shipments",
            ),
            (
                raw_tabs[1],
                pickups,
                "pickups_export.csv",
                "Download Pickups",
            ),
            (
                raw_tabs[2],
                branch_payments,
                "branch_payments_export.csv",
                (
                    "Download Branch Payments"
                ),
            ),
            (
                raw_tabs[3],
                pickup_capacity,
                "pickup_capacity_export.csv",
                (
                    "Download Pickup Capacity"
                ),
            ),
            (
                raw_tabs[4],
                drivers,
                "drivers_export.csv",
                "Download Drivers",
            ),
            (
                raw_tabs[5],
                change_history,
                "change_history_export.csv",
                (
                    "Download Change History"
                ),
            ),
        ]

        for (
            tab,
            dataframe,
            file_name,
            label,
        ) in raw_data:
            with tab:
                if dataframe.empty:
                    st.info(
                        "No records are available."
                    )
                else:
                    st.dataframe(
                        dataframe,
                        use_container_width=True,
                    )

                    download_report_button(
                        dataframe,
                        file_name,
                        label,
                    )


if __name__ == "__main__":
    main()