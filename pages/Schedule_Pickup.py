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
    "Pending Driver Acceptance",
    "Driver Accepted",
    "Driver En Route",
    "Driver Delayed — Traffic",
    "Driver Arrived",
    "Driver Waiting — No Answer",
    "Driver Waiting for Customer",
    "Customer Not Ready — Staff Review",
    "Customer Requested Reschedule",
    "Address Issue — Staff Review",
    "Unable to Access — Staff Review",
    "Vehicle Issue — Reassignment Needed",
    "Driver Declined — Reassignment Needed",
    "Pickup Issue — Staff Review",
    "Picked Up",
    "Completed",
    "Cancelled",
    "No Show",
]

PICKUP_WINDOWS = [
    "8:00 AM – 10:00 AM",
    "10:00 AM – 12:00 PM",
    "12:00 PM – 2:00 PM",
    "2:00 PM – 4:00 PM",
    "4:00 PM – 6:00 PM",
]

NEW_PICKUP_STATUSES = {
    "pending",
    "pending confirmation",
    "awaiting confirmation",
}

SCHEDULED_PICKUP_STATUSES = {
    "scheduled",
    "rescheduled",
    "pending driver acceptance",
    "driver accepted",
    "driver en route",
    "driver delayed — traffic",
    "driver arrived",
    "driver waiting — no answer",
    "driver waiting for customer",
}

