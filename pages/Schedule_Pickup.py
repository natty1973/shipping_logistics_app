from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(
    page_title="Schedule Pickup",
    page_icon="🚚",
    layout="wide",
)

SCHEMA = "solomon_shipping"

PICKUP_STATUSES = [
    "Pending Confirmation",
    "Scheduled",
    "Rescheduled",
    "Driver Assigned",
    "On the Way",
    "Arrived",
    "Picked Up",
    "Completed",
    "Cancelled",
    "No Show",
]

PICKUP_WINDOWS = [
    "Morning",
    "Afternoon",
    "Evening",
    "Flexible",
    "8 AM – 10 AM",
    "10 AM – 12 PM",
    "12 PM – 2 PM",
    "2 PM – 4 PM",
    "4 PM – 6 PM",
]

DEFAULT_AREAS = [
    "Queens",
    "Brooklyn",
    "Bronx",
    "Manhattan",
    "Staten Island",
    "New Jersey",
    "Jersey City",
    "Newark",
    "Long Island",
    "Other",
]

REVIEW_TYPES = [
    "Request Pickup Reschedule",
    "Request Shipment Cancellation",
    "Update Pickup Notes",
    "Update Contact Information",
    "General Shipment Change Request",
    "Reschedule Requested",
    "Cancellation Requested",
]


def secret(name: str) -> str:
    value = os.getenv(name, "").strip()

    if value:
        return value

    try:
        return str(
            st.secrets.get(name, "")
        ).strip()

    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        return ""


