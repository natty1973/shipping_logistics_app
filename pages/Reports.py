from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_loader import (
    load_branch_payments,
    load_drivers,
    load_pickup_capacity,
    load_pickups,
    load_shipment_change_history,
    load_shipments,
)
from src.styles import apply_custom_styles, hero, sidebar_shipping_options
from src.utils import format_currency


st.set_page_config(
    page_title="Reports",
    page_icon="📄",
    layout="wide",
)


def safe_sum(df: pd.DataFrame, column: str) -> float:
    """
    Safely sum a numeric column.
    """

    if df.empty or column not in df.columns:
        return 0.0

    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def safe_count(df: pd.DataFrame, column: str, contains_text: str | None = None) -> int:
    """
    Safely count rows or rows containing text in a column.
    """

    if df.empty:
        return 0

    if column not in df.columns:
        return len(df)

    if contains_text:
        return int(
            df[column]
            .astype(str)
            .str.contains(contains_text, case=False, na=False)
            .sum()
        )

    return int(df[column].notna().sum())


def make_count_report(df: pd.DataFrame, group_column: str, label: str) -> pd.DataFrame:
    """
    Create a simple count report by category.
    """

    if df.empty or group_column not in df.columns:
        return pd.DataFrame()

    report = (
        df.groupby(group_column, dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    report = report.rename(columns={group_column: label})

    return report


def make_payment_terms_report(branch_payments: pd.DataFrame) -> pd.DataFrame:
    """
    Create report by payment terms.
    """

    if branch_payments.empty or "payment_terms" not in branch_payments.columns:
        return pd.DataFrame()

    return (
        branch_payments.groupby("payment_terms", dropna=False)
        .agg(
            shipments=("shipment_id", "count"),
            amount_charged=("amount_charged", "sum"),
            amount_paid_nj=("amount_paid_nj", "sum"),
            amount_paid_guyana=("amount_paid_guyana", "sum"),
            total_amount_paid=("total_amount_paid", "sum"),
            balance_due=("balance_due", "sum"),
        )
        .reset_index()
        .sort_values("balance_due", ascending=False)
    )


def make_release_report(branch_payments: pd.DataFrame) -> pd.DataFrame:
    """
    Create report by release status.
    """

    if branch_payments.empty or "release_status" not in branch_payments.columns:
        return pd.DataFrame()

    return (
        branch_payments.groupby("release_status", dropna=False)
        .agg(
            shipments=("shipment_id", "count"),
            amount_charged=("amount_charged", "sum"),
            total_amount_paid=("total_amount_paid", "sum"),
            balance_due=("balance_due", "sum"),
        )
        .reset_index()
        .sort_values("balance_due", ascending=False)
    )


def make_collection_location_report(branch_payments: pd.DataFrame) -> pd.DataFrame:
    """
    Create report by payment collection location.
    """

    if branch_payments.empty or "payment_collected_at" not in branch_payments.columns:
        return pd.DataFrame()

    return (
        branch_payments.groupby("payment_collected_at", dropna=False)
        .agg(
            shipments=("shipment_id", "count"),
            amount_charged=("amount_charged", "sum"),
            amount_paid_nj=("amount_paid_nj", "sum"),
            amount_paid_guyana=("amount_paid_guyana", "sum"),
            total_amount_paid=("total_amount_paid", "sum"),
            balance_due=("balance_due", "sum"),
        )
        .reset_index()
        .sort_values("total_amount_paid", ascending=False)
    )


def make_capacity_report(pickup_capacity: pd.DataFrame) -> pd.DataFrame:
    """
    Create capacity report by pickup area.
    """

    if pickup_capacity.empty or "pickup_area" not in pickup_capacity.columns:
        return pd.DataFrame()

    return (
        pickup_capacity.groupby("pickup_area", dropna=False)
        .agg(
            route_days=("capacity_id", "count"),
            driver_count=("driver_count", "sum"),
            max_pickups=("max_pickups", "sum"),
            scheduled_pickups=("scheduled_pickups", "sum"),
            available_slots=("available_slots", "sum"),
        )
        .reset_index()
        .sort_values("available_slots", ascending=True)
    )


def make_pending_change_report(change_history: pd.DataFrame) -> pd.DataFrame:
    """
    Create pending customer change request report.
    """

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

    available_columns = [col for col in display_columns if col in report.columns]

    if available_columns:
        report = report[available_columns]

    if "change_date" in report.columns:
        report = report.sort_values("change_date", ascending=False)

    return report


def download_report_button(df: pd.DataFrame, file_name: str, label: str) -> None:
    """
    Render a download button for a dataframe.
    """

    if df.empty:
        return

    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label=label,
        data=csv,
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
    """
    Render owner-level report KPIs.
    """

    total_shipments = len(shipments)
    total_charged = safe_sum(branch_payments, "amount_charged")
    paid_nj = safe_sum(branch_payments, "amount_paid_nj")
    paid_guyana = safe_sum(branch_payments, "amount_paid_guyana")
    balance_due = safe_sum(branch_payments, "balance_due")
    available_slots = safe_sum(pickup_capacity, "available_slots")

    pending_changes = 0
    if not change_history.empty and "approval_status" in change_history.columns:
        pending_changes = int(
            change_history["approval_status"]
            .astype(str)
            .str.lower()
            .eq("pending")
            .sum()
        )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Shipments", total_shipments)

    with col2:
        st.metric("Total Charged", format_currency(total_charged))

    with col3:
        st.metric("Balance Due", format_currency(balance_due))

    with col4:
        st.metric("Pending Changes", pending_changes)

    col5, col6, col7 = st.columns(3)

    with col5:
        st.metric("Paid in New Jersey", format_currency(paid_nj))

    with col6:
        st.metric("Paid in Guyana", format_currency(paid_guyana))

    with col7:
        st.metric("Available Pickup Slots", int(available_slots))


def render_financial_reports(branch_payments: pd.DataFrame) -> None:
    """
    Render owner financial reports.
    """

    st.subheader("Financial Reports")

    if branch_payments.empty:
        st.warning("No branch payment data found.")
        return

    payment_terms_report = make_payment_terms_report(branch_payments)
    release_report = make_release_report(branch_payments)
    location_report = make_collection_location_report(branch_payments)

    tabs = st.tabs(
        [
            "Payment Terms",
            "Release Status",
            "Collection Location",
            "Outstanding Balances",
        ]
    )

    with tabs[0]:
        st.markdown("### Payment Terms Summary")
        st.dataframe(payment_terms_report, use_container_width=True)
        download_report_button(
            payment_terms_report,
            "payment_terms_report.csv",
            "Download Payment Terms Report",
        )

    with tabs[1]:
        st.markdown("### Release Status Summary")
        st.dataframe(release_report, use_container_width=True)
        download_report_button(
            release_report,
            "release_status_report.csv",
            "Download Release Status Report",
        )

    with tabs[2]:
        st.markdown("### Collection Location Summary")
        st.dataframe(location_report, use_container_width=True)
        download_report_button(
            location_report,
            "collection_location_report.csv",
            "Download Collection Location Report",
        )

    with tabs[3]:
        st.markdown("### Outstanding Balance / Hold Queue")

        balance_df = branch_payments.copy()

        if "balance_due" in balance_df.columns:
            balance_df = balance_df[
                pd.to_numeric(balance_df["balance_due"], errors="coerce").fillna(0) > 0
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

        available_columns = [col for col in display_columns if col in balance_df.columns]

        if balance_df.empty:
            st.success("No outstanding branch payment balances found.")
        else:
            st.dataframe(balance_df[available_columns], use_container_width=True)
            download_report_button(
                balance_df[available_columns],
                "outstanding_balances_report.csv",
                "Download Outstanding Balances Report",
            )


def render_operations_reports(
    shipments: pd.DataFrame,
    pickups: pd.DataFrame,
    pickup_capacity: pd.DataFrame,
    drivers: pd.DataFrame,
) -> None:
    """
    Render operational reports.
    """

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
        st.markdown("### Shipment Status Summary")

        shipment_status_column = None

        for candidate in ["current_status", "shipment_status", "status"]:
            if candidate in shipments.columns:
                shipment_status_column = candidate
                break

        if shipment_status_column:
            shipment_report = make_count_report(
                shipments,
                shipment_status_column,
                "shipment_status",
            )
            st.dataframe(shipment_report, use_container_width=True)
            download_report_button(
                shipment_report,
                "shipment_status_report.csv",
                "Download Shipment Status Report",
            )
        else:
            st.info("No shipment status column found.")

    with tabs[1]:
        st.markdown("### Pickup Status Summary")

        pickup_status_column = None

        for candidate in ["pickup_status", "status"]:
            if candidate in pickups.columns:
                pickup_status_column = candidate
                break

        if pickup_status_column:
            pickup_report = make_count_report(
                pickups,
                pickup_status_column,
                "pickup_status",
            )
            st.dataframe(pickup_report, use_container_width=True)
            download_report_button(
                pickup_report,
                "pickup_status_report.csv",
                "Download Pickup Status Report",
            )
        else:
            st.info("No pickup status column found.")

    with tabs[2]:
        st.markdown("### Pickup Capacity by Area")

        capacity_report = make_capacity_report(pickup_capacity)

        if capacity_report.empty:
            st.info("No pickup capacity data found.")
        else:
            st.dataframe(capacity_report, use_container_width=True)
            download_report_button(
                capacity_report,
                "pickup_capacity_report.csv",
                "Download Pickup Capacity Report",
            )

    with tabs[3]:
        st.markdown("### Driver Directory")

        if drivers.empty:
            st.info("No driver data found.")
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

            available_columns = [col for col in display_columns if col in drivers.columns]

            st.dataframe(drivers[available_columns], use_container_width=True)
            download_report_button(
                drivers[available_columns],
                "driver_directory_report.csv",
                "Download Driver Directory",
            )


def render_change_history_reports(change_history: pd.DataFrame) -> None:
    """
    Render shipment change history and pending request reports.
    """

    st.subheader("Change History Reports")

    if change_history.empty:
        st.info("No shipment change history data found.")
        return

    pending_report = make_pending_change_report(change_history)

    change_type_report = pd.DataFrame()

    if "change_type" in change_history.columns:
        change_type_report = make_count_report(
            change_history,
            "change_type",
            "change_type",
        )

    approval_status_report = pd.DataFrame()

    if "approval_status" in change_history.columns:
        approval_status_report = make_count_report(
            change_history,
            "approval_status",
            "approval_status",
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
        st.markdown("### Pending Customer Requests")

        if pending_report.empty:
            st.success("No pending customer change requests.")
        else:
            st.dataframe(pending_report, use_container_width=True)
            download_report_button(
                pending_report,
                "pending_change_requests_report.csv",
                "Download Pending Requests Report",
            )

    with tabs[1]:
        st.markdown("### Change Type Summary")

        if change_type_report.empty:
            st.info("No change type data available.")
        else:
            st.dataframe(change_type_report, use_container_width=True)
            download_report_button(
                change_type_report,
                "change_type_report.csv",
                "Download Change Type Report",
            )

    with tabs[2]:
        st.markdown("### Approval Status Summary")

        if approval_status_report.empty:
            st.info("No approval status data available.")
        else:
            st.dataframe(approval_status_report, use_container_width=True)
            download_report_button(
                approval_status_report,
                "approval_status_report.csv",
                "Download Approval Status Report",
            )

    with tabs[3]:
        st.markdown("### Full Change History")

        full_history = change_history.copy()

        if "change_date" in full_history.columns:
            full_history = full_history.sort_values("change_date", ascending=False)

        st.dataframe(full_history, use_container_width=True)
        download_report_button(
            full_history,
            "full_change_history_report.csv",
            "Download Full Change History",
        )


def main() -> None:
    """
    Owner-facing reports page.

    Reports are intentionally owner-facing because they include branch payments,
    outstanding balances, operational summaries, pickup capacity, and full change history.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    shipments = load_shipments()
    pickups = load_pickups()
    branch_payments = load_branch_payments()
    pickup_capacity = load_pickup_capacity()
    drivers = load_drivers()
    change_history = load_shipment_change_history()

    hero(
        title="Reports",
        subtitle=(
            "Review owner-level reports across New Jersey and Guyana payments, freight collect balances, "
            "pickup capacity, drivers, shipment activity, and customer change history."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner Reports</span>
        <span class="badge-dark">Branch Payments</span>
        <span class="badge-red">Operations + Change History</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

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
        render_financial_reports(branch_payments)

    with report_tabs[1]:
        render_operations_reports(
            shipments=shipments,
            pickups=pickups,
            pickup_capacity=pickup_capacity,
            drivers=drivers,
        )

    with report_tabs[2]:
        render_change_history_reports(change_history)

    with report_tabs[3]:
        st.subheader("Raw Data Export")

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

        with raw_tabs[0]:
            st.dataframe(shipments, use_container_width=True)
            download_report_button(shipments, "shipments_export.csv", "Download Shipments")

        with raw_tabs[1]:
            st.dataframe(pickups, use_container_width=True)
            download_report_button(pickups, "pickups_export.csv", "Download Pickups")

        with raw_tabs[2]:
            st.dataframe(branch_payments, use_container_width=True)
            download_report_button(
                branch_payments,
                "branch_payments_export.csv",
                "Download Branch Payments",
            )

        with raw_tabs[3]:
            st.dataframe(pickup_capacity, use_container_width=True)
            download_report_button(
                pickup_capacity,
                "pickup_capacity_export.csv",
                "Download Pickup Capacity",
            )

        with raw_tabs[4]:
            st.dataframe(drivers, use_container_width=True)
            download_report_button(drivers, "drivers_export.csv", "Download Drivers")

        with raw_tabs[5]:
            st.dataframe(change_history, use_container_width=True)
            download_report_button(
                change_history,
                "change_history_export.csv",
                "Download Change History",
            )


if __name__ == "__main__":
    main()