CLOSED_PICKUP_STATUSES = {
    "picked up",
    "completed",
    "cancelled",
    "no show",
}

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
        "driver_assignments",
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
    """
    Load the complete shipment-request and pickup queue.

    The queue starts from shipments rather than pickup_schedule so every
    customer request appears on the Schedule Pickup page. The latest pickup
    row is joined when one already exists.
    """

    return read_df(
        engine,
        f"""
        WITH latest_pickup AS (
            SELECT DISTINCT ON (shipment_id)
                pickup_id,
                shipment_id,
                customer_id,
                customer_name,
                pickup_date,
                pickup_time_window,
                pickup_address,
                assigned_staff,
                pickup_status,
                notes,
                driver_id,
                created_at,
                updated_at
            FROM {SCHEMA}.pickup_schedule
            ORDER BY
                shipment_id,
                updated_at DESC NULLS LAST,
                created_at DESC NULLS LAST
        )
        SELECT
            p.pickup_id,
            s.shipment_id,
            COALESCE(
                p.customer_id,
                s.customer_id
            ) AS customer_id,
            COALESCE(
                NULLIF(
                    BTRIM(
                        COALESCE(
                            p.customer_name,
                            ''
                        )
                    ),
                    ''
                ),
                s.customer_name
            ) AS customer_name,
            p.pickup_date,
            p.pickup_time_window,
            p.pickup_address,
            p.assigned_staff,
            COALESCE(
                NULLIF(
                    BTRIM(
                        COALESCE(
                            p.pickup_status,
                            ''
                        )
                    ),
                    ''
                ),
                'Pending Confirmation'
            ) AS pickup_status,
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
            s.origin_city,
            s.origin_state,
            s.destination_city,
            s.destination_country,
            s.service_type,
            s.shipment_mode,
            s.amount_charged,
            s.created_at
                AS request_created_at,
            CASE
                WHEN p.pickup_id IS NULL
                    THEN TRUE
                ELSE FALSE
            END AS pickup_record_missing
        FROM {SCHEMA}.shipments AS s
        LEFT JOIN latest_pickup AS p
            ON p.shipment_id = s.shipment_id
        LEFT JOIN {SCHEMA}.drivers AS d
            ON d.driver_id = p.driver_id
        ORDER BY
            CASE
                WHEN p.pickup_id IS NULL
                    THEN 0
                WHEN LOWER(
                    BTRIM(
                        COALESCE(
                            p.pickup_status,
                            ''
                        )
                    )
                ) IN (
                    'pending',
                    'pending confirmation',
                    'awaiting confirmation'
                )
                    THEN 1
                ELSE 2
            END,
            s.created_at DESC NULLS LAST,
            p.pickup_date ASC NULLS LAST,
            s.shipment_id DESC
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
    pickup_address: str,
    driver_id: str,
    status: str,
    dispatcher: str,
    notified: bool,
    notes: str,
) -> str:
    """
    Create or update a pickup and send a new assignment to the Driver Portal.

    A newly selected driver receives Pending Driver Acceptance. Reassignment
    closes the previous active assignment while preserving its history.
    """

    pickup_id = clean(
        record.get("pickup_id"),
        "",
    )

    shipment_id = clean(
        record.get("shipment_id"),
        "",
    )

    customer_id = clean(
        record.get("customer_id"),
        "",
    )

    customer_name = clean(
        record.get("customer_name"),
        "",
    )

    previous_driver_id = clean(
        record.get("driver_id"),
        "",
    )

    address = pickup_address.strip()

    if not shipment_id:
        raise RuntimeError(
            "The selected request is missing "
            "its Shipment ID."
        )

    if not customer_name:
        raise RuntimeError(
            "The selected request is missing "
            "the customer name."
        )

    if not address:
        raise RuntimeError(
            "Enter the pickup address before saving."
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

    updated_notes = add_note(
        record.get("notes"),
        entry,
    )

    with engine.begin() as connection:
        if driver_id:
            conflict = connection.execute(
                text(
                    f"""
                    SELECT
                        pickup_id,
                        shipment_id
                    FROM {SCHEMA}.pickup_schedule
                    WHERE
                        driver_id = :driver_id
                        AND pickup_date = :pickup_date
                        AND pickup_time_window =
                            :pickup_time_window
                        AND LOWER(
                            BTRIM(
                                COALESCE(
                                    pickup_status,
                                    ''
                                )
                            )
                        ) NOT IN (
                            'cancelled',
                            'completed',
                            'picked up',
                            'no show',
                            'driver declined — reassignment needed'
                        )
                        AND (
                            :pickup_id = ''
                            OR pickup_id <> :pickup_id
                        )
                    LIMIT 1;
                    """
                ),
                {
                    "driver_id": driver_id,
                    "pickup_date": selected_date,
                    "pickup_time_window": window,
                    "pickup_id": pickup_id,
                },
            ).mappings().first()

            if conflict is not None:
                raise RuntimeError(
                    "The selected driver already has a pickup "
                    "during this two-hour window. Choose another "
                    "driver or another time."
                )

        driver_changed = (
            previous_driver_id != driver_id
        )

        active_assignment = None

        if pickup_id and driver_id:
            active_assignment = connection.execute(
                text(
                    f"""
                    SELECT
                        assignment_id,
                        assignment_status
                    FROM {SCHEMA}.driver_assignments
                    WHERE
                        pickup_id = :pickup_id
                        AND driver_id = :driver_id
                        AND assignment_status IN (
                            'Pending Driver Acceptance',
                            'Driver Accepted',
                            'Driver En Route',
                            'Driver Delayed',
                            'Driver Arrived',
                            'Waiting for Customer'
                        )
                    ORDER BY assigned_date DESC
                    LIMIT 1;
                    """
                ),
                {
                    "pickup_id": pickup_id,
                    "driver_id": driver_id,
                },
            ).mappings().first()

        new_assignment_needed = bool(
            driver_id
            and (
                driver_changed
                or active_assignment is None
            )
        )

        effective_status = status

        if new_assignment_needed:
            effective_status = (
                "Pending Driver Acceptance"
            )

        elif (
            driver_id
            and active_assignment is not None
            and clean(
                active_assignment.get(
                    "assignment_status"
                ),
                "",
            )
            == "Pending Driver Acceptance"
        ):
            effective_status = (
                "Pending Driver Acceptance"
            )

        if pickup_id:
            updated = connection.execute(
                text(
                    f"""
                    UPDATE {SCHEMA}.pickup_schedule
                    SET
                        pickup_date = :pickup_date,
                        pickup_time_window =
                            :pickup_time_window,
                        pickup_address =
                            :pickup_address,
                        driver_id =
                            NULLIF(:driver_id, ''),
                        assigned_staff =
                            :assigned_staff,
                        pickup_status =
                            :pickup_status,
                        notes = :notes,
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE pickup_id = :pickup_id;
                    """
                ),
                {
                    "pickup_date": selected_date,
                    "pickup_time_window": window,
                    "pickup_address": address,
                    "driver_id": driver_id,
                    "assigned_staff": dispatcher,
                    "pickup_status": effective_status,
                    "notes": updated_notes,
                    "pickup_id": pickup_id,
                },
            ).rowcount

            if updated != 1:
                raise RuntimeError(
                    "The pickup record was not updated."
                )

        else:
            pickup_id = (
                "PICK-"
                + uuid4().hex[:20].upper()
            )

            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.pickup_schedule (
                        pickup_id,
                        shipment_id,
                        customer_id,
                        customer_name,
                        pickup_date,
                        pickup_time_window,
                        pickup_address,
                        assigned_staff,
                        pickup_status,
                        notes,
                        driver_id,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :pickup_id,
                        :shipment_id,
                        NULLIF(:customer_id, ''),
                        :customer_name,
                        :pickup_date,
                        :pickup_time_window,
                        :pickup_address,
                        :assigned_staff,
                        :pickup_status,
                        :notes,
                        NULLIF(:driver_id, ''),
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    );
                    """
                ),
                {
                    "pickup_id": pickup_id,
                    "shipment_id": shipment_id,
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "pickup_date": selected_date,
                    "pickup_time_window": window,
                    "pickup_address": address,
                    "assigned_staff": dispatcher,
                    "pickup_status": effective_status,
                    "notes": updated_notes,
                    "driver_id": driver_id,
                },
            )

            if driver_id:
                new_assignment_needed = True

        if previous_driver_id and previous_driver_id != driver_id:
            connection.execute(
                text(
                    f"""
                    UPDATE {SCHEMA}.driver_assignments
                    SET
                        assignment_status = 'Reassigned',
                        driver_notes = CASE
                            WHEN driver_notes IS NULL
                                 OR BTRIM(driver_notes) = ''
                                THEN :note
                            ELSE driver_notes
                                || E'\n\n'
                                || :note
                        END,
                        last_status_date =
                            CURRENT_TIMESTAMP,
                        completion_time = COALESCE(
                            completion_time,
                            CURRENT_TIMESTAMP
                        ),
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE
                        pickup_id = :pickup_id
                        AND assignment_status IN (
                            'Pending Driver Acceptance',
                            'Driver Accepted',
                            'Driver En Route',
                            'Driver Delayed',
                            'Driver Arrived',
                            'Waiting for Customer'
                        );
                    """
                ),
                {
                    "note": (
                        "Assignment changed by "
                        f"{dispatcher}."
                    ),
                    "pickup_id": pickup_id,
                },
            )

        elif previous_driver_id and not driver_id:
            connection.execute(
                text(
                    f"""
                    UPDATE {SCHEMA}.driver_assignments
                    SET
                        assignment_status =
                            'Assignment Removed',
                        driver_notes = CASE
                            WHEN driver_notes IS NULL
                                 OR BTRIM(driver_notes) = ''
                                THEN :note
                            ELSE driver_notes
                                || E'\n\n'
                                || :note
                        END,
                        last_status_date =
                            CURRENT_TIMESTAMP,
                        completion_time = COALESCE(
                            completion_time,
                            CURRENT_TIMESTAMP
                        ),
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE
                        pickup_id = :pickup_id
                        AND assignment_status IN (
                            'Pending Driver Acceptance',
                            'Driver Accepted',
                            'Driver En Route',
                            'Driver Delayed',
                            'Driver Arrived',
                            'Waiting for Customer'
                        );
                    """
                ),
                {
                    "note": (
                        "Driver removed by "
                        f"{dispatcher}."
                    ),
                    "pickup_id": pickup_id,
                },
            )

        if new_assignment_needed and driver_id:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.driver_assignments (
                        assignment_id,
                        pickup_id,
                        shipment_id,
                        driver_id,
                        assigned_by,
                        assigned_role,
                        assigned_date,
                        assignment_status,
                        driver_notes,
                        last_status_date,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :assignment_id,
                        :pickup_id,
                        :shipment_id,
                        :driver_id,
                        :assigned_by,
                        :assigned_role,
                        CURRENT_TIMESTAMP,
                        'Pending Driver Acceptance',
                        :driver_notes,
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    );
                    """
                ),
                {
                    "assignment_id": (
                        "ASSIGN-"
                        + uuid4().hex[:24].upper()
                    ),
                    "pickup_id": pickup_id,
                    "shipment_id": shipment_id,
                    "driver_id": driver_id,
                    "assigned_by": dispatcher,
                    "assigned_role": portal_role(),
                    "driver_notes": (
                        "New assignment sent to "
                        "the Driver Portal."
                    ),
                },
            )

        shipment_status = {
            "Pending Confirmation": (
                "Request Received"
            ),
            "Scheduled": "Pickup Scheduled",
            "Rescheduled": "Pickup Scheduled",
            "Pending Driver Acceptance": (
                "Driver Assigned — Awaiting Acceptance"
            ),
            "Driver Accepted": "Driver Accepted",
            "Driver En Route": "Driver En Route",
            "Driver Delayed — Traffic": (
                "Driver Delayed — Traffic"
            ),
            "Driver Arrived": "Driver Arrived",
            "Driver Waiting — No Answer": (
                "Driver Waiting — No Answer"
            ),
            "Driver Waiting for Customer": (
                "Driver Waiting for Customer"
            ),
            "Driver Declined — Reassignment Needed": (
                "Driver Reassignment Needed"
            ),
            "Customer Not Ready — Staff Review": (
                "Customer Not Ready — Staff Review"
            ),
            "Customer Requested Reschedule": (
                "Pickup Reschedule Requested"
            ),
            "Address Issue — Staff Review": (
                "Address Issue — Staff Review"
            ),
            "Unable to Access — Staff Review": (
                "Unable to Access — Staff Review"
            ),
            "Vehicle Issue — Reassignment Needed": (
                "Vehicle Issue — Reassignment Needed"
            ),
            "Pickup Issue — Staff Review": (
                "Pickup Issue — Staff Review"
            ),
            "Picked Up": "Picked Up",
            "Completed": "Picked Up",
            "Cancelled": "Cancelled",
            "No Show": "Pickup No Show",
        }.get(
            effective_status,
            "Pickup Scheduled",
        )

        current_status = connection.execute(
            text(
                f"""
                SELECT current_status
                FROM {SCHEMA}.shipments
                WHERE shipment_id = :shipment_id
                FOR UPDATE;
                """
            ),
            {
                "shipment_id": shipment_id
            },
        ).scalar_one_or_none()

        if current_status != shipment_status:
            connection.execute(
                text(
                    f"""
                    UPDATE {SCHEMA}.shipments
                    SET
                        current_status = :status,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE shipment_id = :shipment_id;
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

        if effective_status in {
            "Scheduled",
            "Rescheduled",
            "Pending Driver Acceptance",
            "Driver Accepted",
            "Driver En Route",
            "Driver Arrived",
        }:
            mark_milestone(
                connection,
                shipment_id,
                "PICKUP_SCHEDULED",
                dispatcher,
            )

        elif effective_status in {
            "Picked Up",
            "Completed",
        }:
            mark_milestone(
                connection,
                shipment_id,
                "PICKED_UP",
                dispatcher,
            )

    return pickup_id


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