@st.cache_resource(show_spinner=False)
def db_engine() -> Engine:
    database_url = secret("DATABASE_URL")

    if database_url:
        if database_url.startswith("postgres://"):
            database_url = (
                "postgresql://"
                + database_url[len("postgres://"):]
            )

        target: str | URL = database_url

    else:
        values = {
            "user": secret("DB_USER"),
            "password": secret("DB_PASSWORD"),
            "host": secret("DB_HOST"),
            "port": secret("DB_PORT") or "5432",
            "database": secret("DB_NAME"),
            "sslmode": secret("DB_SSLMODE") or "require",
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
            port = int(values["port"])
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
                "sslmode": values["sslmode"]
            },
        )

    engine = create_engine(
        target,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 15,
            "application_name": (
                "solomon_shipping_schedule_pickup"
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


def clean(
    value: Any,
    default: str = "Not Available",
) -> str:
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default

    except (TypeError, ValueError):
        pass

    value = str(value).strip()

    return value or default


def portal_role() -> str:
    mode = str(
        st.session_state.get(
            "portal_mode",
            "staff",
        )
    ).lower()

    return {
        "owner": "Owner",
        "admin": "Admin",
    }.get(
        mode,
        "Staff",
    )


def verify_tables(
    engine: Engine,
) -> None:
    required = [
        "shipments",
        "pickup_schedule",
        "drivers",
        "pickup_capacity",
        "shipment_change_history",
        "status_history",
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
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    with engine.connect() as connection:
        return pd.read_sql_query(
            text(query),
            connection,
            params=params or {},
        )


def load_pickups(
    engine: Engine,
) -> pd.DataFrame:
    return read_df(
        engine,
        f"""
        SELECT
            p.pickup_id,
            p.shipment_id,
            p.customer_id,
            p.customer_name,
            p.pickup_date,
            p.pickup_time_window,
            p.pickup_address,
            p.assigned_staff,
            p.pickup_status,
            p.notes,
            p.driver_id,
            d.driver_name,
            d.phone AS driver_phone,
            d.vehicle_type,
            d.vehicle_plate,
            d.active_status
                AS driver_active_status,
            s.current_status
                AS shipment_status,
            s.destination_city,
            s.destination_country,
            s.service_type,
            s.shipment_mode
        FROM {SCHEMA}.pickup_schedule p
        LEFT JOIN {SCHEMA}.drivers d
            ON d.driver_id = p.driver_id
        LEFT JOIN {SCHEMA}.shipments s
            ON s.shipment_id = p.shipment_id
        ORDER BY
            p.pickup_date ASC NULLS LAST,
            p.created_at DESC
        """,
    )


def load_drivers(
    engine: Engine,
) -> pd.DataFrame:
    return read_df(
        engine,
        f"""
        SELECT
            driver_id,
            driver_name,
            phone,
            home_base,
            service_areas,
            primary_area,
            max_pickups_per_day,
            vehicle_type,
            vehicle_plate,
            active_status,
            notes
        FROM {SCHEMA}.drivers
        ORDER BY
            CASE
                WHEN active_status = 'Active'
                    THEN 1
                WHEN active_status = 'Backup'
                    THEN 2
                ELSE 3
            END,
            driver_name
        """,
    )


def load_capacity(
    engine: Engine,
) -> pd.DataFrame:
    return read_df(
        engine,
        f"""
        SELECT
            capacity_id,
            pickup_date,
            pickup_area,
            assigned_driver_ids,
            driver_count,
            max_pickups,
            scheduled_pickups,
            available_slots,
            capacity_status,
            notes
        FROM {SCHEMA}.pickup_capacity
        ORDER BY
            pickup_date,
            pickup_area
        """,
    )


def load_pending_changes(
    engine: Engine,
) -> pd.DataFrame:
    quoted_types = ", ".join(
        "'" + item.replace("'", "''") + "'"
        for item in REVIEW_TYPES
    )

    return read_df(
        engine,
        f"""
        SELECT
            change_id,
            shipment_id,
            customer_id,
            customer_name,
            change_date,
            change_type,
            old_value,
            new_value,
            requested_by,
            requested_role,
            request_reason,
            approval_status,
            approved_by,
            approved_role,
            approved_date,
            notes
        FROM {SCHEMA}.shipment_change_history
        WHERE
            LOWER(
                COALESCE(
                    approval_status,
                    'pending'
                )
            ) = 'pending'
            AND change_type IN (
                {quoted_types}
            )
        ORDER BY
            change_date DESC
        """,
    )


def pickup_area(
    notes: Any,
) -> str:
    match = re.search(
        r"Pickup area:\s*([^\n\r]+)",
        clean(notes, ""),
        re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    return "Other"


def as_date(
    value: Any,
) -> date:
    if isinstance(value, date):
        return value

    try:
        return pd.to_datetime(
            value
        ).date()

    except (TypeError, ValueError):
        return date.today()


def add_note(
    existing: Any,
    new_note: str,
) -> str:
    old = clean(existing, "")

    if old:
        return f"{old}\n\n{new_note}"

    return new_note


def driver_choices(
    drivers: pd.DataFrame,
) -> tuple[list[str], dict[str, str]]:
    ids = [""]
    labels = {
        "": "Unassigned"
    }

    if drivers.empty:
        return ids, labels

    active = drivers[
        drivers["active_status"]
        .astype(str)
        .isin(
            [
                "Active",
                "Backup",
            ]
        )
    ]

    for _, row in active.iterrows():
        driver_id = clean(
            row.get("driver_id"),
            "",
        )

        driver_name = clean(
            row.get("driver_name"),
            "",
        )

        if not driver_id or not driver_name:
            continue

        details = [
            value
            for value in [
                clean(
                    row.get("primary_area"),
                    "",
                ),
                clean(
                    row.get("vehicle_type"),
                    "",
                ),
            ]
            if value
        ]

        ids.append(driver_id)

        labels[driver_id] = (
            driver_name
            + (
                f" — {' | '.join(details)}"
                if details
                else ""
            )
        )

    return ids, labels


def area_choices(
    pickups: pd.DataFrame,
    capacity: pd.DataFrame,
) -> list[str]:
    areas = set(DEFAULT_AREAS)

    if not capacity.empty:
        areas.update(
            capacity["pickup_area"]
            .dropna()
            .astype(str)
        )

    if not pickups.empty:
        areas.update(
            pickup_area(value)
            for value in pickups["notes"]
        )

    return sorted(
        area
        for area in areas
        if area
    )


def capacity_record(
    capacity: pd.DataFrame,
    area: str,
    selected_date: date,
) -> pd.DataFrame:
    if capacity.empty:
        return pd.DataFrame()

    frame = capacity.copy()

    frame["pickup_date"] = (
        pd.to_datetime(
            frame["pickup_date"],
            errors="coerce",
        )
        .dt.date
    )

    return frame[
        frame["pickup_area"]
        .astype(str)
        .str.lower()
        .eq(area.lower())
        & frame["pickup_date"]
        .eq(selected_date)
    ]


def show_capacity(
    frame: pd.DataFrame,
) -> None:
    if frame.empty:
        st.info(
            "No capacity record exists "
            "for this area and date."
        )
        return

    row = frame.iloc[0]

    columns = st.columns(4)

    values = [
        (
            "Max Pickups",
            int(
                row.get(
                    "max_pickups",
                    0,
                )
                or 0
            ),
        ),
        (
            "Scheduled",
            int(
                row.get(
                    "scheduled_pickups",
                    0,
                )
                or 0
            ),
        ),
        (
            "Available Slots",
            int(
                row.get(
                    "available_slots",
                    0,
                )
                or 0
            ),
        ),
        (
            "Capacity Status",
            clean(
                row.get(
                    "capacity_status"
                )
            ),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        columns,
        values,
    ):
        with column:
            st.metric(
                label,
                value,
            )

    available = int(
        row.get(
            "available_slots",
            0,
        )
        or 0
    )

    status = clean(
        row.get(
            "capacity_status"
        ),
        "",
    ).lower()

    if (
        status == "full"
        or available <= 0
    ):
        st.error(
            "This route and date are full."
        )

    elif status == "limited":
        st.warning(
            "This route and date have "
            "limited availability."
        )

    else:
        st.success(
            "This route and date have "
            "pickup availability."
        )


def add_status(
    connection: Any,
    shipment_id: str,
    status: str,
    updated_by: str,
    notes: str,
) -> None:
    connection.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.status_history (
                status_id,
                shipment_id,
                status,
                status_date,
                updated_by,
                notes
            )
            VALUES (
                :status_id,
                :shipment_id,
                :status,
                CURRENT_TIMESTAMP,
                :updated_by,
                :notes
            )
            """
        ),
        {
            "status_id": (
                "STAT-"
                + uuid4().hex[:24].upper()
            ),
            "shipment_id": shipment_id,
            "status": status,
            "updated_by": updated_by,
            "notes": notes,
        },
    )


def mark_milestone(
    connection: Any,
    shipment_id: str,
    milestone_code: str,
    updated_by: str,
) -> None:
    milestone_table = connection.execute(
        text(
            """
            SELECT TO_REGCLASS(
                'solomon_shipping.shipment_milestones'
            )
            """
        )
    ).scalar_one_or_none()

    if milestone_table is None:
        return

    connection.execute(
        text(
            f"""
            UPDATE {SCHEMA}.shipment_milestones
            SET
                milestone_status = 'Achieved',
                achieved_date = COALESCE(
                    achieved_date,
                    CURRENT_TIMESTAMP
                ),
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE
                shipment_id = :shipment_id
                AND milestone_code = :milestone_code
            """
        ),
        {
            "shipment_id": shipment_id,
            "milestone_code": milestone_code,
            "updated_by": updated_by,
        },
    )


def save_pickup(
    engine: Engine,
    record: dict[str, Any],
    selected_date: date,
    window: str,
    area: str,
    driver_id: str,
    status: str,
    dispatcher: str,
    notified: bool,
    notes: str,
) -> None:
    pickup_id = clean(
        record.get("pickup_id"),
        "",
    )

    shipment_id = clean(
        record.get("shipment_id"),
        "",
    )

    if not pickup_id or not shipment_id:
        raise RuntimeError(
            "The selected pickup is "
            "missing its ID."
        )

    entry = (
        f"[{datetime.now():%Y-%m-%d %H:%M}] "
        f"Pickup area: {area}\n"
        f"Updated by: {dispatcher}\n"
        f"Customer notified: "
        f"{'Yes' if notified else 'No'}"
    )

    if notes.strip():
        entry += (
            "\nInternal notes: "
            + notes.strip()
        )

    shipment_status = {
        "Scheduled": "Pickup Scheduled",
        "Rescheduled": "Pickup Scheduled",
        "Driver Assigned": "Pickup Scheduled",
        "Picked Up": "Picked Up",
        "Completed": "Picked Up",
        "Cancelled": "Cancelled",
    }.get(status)

    with engine.begin() as connection:
        updated = connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.pickup_schedule
                SET
                    pickup_date = :pickup_date,
                    pickup_time_window =
                        :pickup_time_window,
                    driver_id =
                        NULLIF(:driver_id, ''),
                    assigned_staff =
                        :assigned_staff,
                    pickup_status =
                        :pickup_status,
                    notes = :notes,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE
                    pickup_id = :pickup_id
                """
            ),
            {
                "pickup_date": selected_date,
                "pickup_time_window": window,
                "driver_id": driver_id,
                "assigned_staff": dispatcher,
                "pickup_status": status,
                "notes": add_note(
                    record.get("notes"),
                    entry,
                ),
                "pickup_id": pickup_id,
            },
        ).rowcount

        if updated != 1:
            raise RuntimeError(
                "The pickup record "
                "was not updated."
            )

        if shipment_status:
            current = connection.execute(
                text(
                    f"""
                    SELECT
                        current_status
                    FROM {SCHEMA}.shipments
                    WHERE
                        shipment_id =
                            :shipment_id
                    FOR UPDATE
                    """
                ),
                {
                    "shipment_id": shipment_id
                },
            ).scalar_one_or_none()

            if current != shipment_status:
                connection.execute(
                    text(
                        f"""
                        UPDATE {SCHEMA}.shipments
                        SET
                            current_status =
                                :status,
                            updated_at =
                                CURRENT_TIMESTAMP
                        WHERE
                            shipment_id =
                                :shipment_id
                        """
                    ),
                    {
                        "status": shipment_status,
                        "shipment_id": shipment_id,
                    },
                )

                add_status(
                    connection,
                    shipment_id,
                    shipment_status,
                    dispatcher,
                    (
                        "Updated from the "
                        "Schedule Pickup page."
                    ),
                )

        if status in {
            "Scheduled",
            "Rescheduled",
            "Driver Assigned",
        }:
            mark_milestone(
                connection,
                shipment_id,
                "PICKUP_SCHEDULED",
                dispatcher,
            )

        elif status in {
            "Picked Up",
            "Completed",
        }:
            mark_milestone(
                connection,
                shipment_id,
                "PICKED_UP",
                dispatcher,
            )


def parse_reschedule(
    value: str,
) -> tuple[date | None, str]:
    match = re.search(
        r"(\d{4}-\d{2}-\d{2})"
        r"\s*(?:—|-)?\s*(.*)",
        value,
    )

    if not match:
        return None, ""

    try:
        selected_date = datetime.strptime(
            match.group(1),
            "%Y-%m-%d",
        ).date()

    except ValueError:
        selected_date = None

    return (
        selected_date,
        match.group(2).strip(),
    )


def parse_contact(
    value: str,
) -> tuple[str, str]:
    phone_match = re.search(
        r"Phone:\s*([^;]+)",
        value,
        re.IGNORECASE,
    )

    email_match = re.search(
        r"Email:\s*(.+)$",
        value,
        re.IGNORECASE,
    )

    phone = (
        phone_match.group(1).strip()
        if phone_match
        else ""
    )

    email = (
        email_match.group(1).strip()
        if email_match
        else ""
    )

    if phone.lower().startswith(
        "no phone"
    ):
        phone = ""

    if email.lower().startswith(
        "no email"
    ):
        email = ""

    return phone, email


def apply_approved_change(
    connection: Any,
    change: dict[str, Any],
    reviewer: str,
) -> None:
    shipment_id = clean(
        change.get("shipment_id"),
        "",
    )

    customer_id = clean(
        change.get("customer_id"),
        "",
    )

    change_type = clean(
        change.get("change_type"),
        "",
    )

    new_value = clean(
        change.get("new_value"),
        "",
    )

    if (
        change_type
        == "Request Pickup Reschedule"
    ):
        selected_date, window = (
            parse_reschedule(new_value)
        )

        if selected_date is None:
            raise RuntimeError(
                "The requested pickup date "
                "could not be read."
            )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.pickup_schedule
                SET
                    pickup_date =
                        :pickup_date,
                    pickup_time_window =
                        COALESCE(
                            NULLIF(
                                :window,
                                ''
                            ),
                            pickup_time_window
                        ),
                    pickup_status =
                        'Rescheduled',
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE
                    shipment_id =
                        :shipment_id
                """
            ),
            {
                "pickup_date": selected_date,
                "window": window,
                "shipment_id": shipment_id,
            },
        )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.shipments
                SET
                    current_status =
                        'Pickup Scheduled',
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE
                    shipment_id =
                        :shipment_id
                """
            ),
            {
                "shipment_id": shipment_id
            },
        )

        add_status(
            connection,
            shipment_id,
            "Pickup Scheduled",
            reviewer,
            (
                "Customer pickup reschedule "
                "request approved."
            ),
        )

        mark_milestone(
            connection,
            shipment_id,
            "PICKUP_SCHEDULED",
            reviewer,
        )

    elif (
        change_type
        == "Request Shipment Cancellation"
    ):
        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.shipments
                SET
                    current_status =
                        'Cancelled',
                    release_status =
                        'Cancelled',
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE
                    shipment_id =
                        :shipment_id
                """
            ),
            {
                "shipment_id": shipment_id
            },
        )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.pickup_schedule
                SET
                    pickup_status =
                        'Cancelled',
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE
                    shipment_id =
                        :shipment_id
                """
            ),
            {
                "shipment_id": shipment_id
            },
        )

        add_status(
            connection,
            shipment_id,
            "Cancelled",
            reviewer,
            (
                "Customer cancellation "
                "request approved."
            ),
        )

    elif (
        change_type
        == "Update Contact Information"
    ):
        phone, email = parse_contact(
            new_value
        )

        if phone or email:
            connection.execute(
                text(
                    f"""
                    UPDATE {SCHEMA}.customers
                    SET
                        phone = CASE
                            WHEN NULLIF(
                                :phone,
                                ''
                            ) IS NOT NULL
                                THEN :phone
                            ELSE phone
                        END,
                        email = CASE
                            WHEN NULLIF(
                                :email,
                                ''
                            ) IS NOT NULL
                                THEN :email
                            ELSE email
                        END,
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE
                        customer_id =
                            :customer_id
                    """
                ),
                {
                    "phone": phone,
                    "email": email,
                    "customer_id": customer_id,
                },
            )

    elif (
        change_type
        == "Update Pickup Notes"
    ):
        pickup = connection.execute(
            text(
                f"""
                SELECT
                    pickup_id,
                    notes
                FROM {SCHEMA}.pickup_schedule
                WHERE
                    shipment_id =
                        :shipment_id
                ORDER BY
                    created_at DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {
                "shipment_id": shipment_id
            },
        ).mappings().first()

        if pickup:
            connection.execute(
                text(
                    f"""
                    UPDATE {SCHEMA}.pickup_schedule
                    SET
                        notes = :notes,
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE
                        pickup_id =
                            :pickup_id
                    """
                ),
                {
                    "notes": add_note(
                        pickup["notes"],
                        (
                            f"[{datetime.now():%Y-%m-%d %H:%M}] "
                            "Approved customer "
                            "pickup note:\n"
                            f"{new_value}"
                        ),
                    ),
                    "pickup_id": (
                        pickup["pickup_id"]
                    ),
                },
            )


def review_change(
    engine: Engine,
    change: dict[str, Any],
    decision: str,
    reviewer: str,
    role: str,
    review_notes: str,
) -> str:
    status = {
        "Approve": "Approved",
        "Reject": "Rejected",
        "Needs Follow-Up": (
            "Needs Follow-Up"
        ),
    }[decision]

    change_id = clean(
        change.get("change_id"),
        "",
    )

    if not change_id:
        raise RuntimeError(
            "The selected request has "
            "no Change ID."
        )

    with engine.begin() as connection:
        current = connection.execute(
            text(
                f"""
                SELECT *
                FROM {SCHEMA}.shipment_change_history
                WHERE
                    change_id = :change_id
                FOR UPDATE
                """
            ),
            {
                "change_id": change_id
            },
        ).mappings().first()

        if current is None:
            raise RuntimeError(
                "The change request "
                "no longer exists."
            )

        if clean(
            current.get(
                "approval_status"
            ),
            "Pending",
        ).lower() != "pending":
            raise RuntimeError(
                "This request has already "
                "been reviewed."
            )

        if status == "Approved":
            apply_approved_change(
                connection,
                dict(current),
                reviewer,
            )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.shipment_change_history
                SET
                    approval_status =
                        :status,
                    approved_by =
                        :reviewer,
                    approved_role =
                        :role,
                    approved_date =
                        CURRENT_TIMESTAMP,
                    notes = CASE
                        WHEN NULLIF(
                            :review_notes,
                            ''
                        ) IS NULL
                            THEN notes
                        WHEN notes IS NULL
                             OR BTRIM(notes) = ''
                            THEN :review_notes
                        ELSE
                            notes
                            || E'\n\nReview notes: '
                            || :review_notes
                    END
                WHERE
                    change_id =
                        :change_id
                """
            ),
            {
                "status": status,
                "reviewer": reviewer,
                "role": role,
                "review_notes": (
                    review_notes.strip()
                ),
                "change_id": change_id,
            },
        )

    return status


