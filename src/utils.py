from __future__ import annotations

import pandas as pd


def format_currency(value: float | int | None) -> str:
    """
    Format a number as currency.

    Example:
    2500 -> $2,500.00
    """
    if value is None or pd.isna(value):
        return "$0.00"

    return f"${float(value):,.2f}"


def format_number(value: float | int | None) -> str:
    """
    Format a number with commas.

    Example:
    2500 -> 2,500
    """
    if value is None or pd.isna(value):
        return "0"

    return f"{int(value):,}"


def safe_date_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """
    Convert a column to datetime only if it exists.
    This keeps the app from crashing if a date column is missing.
    """
    if column in df.columns:
        df[column] = pd.to_datetime(df[column], errors="coerce")

    return df


def add_search_column(
    df: pd.DataFrame,
    columns: list[str],
    output_col: str = "_search_text",
) -> pd.DataFrame:
    """
    Create one combined lowercase search column from multiple fields.

    This allows search across shipment ID, customer name, destination,
    payment status, and other fields.
    """
    available_columns = [col for col in columns if col in df.columns]

    if not available_columns:
        df[output_col] = ""
        return df

    df[output_col] = (
        df[available_columns]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )

    return df