def prepare_working_queue(
    pickups: pd.DataFrame,
) -> pd.DataFrame:
    """Add clean display fields and non-overlapping queue categories."""

    if pickups.empty:
        return pickups.copy()

    queue = pickups.copy()

    queue["queue_key"] = queue.apply(
        lambda row: (
            clean(
                row.get("pickup_id"),
                "",
            )
            or (
                "NEW::"
                + clean(
                    row.get("shipment_id"),
                    "",
                )
            )
        ),
        axis=1,
    )

    queue["record_type"] = queue[
        "pickup_record_missing"
    ].apply(
        lambda value: (
            "New Request"
            if bool(value)
            else "Pickup Record"
        )
    )

    queue["driver_display"] = (
        queue["driver_name"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Not Assigned")
    )

    queue["estimate_display"] = (
        pd.to_numeric(
            queue["amount_charged"],
            errors="coerce",
        )
        .fillna(0)
        .map(
            lambda value: f"${value:,.2f}"
        )
    )

    queue["pickup_status_normalized"] = (
        queue["pickup_status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    queue["shipment_status_normalized"] = (
        queue["shipment_status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    queue["assigned_staff_normalized"] = (
        queue["assigned_staff"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    queue["is_new_request"] = (
        queue["shipment_status_normalized"].eq(
            "request received"
        )
        & queue["pickup_status_normalized"].isin(
            NEW_PICKUP_STATUSES
        )
        & queue["assigned_staff_normalized"].eq("")
    )

    queue["is_scheduled_active"] = (
        queue["pickup_status_normalized"].isin(
            SCHEDULED_PICKUP_STATUSES
        )
    )

    queue["is_closed"] = (
        queue["pickup_status_normalized"].isin(
            CLOSED_PICKUP_STATUSES
        )
    )

    queue["is_pending"] = ~(
        queue["is_new_request"]
        | queue["is_scheduled_active"]
        | queue["is_closed"]
    )

    return queue


def queue_display_frame(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Create a compact, readable pickup table."""

    if frame.empty:
        return pd.DataFrame()

    display = frame.copy()

    for column in [
        "pickup_date",
        "request_created_at",
    ]:
        if column in display.columns:
            display[column] = pd.to_datetime(
                display[column],
                errors="coerce",
            ).dt.strftime("%b %d, %Y")

    selected_columns = [
        "record_type",
        "shipment_id",
        "pickup_id",
        "customer_name",
        "pickup_date",
        "pickup_time_window",
        "pickup_address",
        "estimate_display",
        "driver_display",
        "pickup_status",
        "shipment_status",
    ]

    return display[
        [
            column
            for column in selected_columns
            if column in display.columns
        ]
    ].rename(
        columns={
            "record_type": "Record",
            "shipment_id": "Shipment ID",
            "pickup_id": "Pickup ID",
            "customer_name": "Customer",
            "pickup_date": "Pickup Date",
            "pickup_time_window": "Two-Hour Window",
            "pickup_address": "Pickup Address",
            "estimate_display": "Estimate",
            "driver_display": "Driver",
            "pickup_status": "Pickup Status",
            "shipment_status": "Shipment Status",
        }
    )


def render_queue_download(
    display: pd.DataFrame,
    label: str,
    filename: str,
    key: str,
) -> None:
    """Render a compact CSV download button for one queue."""

    if display.empty:
        return

    left, right = st.columns(
        [4.7, 1.3]
    )

    with left:
        st.caption(
            f"{len(display)} record"
            f"{'s' if len(display) != 1 else ''}"
        )

    with right:
        st.download_button(
            label=label,
            data=display.to_csv(
                index=False
            ).encode("utf-8"),
            file_name=filename,
            mime="text/csv",
            key=key,
            use_container_width=True,
        )


def render_pickup_management_form(
    *,
    frame: pd.DataFrame,
    key_prefix: str,
    engine: Engine,
    all_pickups: pd.DataFrame,
    drivers: pd.DataFrame,
    capacity: pd.DataFrame,
    role: str,
) -> None:
    """Let staff schedule or update one record from the active queue tab."""

    if frame.empty:
        return

    queue_keys = (
        frame["queue_key"]
        .astype(str)
        .tolist()
    )

    record_lookup = {
        str(row["queue_key"]): row
        for _, row in frame.iterrows()
    }

    def queue_label(
        value: str,
    ) -> str:
        row = record_lookup[value]

        return (
            f"{clean(row.get('shipment_id'))}"
            f" — {clean(row.get('customer_name'))}"
            f" — {clean(row.get('pickup_status'))}"
        )

    selected_key = st.selectbox(
        "Select a request to schedule or update",
        queue_keys,
        format_func=queue_label,
        key=f"{key_prefix}_selected_request",
    )

    record = (
        record_lookup[selected_key]
        .to_dict()
    )

    current_status = clean(
        record.get("pickup_status"),
        "Pending Confirmation",
    )

    current_window = clean(
        record.get("pickup_time_window"),
        PICKUP_WINDOWS[0],
    )

    current_date = as_date(
        record.get("pickup_date")
    )

    current_area = pickup_area(
        record.get("notes")
    )

    areas = area_choices(
        all_pickups,
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

    if bool(
        record.get(
            "pickup_record_missing"
        )
    ):
        st.info(
            "This shipment request does not yet have a "
            "pickup_schedule record. Saving below will "
            "create it automatically."
        )

    if (
        current_window
        and current_window not in PICKUP_WINDOWS
    ):
        st.warning(
            f"The customer originally selected “{current_window}.” "
            "Choose an exact two-hour window before confirming."
        )

    with st.expander(
        "Schedule or update this pickup",
        expanded=False,
    ):
        with st.form(
            f"{key_prefix}_pickup_update_form"
        ):
            left, right = st.columns(2)

            with left:
                selected_date = st.date_input(
                    "Confirmed Pickup Date",
                    value=current_date,
                )

                selected_window = st.selectbox(
                    "Confirmed Two-Hour Window",
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

                selected_area = st.selectbox(
                    "Pickup Area",
                    areas,
                    index=areas.index(
                        current_area
                    ),
                )

                pickup_address_value = (
                    st.text_area(
                        "Pickup Address",
                        value=clean(
                            record.get(
                                "pickup_address"
                            ),
                            "",
                        ),
                        height=95,
                        placeholder=(
                            "Enter the complete pickup address"
                        ),
                    )
                )

            with right:
                selected_driver = st.selectbox(
                    "Assign Driver — Driver Must Accept",
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
                            driver_labels[value]
                        )
                    ),
                )

                selected_status = st.selectbox(
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

                dispatcher = st.text_input(
                    "Updated By / Dispatcher",
                    value=role,
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

            save_left, save_center, save_right = (
                st.columns([2.1, 1.8, 2.1])
            )

            with save_center:
                submitted = (
                    st.form_submit_button(
                        "Save Pickup Update",
                        use_container_width=True,
                        type="primary",
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
                saved_pickup_id = save_pickup(
                    engine,
                    record,
                    selected_date,
                    selected_window,
                    selected_area,
                    pickup_address_value,
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
                    "Pickup update saved to Neon. "
                    f"Pickup ID: {saved_pickup_id}. "
                    "A newly assigned driver will see it "
                    "in the Driver Portal for acceptance."
                )

                st.rerun()

            except Exception as exc:
                st.error(
                    "The pickup update could not be saved."
                )

                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error(exc)}"
                )


def render_queue_tab(
    *,
    title: str,
    description: str,
    frame: pd.DataFrame,
    key_prefix: str,
    csv_filename: str,
    engine: Engine,
    all_pickups: pd.DataFrame,
    drivers: pd.DataFrame,
    capacity: pd.DataFrame,
    role: str,
) -> None:
    """Render one uncluttered queue table with its own CSV download."""

    st.markdown(f"### {title}")
    st.caption(description)

    if frame.empty:
        st.info(
            f"No records are currently in {title.lower()}."
        )
        return

    search_value = st.text_input(
        "Search this table",
        key=f"{key_prefix}_search",
        placeholder=(
            "Shipment ID, customer, address, driver, or status"
        ),
    )

    filtered = frame.copy()

    if search_value.strip():
        search_columns = [
            "pickup_id",
            "shipment_id",
            "customer_name",
            "pickup_address",
            "pickup_status",
            "shipment_status",
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

    display = queue_display_frame(
        filtered
    )

    if display.empty:
        st.info(
            "No records match this search."
        )
        return

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        height=min(
            520,
            85 + (len(display) * 35),
        ),
    )

    render_queue_download(
        display,
        label="Download CSV",
        filename=csv_filename,
        key=f"{key_prefix}_csv",
    )

    render_pickup_management_form(
        frame=filtered,
        key_prefix=key_prefix,
        engine=engine,
        all_pickups=all_pickups,
        drivers=drivers,
        capacity=capacity,
        role=role,
    )



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
                "Shipment Requests",
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

    working_queue = prepare_working_queue(
        pickups
    )

    new_requests = working_queue[
        working_queue["is_new_request"]
    ].copy()

    pending_requests = working_queue[
        working_queue["is_pending"]
    ].copy()

    scheduled_active = working_queue[
        working_queue["is_scheduled_active"]
    ].copy()

    completed_closed = working_queue[
        working_queue["is_closed"]
    ].copy()

    st.subheader(
        "Pickup Request Queues"
    )

    queue_metrics = st.columns(4)

    metric_values = [
        (
            "New Requests",
            len(new_requests),
        ),
        (
            "Pending",
            len(pending_requests),
        ),
        (
            "Scheduled / Active",
            len(scheduled_active),
        ),
        (
            "Completed / Closed",
            len(completed_closed),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        queue_metrics,
        metric_values,
    ):
        with column:
            st.metric(
                label,
                value,
            )

    tabs = st.tabs(
        [
            "New Requests",
            "Pending",
            "Scheduled & Active",
            "Completed / Closed",
            "Dispatch Tools",
        ]
    )

    with tabs[0]:
        render_queue_tab(
            title="New Requests",
            description=(
                "Fresh customer shipment requests that have not "
                "yet been reviewed or assigned by staff."
            ),
            frame=new_requests,
            key_prefix="new_requests",
            csv_filename="new_pickup_requests.csv",
            engine=engine,
            all_pickups=pickups,
            drivers=drivers,
            capacity=capacity,
            role=role,
        )

    with tabs[1]:
        render_queue_tab(
            title="Pending Pickups",
            description=(
                "Requests under review or awaiting a confirmed "
                "date, two-hour window, driver, or customer contact."
            ),
            frame=pending_requests,
            key_prefix="pending_pickups",
            csv_filename="pending_pickups.csv",
            engine=engine,
            all_pickups=pickups,
            drivers=drivers,
            capacity=capacity,
            role=role,
        )

    with tabs[2]:
        render_queue_tab(
            title="Scheduled and Active Pickups",
            description=(
                "Confirmed, assigned, rescheduled, en-route, "
                "and arrived pickups."
            ),
            frame=scheduled_active,
            key_prefix="scheduled_pickups",
            csv_filename="scheduled_active_pickups.csv",
            engine=engine,
            all_pickups=pickups,
            drivers=drivers,
            capacity=capacity,
            role=role,
        )

    with tabs[3]:
        render_queue_tab(
            title="Completed and Closed Pickups",
            description=(
                "Picked up, completed, cancelled, and no-show records."
            ),
            frame=completed_closed,
            key_prefix="completed_pickups",
            csv_filename="completed_closed_pickups.csv",
            engine=engine,
            all_pickups=pickups,
            drivers=drivers,
            capacity=capacity,
            role=role,
        )

    with tabs[4]:
        dispatch_tabs = st.tabs(
            [
                "Capacity Board",
                "Driver Directory",
                "Customer Changes",
            ]
        )

        with dispatch_tabs[0]:
            st.subheader(
                "Pickup Capacity Board"
            )

            st.caption(
                "Capacity should be maintained by date and area. "
                "Separate area capacity allows Queens and Brooklyn "
                "pickups to use the same time when different drivers "
                "are available."
            )

            if capacity.empty:
                st.info(
                    "No pickup-capacity records are stored in Neon."
                )

            else:
                st.dataframe(
                    capacity,
                    use_container_width=True,
                    hide_index=True,
                )

                st.download_button(
                    "Download Capacity CSV",
                    data=capacity.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="pickup_capacity.csv",
                    mime="text/csv",
                    key="capacity_csv",
                )

        with dispatch_tabs[1]:
            st.subheader(
                "Driver Directory"
            )

            st.caption(
                "Each driver should have a primary area, service areas, "
                "vehicle information, and active status. Driver assignment "
                "is checked to prevent overlapping two-hour pickups."
            )

            if drivers.empty:
                st.info(
                    "No driver records are stored in Neon."
                )

            else:
                st.dataframe(
                    drivers,
                    use_container_width=True,
                    hide_index=True,
                )

                st.download_button(
                    "Download Driver CSV",
                    data=drivers.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="driver_directory.csv",
                    mime="text/csv",
                    key="drivers_csv",
                )

        with dispatch_tabs[2]:
            st.subheader(
                "Customer Change Requests for Review"
            )

            if pending_changes.empty:
                st.success(
                    "There are no pending customer change requests."
                )

            else:
                st.dataframe(
                    pending_changes,
                    use_container_width=True,
                    hide_index=True,
                )

                change_id = st.selectbox(
                    "Select Change Request",
                    pending_changes[
                        "change_id"
                    ].astype(str).tolist(),
                )

                change = pending_changes[
                    pending_changes[
                        "change_id"
                    ].astype(str).eq(
                        change_id
                    )
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

                    review_notes = st.text_area(
                        "Review Notes",
                        height=110,
                    )

                    review_submitted = (
                        st.form_submit_button(
                            "Save Review Decision",
                            use_container_width=True,
                        )
                    )

                if review_submitted:
                    try:
                        saved_status = review_change(
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

                        st.success(
                            "Review saved. Status: "
                            f"{saved_status}."
                        )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            "The review decision could not be saved."
                        )

                        st.caption(
                            "Technical details: "
                            f"{type(exc).__name__}: "
                            f"{safe_error(exc)}"
                        )


if __name__ == "__main__":
    main()