def main() -> None:
    apply_custom_styles()
    sidebar_shipping_options()

    role = portal_role()

    hero(
        title="Schedule Pickup",
        subtitle=(
            "Review pickup requests, check route "
            "capacity, assign drivers, confirm pickup "
            "windows, and review customer change requests."
        ),
    )

    st.markdown(
        f"""
        <span class="badge-green">{role} Operations</span>
        <span class="badge-dark">Pickup Scheduling</span>
        <span class="badge-red">Neon Database</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = db_engine()
        verify_tables(engine)

        pickups = load_pickups(engine)
        drivers = load_drivers(engine)
        capacity = load_capacity(engine)
        pending_changes = (
            load_pending_changes(engine)
        )

    except Exception as exc:
        st.error(
            "The Schedule Pickup page could "
            "not load records from Neon."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error(exc)}"
        )

        return

    available_slots = (
        int(
            pd.to_numeric(
                capacity["available_slots"],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )
        if not capacity.empty
        else 0
    )

    active_drivers = (
        int(
            drivers["active_status"]
            .astype(str)
            .eq("Active")
            .sum()
        )
        if not drivers.empty
        else 0
    )

    st.subheader(
        "Dispatch Overview"
    )

    metrics = st.columns(4)

    for column, (
        label,
        value,
    ) in zip(
        metrics,
        [
            (
                "Pickup Records",
                len(pickups),
            ),
            (
                "Active Drivers",
                active_drivers,
            ),
            (
                "Available Slots",
                available_slots,
            ),
            (
                "Pending Changes",
                len(pending_changes),
            ),
        ],
    ):
        with column:
            st.metric(
                label,
                value,
            )

    tabs = st.tabs(
        [
            "Pickup Work Queue",
            "Capacity Board",
            "Driver Directory",
            "Customer Change Requests",
        ]
    )

    with tabs[0]:
        if pickups.empty:
            st.info(
                "No pickup records are "
                "stored in Neon."
            )

        else:
            search_value = st.text_input(
                "Search pickup ID, shipment ID, "
                "customer, address, driver, or status"
            )

            filtered = pickups.copy()

            if search_value.strip():
                search_columns = [
                    "pickup_id",
                    "shipment_id",
                    "customer_name",
                    "pickup_address",
                    "pickup_status",
                    "driver_name",
                    "assigned_staff",
                    "notes",
                ]

                combined = (
                    filtered[search_columns]
                    .fillna("")
                    .astype(str)
                    .agg(
                        " ".join,
                        axis=1,
                    )
                )

                filtered = filtered[
                    combined.str.contains(
                        search_value.strip(),
                        case=False,
                        na=False,
                    )
                ]

            st.dataframe(
                filtered[
                    [
                        "pickup_id",
                        "shipment_id",
                        "customer_name",
                        "pickup_date",
                        "pickup_time_window",
                        "pickup_address",
                        "driver_name",
                        "pickup_status",
                        "shipment_status",
                    ]
                ],
                use_container_width=True,
            )

            if not filtered.empty:
                selected_id = st.selectbox(
                    "Select Pickup ID to update",
                    filtered["pickup_id"]
                    .dropna()
                    .astype(str)
                    .tolist(),
                )

                record = filtered[
                    filtered["pickup_id"]
                    .astype(str)
                    .eq(selected_id)
                ].iloc[0].to_dict()

                current_status = clean(
                    record.get(
                        "pickup_status"
                    ),
                    "Pending Confirmation",
                )

                current_window = clean(
                    record.get(
                        "pickup_time_window"
                    ),
                    "Flexible",
                )

                current_date = as_date(
                    record.get(
                        "pickup_date"
                    )
                )

                current_area = pickup_area(
                    record.get("notes")
                )

                areas = area_choices(
                    pickups,
                    capacity,
                )

                if current_area not in areas:
                    areas.append(current_area)
                    areas.sort()

                (
                    driver_ids,
                    driver_labels,
                ) = driver_choices(drivers)

                current_driver = clean(
                    record.get("driver_id"),
                    "",
                )

                with st.form(
                    "pickup_update_form"
                ):
                    left, right = st.columns(2)

                    with left:
                        selected_date = (
                            st.date_input(
                                "Confirmed Pickup Date",
                                value=current_date,
                            )
                        )

                        selected_window = (
                            st.selectbox(
                                (
                                    "Confirmed "
                                    "Pickup Window"
                                ),
                                PICKUP_WINDOWS,
                                index=(
                                    PICKUP_WINDOWS.index(
                                        current_window
                                    )
                                    if current_window
                                    in PICKUP_WINDOWS
                                    else 0
                                ),
                            )
                        )

                        selected_area = (
                            st.selectbox(
                                "Pickup Area",
                                areas,
                                index=areas.index(
                                    current_area
                                ),
                            )
                        )

                        selected_status = (
                            st.selectbox(
                                "Pickup Status",
                                PICKUP_STATUSES,
                                index=(
                                    PICKUP_STATUSES.index(
                                        current_status
                                    )
                                    if current_status
                                    in PICKUP_STATUSES
                                    else 0
                                ),
                            )
                        )

                    with right:
                        selected_driver = (
                            st.selectbox(
                                "Assign Driver",
                                driver_ids,
                                index=(
                                    driver_ids.index(
                                        current_driver
                                    )
                                    if current_driver
                                    in driver_ids
                                    else 0
                                ),
                                format_func=(
                                    lambda value: (
                                        driver_labels[
                                            value
                                        ]
                                    )
                                ),
                            )
                        )

                        dispatcher = (
                            st.text_input(
                                (
                                    "Updated By / "
                                    "Dispatcher"
                                ),
                                value=role,
                            )
                        )

                        notified = st.checkbox(
                            "Customer Notified"
                        )

                        completed = st.checkbox(
                            "Mark Pickup Completed"
                        )

                    notes = st.text_area(
                        "Internal Pickup Notes",
                        height=110,
                    )

                    submitted = (
                        st.form_submit_button(
                            "Save Pickup Update",
                            use_container_width=True,
                        )
                    )

                show_capacity(
                    capacity_record(
                        capacity,
                        selected_area,
                        selected_date,
                    )
                )

                if submitted:
                    try:
                        save_pickup(
                            engine,
                            record,
                            selected_date,
                            selected_window,
                            selected_area,
                            selected_driver,
                            (
                                "Completed"
                                if completed
                                else selected_status
                            ),
                            (
                                dispatcher.strip()
                                or role
                            ),
                            notified,
                            notes,
                        )

                        st.success(
                            "Pickup update saved "
                            "to Neon."
                        )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            "The pickup update "
                            "could not be saved."
                        )

                        st.caption(
                            "Technical details: "
                            f"{type(exc).__name__}: "
                            f"{safe_error(exc)}"
                        )

    with tabs[1]:
        st.subheader(
            "Pickup Capacity Board"
        )

        if capacity.empty:
            st.info(
                "No pickup-capacity records "
                "are stored in Neon."
            )
        else:
            st.dataframe(
                capacity,
                use_container_width=True,
            )

    with tabs[2]:
        st.subheader(
            "Driver Directory"
        )

        if drivers.empty:
            st.info(
                "No driver records are "
                "stored in Neon."
            )
        else:
            st.dataframe(
                drivers,
                use_container_width=True,
            )

    with tabs[3]:
        st.subheader(
            "Customer Change Requests "
            "for Review"
        )

        if pending_changes.empty:
            st.success(
                "There are no pending "
                "customer change requests."
            )

        else:
            st.dataframe(
                pending_changes,
                use_container_width=True,
            )

            change_id = st.selectbox(
                "Select Change Request",
                pending_changes["change_id"]
                .astype(str)
                .tolist(),
            )

            change = pending_changes[
                pending_changes["change_id"]
                .astype(str)
                .eq(change_id)
            ].iloc[0].to_dict()

            with st.container(
                border=True
            ):
                st.write(
                    "**Shipment:** "
                    + clean(
                        change.get(
                            "shipment_id"
                        )
                    )
                )

                st.write(
                    "**Change type:** "
                    + clean(
                        change.get(
                            "change_type"
                        )
                    )
                )

                st.write(
                    "**Requested change:** "
                    + clean(
                        change.get(
                            "new_value"
                        )
                    )
                )

            with st.form(
                "change_review_form"
            ):
                decision = st.selectbox(
                    "Decision",
                    [
                        "Approve",
                        "Reject",
                        "Needs Follow-Up",
                    ],
                )

                reviewer = st.text_input(
                    "Reviewed By",
                    value=role,
                )

                review_notes = (
                    st.text_area(
                        "Review Notes",
                        height=110,
                    )
                )

                review_submitted = (
                    st.form_submit_button(
                        "Save Review Decision",
                        use_container_width=True,
                    )
                )

            if review_submitted:
                try:
                    saved_status = (
                        review_change(
                            engine,
                            change,
                            decision,
                            (
                                reviewer.strip()
                                or role
                            ),
                            role,
                            review_notes,
                        )
                    )

                    st.success(
                        "Review saved. Status: "
                        f"{saved_status}."
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(
                        "The review decision "
                        "could not be saved."
                    )

                    st.caption(
                        "Technical details: "
                        f"{type(exc).__name__}: "
                        f"{safe_error(exc)}"
                    )


if __name__ == "__main__":
    main()