from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_csv_file(file_name: str) -> pd.DataFrame:
    """
    Safely load a CSV file from the data folder.
    Returns an empty DataFrame if the file is missing.
    """

    file_path = DATA_DIR / file_name

    if not file_path.exists():
        return pd.DataFrame()

    return pd.read_csv(file_path)


def clean_currency_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert common currency columns to numeric values.
    """

    if df.empty:
        return df

    currency_columns = [
        "amount_charged",
        "amount_paid",
        "balance_due",
        "total_charged",
        "total_paid",
        "outstanding_balance",
        "amount_paid_nj",
        "amount_paid_guyana",
        "total_amount_paid",
    ]

    for column in currency_columns:
        if column in df.columns:
            df[column] = (
                df[column]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
            )

            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)

    return df


def clean_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert common count/capacity columns to numeric values.
    """

    if df.empty:
        return df

    numeric_columns = [
        "quantity",
        "driver_count",
        "max_pickups",
        "scheduled_pickups",
        "available_slots",
        "max_pickups_per_day",
        "pickup_order",
        "estimated_pickup_order",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)

    return df


def clean_standard_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply common cleaning rules to any loaded dataframe.
    """

    if df.empty:
        return df

    df = clean_currency_columns(df)
    df = clean_numeric_columns(df)

    return df


@st.cache_data
def load_customers() -> pd.DataFrame:
    """
    Load customer data.
    """
    df = load_csv_file("customers.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_shipments() -> pd.DataFrame:
    """
    Load shipment data.
    """
    df = load_csv_file("shipments.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_pickups() -> pd.DataFrame:
    """
    Load pickup schedule data.
    """
    df = load_csv_file("pickup_schedule.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_payments() -> pd.DataFrame:
    """
    Load payment data.
    """
    df = load_csv_file("payments.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_branch_payments() -> pd.DataFrame:
    """
    Load branch payment data.

    This supports New Jersey and Guyana payment workflows, including:
    - Sender Paid / Prepaid
    - Receiver Paid / Freight Collect
    - Split Payment
    - Amount paid in New Jersey
    - Amount paid in Guyana
    - Balance due
    - Release status
    """
    df = load_csv_file("branch_payments.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_status_history() -> pd.DataFrame:
    """
    Load shipment status history data.
    """
    df = load_csv_file("status_history.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_shipment_change_history() -> pd.DataFrame:
    """
    Load shipment change/audit history data.

    This includes reschedule requests, cancellation requests,
    staff approvals, owner approvals, driver assignment, status changes,
    payment updates, and support requests.
    """
    df = load_csv_file("shipment_change_history.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_drivers() -> pd.DataFrame:
    """
    Load driver information.

    This includes driver name, phone, home base, service areas,
    vehicle details, active status, and max pickups per day.
    """
    df = load_csv_file("drivers.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_pickup_capacity() -> pd.DataFrame:
    """
    Load pickup capacity by date and pickup area.

    This helps the app understand how many pickup slots are available
    by area/date based on driver count and scheduled pickups.
    """
    df = load_csv_file("pickup_capacity.csv")
    return clean_standard_columns(df)


@st.cache_data
def load_all_data() -> dict[str, pd.DataFrame]:
    """
    Load all CSV data files used across the platform.
    """

    return {
        "customers": load_customers(),
        "shipments": load_shipments(),
        "pickups": load_pickups(),
        "payments": load_payments(),
        "branch_payments": load_branch_payments(),
        "status_history": load_status_history(),
        "change_history": load_shipment_change_history(),
        "drivers": load_drivers(),
        "pickup_capacity": load_pickup_capacity(),
    }