from __future__ import annotations

import pandas as pd
import plotly.express as px


def create_bar_count_chart(
    df: pd.DataFrame,
    column: str,
    title: str,
    x_label: str | None = None,
    y_label: str = "Count",
):
    """
    Create a bar chart showing counts by category.

    Example:
    Shipments by status
    Payments by status
    Pickups by assigned staff
    """
    if df.empty or column not in df.columns:
        return None

    chart_df = (
        df[column]
        .fillna("Unknown")
        .value_counts()
        .reset_index()
    )

    chart_df.columns = [column, "count"]

    fig = px.bar(
        chart_df,
        x=column,
        y="count",
        title=title,
        text_auto=True,
        labels={
            column: x_label or column.replace("_", " ").title(),
            "count": y_label,
        },
    )

    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=60, b=20),
    )

    return fig


def create_pie_count_chart(
    df: pd.DataFrame,
    column: str,
    title: str,
):
    """
    Create a donut chart showing percentage/count by category.

    Example:
    Payment status breakdown
    Shipment status breakdown
    """
    if df.empty or column not in df.columns:
        return None

    chart_df = (
        df[column]
        .fillna("Unknown")
        .value_counts()
        .reset_index()
    )

    chart_df.columns = [column, "count"]

    fig = px.pie(
        chart_df,
        names=column,
        values="count",
        title=title,
        hole=0.35,
    )

    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=60, b=20),
    )

    return fig


def create_revenue_by_day_chart(payments: pd.DataFrame):
    """
    Create a line chart showing revenue collected by payment date.
    """
    if (
        payments.empty
        or "payment_date" not in payments.columns
        or "amount_paid" not in payments.columns
    ):
        return None

    payment_rows = payments.dropna(subset=["payment_date"]).copy()

    if payment_rows.empty:
        return None

    chart_df = (
        payment_rows
        .groupby(payment_rows["payment_date"].dt.date, as_index=False)["amount_paid"]
        .sum()
    )

    chart_df.columns = ["payment_date", "amount_paid"]

    fig = px.line(
        chart_df,
        x="payment_date",
        y="amount_paid",
        markers=True,
        title="Revenue Collected by Day",
        labels={
            "payment_date": "Payment Date",
            "amount_paid": "Amount Paid",
        },
    )

    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=60, b=20),
    )

    return fig


def create_outstanding_balance_chart(payments: pd.DataFrame):
    """
    Create a bar chart showing outstanding balance by customer.
    """
    if (
        payments.empty
        or "customer_name" not in payments.columns
        or "balance_due" not in payments.columns
    ):
        return None

    chart_df = (
        payments.groupby("customer_name", as_index=False)["balance_due"]
        .sum()
        .sort_values("balance_due", ascending=False)
    )

    chart_df = chart_df[chart_df["balance_due"] > 0]

    if chart_df.empty:
        return None

    fig = px.bar(
        chart_df,
        x="customer_name",
        y="balance_due",
        title="Outstanding Balance by Customer",
        text_auto=True,
        labels={
            "customer_name": "Customer",
            "balance_due": "Balance Due",
        },
    )

    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis_tickangle=-35,
    )

    return fig


def create_shipments_by_day_chart(shipments: pd.DataFrame):
    """
    Create a bar chart showing shipment count by shipment date.
    """
    if shipments.empty or "shipment_date" not in shipments.columns:
        return None

    shipment_rows = shipments.dropna(subset=["shipment_date"]).copy()

    if shipment_rows.empty:
        return None

    chart_df = (
        shipment_rows
        .groupby(shipment_rows["shipment_date"].dt.date)
        .size()
        .reset_index(name="shipment_count")
    )

    chart_df.columns = ["shipment_date", "shipment_count"]

    fig = px.bar(
        chart_df,
        x="shipment_date",
        y="shipment_count",
        title="Shipments by Day",
        text_auto=True,
        labels={
            "shipment_date": "Shipment Date",
            "shipment_count": "Shipment Count",
        },
    )

    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=60, b=20),
    )

    return fig