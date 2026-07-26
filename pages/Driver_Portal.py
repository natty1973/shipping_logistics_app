from __future__ import annotations

import os
import re
from datetime import date
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

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
    page_title="Driver Portal",
    page_icon="🚚",
    layout="wide",
)

SCHEMA = "solomon_shipping"

PENDING_STATUSES = {
    "Pending Driver Acceptance",
}

ACTIVE_STATUSES = {
    "Driver Accepted",
    "Driver En Route",
    "Driver Delayed",
    "Driver Arrived",
    "Waiting for Customer",
}

HISTORY_STATUSES = {
    "Completed",
    "Driver Declined",
    "Customer Requested Reschedule",
    "Customer Not Ready",
    "Address Issue",
    "Unable to Access",
    "Vehicle Issue",
    "Unable to Complete",
    "Reassigned",
    "Assignment Removed",
    "Cancelled",
}


def secret(name: str) -> str:
    """Read a database setting from the environment or Streamlit Secrets."""

    environment_value = os.getenv(name, "").strip()

    if environment_value:
        return environment_value

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
def db_engine() -> Engine:
    """Create a reusable Neon/PostgreSQL connection."""

    database_url = secret("DATABASE_URL")

    if database_url:
        if database_url.startswith("postgres://"):
            database_url = (
                "postgresql://"
                + database_url[len("postgres://"):]
            )

        target: str | URL = database_url

    else:
        settings = {
            "user": secret("DB_USER"),
            "password": secret("DB_PASSWORD"),
            "host": secret("DB_HOST"),
            "port": secret("DB_PORT") or "5432",
            "database": secret("DB_NAME"),
            "sslmode": secret("DB_SSLMODE") or "require",
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

        target = URL.create(
            drivername="postgresql+psycopg2",
            username=settings["user"],
            password=settings["password"],
            host=settings["host"],
            port=port,
            database=settings["database"],
            query={
                "sslmode": settings["sslmode"]
            },
        )

    engine = create_engine(
        target,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 15,
            "application_name": (
                "solomon_shipping_driver_portal"
            ),
        },
    )

    with engine.connect() as connection:
        connection.execute(
            text("SELECT 1;")
        )

    return engine


def safe_error(
    error: Exception,
) -> str:
    """Remove credentials from database error messages."""

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
    """Return a clean display string."""

    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    text_value = str(value).strip()

    return text_value or default


def verify_access() -> tuple[str, str]:
    """Confirm the current session belongs to an authenticated driver."""

    is_driver = (
        st.session_state.get("portal_mode")
        == "driver"
    )

    authenticated = bool(
        st.session_state.get(
            "driver_authenticated",
            False,
        )
    )

    driver_id = clean(
        st.session_state.get("driver_id"),
        "",
    )

    driver_name = clean(
        st.session_state.get("driver_name"),
        "",
    )

    if (
        not is_driver
        or not authenticated
        or not driver_id
    ):
        st.error(
            "Driver access is required to open this page."
        )
        st.info(
            "Return to Portal Selection and sign in "
            "with the Driver Portal username and password."
        )
        st.stop()

    return driver_id, driver_name


def verify_tables(
    engine: Engine,
) -> None:
    """Confirm the tables required by the Driver Portal exist."""

    required_tables = [
        "drivers",
        "driver_assignments",
        "pickup_schedule",
        "shipments",
        "customers",
        "status_history",
        "pickup_messages",
    ]

    missing: list[str] = []

    with engine.connect() as connection:
        for table_name in required_tables:
            relation_name = (
                f"{SCHEMA}.{table_name}"
            )

            exists = connection.execute(
                text(
                    "SELECT TO_REGCLASS(:relation_name);"
                ),
                {
                    "relation_name": relation_name
                },
            ).scalar_one_or_none()

            if exists is None:
                missing.append(relation_name)

    if missing:
        raise RuntimeError(
            "Required Driver Portal tables are missing: "
            + ", ".join(missing)
        )


def load_driver_profile(
    engine: Engine,
    driver_id: str,
) -> dict[str, Any]:
    """Load the signed-in driver's active profile."""

    with engine.connect() as connection:
        profile = connection.execute(
            text(
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
                WHERE driver_id = :driver_id
                LIMIT 1;
                """
            ),
            {
                "driver_id": driver_id
            },
        ).mappings().first()

    if profile is None:
        raise RuntimeError(
            "The signed-in driver record "
            "could not be found."
        )

    return dict(profile)


def load_assignments(
    engine: Engine,
    driver_id: str,
) -> pd.DataFrame:
    """Load every assignment belonging to the signed-in driver."""

    query = text(
        f"""
        SELECT
            a.assignment_id,
            a.pickup_id,
            a.shipment_id,
            a.driver_id,
            a.assigned_by,
            a.assigned_role,
            a.assigned_date,
            a.assignment_status,
            a.accepted_date,
            a.declined_date,
            a.decline_reason,
            a.en_route_time,
            a.arrival_time,
            a.picked_up_time,
            a.completion_time,
            a.driver_notes,
            a.last_status_date,
            a.created_at,
            a.updated_at,

            p.pickup_date,
            p.pickup_time_window,
            p.pickup_address,
            p.pickup_status,
            p.notes AS pickup_notes,
            p.assigned_staff,

            s.customer_id,
            s.customer_name,
            s.item_type,
            s.quantity,
            s.service_type,
            s.shipment_mode,
            s.destination_city,
            s.destination_country,
            s.current_status AS shipment_status,
            s.notes AS shipment_notes,

            c.phone AS customer_phone,
            c.email AS customer_email
        FROM {SCHEMA}.driver_assignments AS a
        JOIN {SCHEMA}.pickup_schedule AS p
            ON p.pickup_id = a.pickup_id
        JOIN {SCHEMA}.shipments AS s
            ON s.shipment_id = a.shipment_id
        LEFT JOIN {SCHEMA}.customers AS c
            ON c.customer_id = s.customer_id
        WHERE a.driver_id = :driver_id
        ORDER BY
            CASE
                WHEN a.assignment_status =
                    'Pending Driver Acceptance'
                    THEN 1
                WHEN a.assignment_status IN (
                    'Driver Accepted',
                    'Driver En Route',
                    'Driver Arrived'
                )
                    THEN 2
                ELSE 3
            END,
            p.pickup_date ASC NULLS LAST,
            p.pickup_time_window ASC NULLS LAST,
            a.assigned_date DESC;
        """
    )

    with engine.connect() as connection:
        frame = pd.read_sql_query(
            query,
            connection,
            params={
                "driver_id": driver_id
            },
        )

    return frame


def load_pickup_messages(
    engine: Engine,
    pickup_id: str,
) -> pd.DataFrame:
    """Load the driver/customer conversation for one pickup."""

    query = text(
        f"""
        SELECT
            message_id,
            shipment_id,
            pickup_id,
            sender_role,
            sender_id,
            sender_name,
            recipient_role,
            message_type,
            message_text,
            created_at,
            read_at
        FROM {SCHEMA}.pickup_messages
        WHERE pickup_id = :pickup_id
        ORDER BY created_at ASC, message_id ASC;
        """
    )

    with engine.connect() as connection:
        return pd.read_sql_query(
            query,
            connection,
            params={
                "pickup_id": pickup_id
            },
        )


def insert_pickup_message(
    connection: Any,
    *,
    shipment_id: str,
    pickup_id: str,
    sender_role: str,
    sender_id: str,
    sender_name: str,
    recipient_role: str,
    message_type: str,
    message_text: str,
) -> str:
    """Insert one message using an existing database transaction."""

    clean_message = message_text.strip()

    if not clean_message:
        raise RuntimeError(
            "The message cannot be blank."
        )

    message_id = (
        "MSG-"
        + uuid4().hex[:24].upper()
    )

    connection.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.pickup_messages (
                message_id,
                shipment_id,
                pickup_id,
                sender_role,
                sender_id,
                sender_name,
                recipient_role,
                message_type,
                message_text,
                created_at
            )
            VALUES (
                :message_id,
                :shipment_id,
                :pickup_id,
                :sender_role,
                NULLIF(:sender_id, ''),
                :sender_name,
                :recipient_role,
                :message_type,
                :message_text,
                CURRENT_TIMESTAMP
            );
            """
        ),
        {
            "message_id": message_id,
            "shipment_id": shipment_id,
            "pickup_id": pickup_id,
            "sender_role": sender_role,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "recipient_role": recipient_role,
            "message_type": message_type,
            "message_text": clean_message,
        },
    )

    return message_id


def send_driver_message(
    engine: Engine,
    *,
    shipment_id: str,
    pickup_id: str,
    driver_id: str,
    driver_name: str,
    message_text: str,
    message_type: str = "Driver Message",
) -> str:
    """
    Send an in-app message to the customer and preserve it in status history.

    The same pickup_messages table can be used by the Customer Portal for
    replies, creating a true two-way conversation without exposing financial
    information to the driver.
    """

    with engine.begin() as connection:
        message_id = insert_pickup_message(
            connection,
            shipment_id=shipment_id,
            pickup_id=pickup_id,
            sender_role="Driver",
            sender_id=driver_id,
            sender_name=driver_name or driver_id,
            recipient_role="Customer",
            message_type=message_type,
            message_text=message_text,
        )

        add_status_history(
            connection,
            shipment_id,
            "Driver Message",
            driver_name or driver_id,
            message_text.strip(),
        )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.pickup_schedule
                SET
                    notes = CASE
                        WHEN notes IS NULL
                             OR BTRIM(notes) = ''
                            THEN :note
                        ELSE notes
                            || E'\n\n'
                            || :note
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE pickup_id = :pickup_id;
                """
            ),
            {
                "note": (
                    "[Driver message to customer] "
                    + message_text.strip()
                ),
                "pickup_id": pickup_id,
            },
        )

    return message_id




def add_status_history(
    connection: Any,
    shipment_id: str,
    status: str,
    updated_by: str,
    notes: str,
) -> None:
    """Write a customer-visible shipment status event."""

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
            );
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


def mark_picked_up_milestone(
    connection: Any,
    shipment_id: str,
    updated_by: str,
) -> None:
    """Mark the optional picked-up milestone when that table exists."""

    exists = connection.execute(
        text(
            "SELECT TO_REGCLASS("
            "'solomon_shipping.shipment_milestones'"
            ");"
        )
    ).scalar_one_or_none()

    if exists is None:
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
                AND milestone_code = 'PICKED_UP';
            """
        ),
        {
            "shipment_id": shipment_id,
            "updated_by": updated_by,
        },
    )


def update_assignment(
    engine: Engine,
    *,
    assignment_id: str,
    driver_id: str,
    driver_name: str,
    action: str,
    notes: str = "",
    decline_reason: str = "",
) -> str:
    """
    Apply one detailed driver action transactionally.

    Driver actions update driver_assignments, pickup_schedule, shipments,
    status_history, and the customer message thread together so Driver, Staff,
    Owner, and Customer views remain aligned.
    """

    action_map = {
        "Accept Assignment": {
            "allowed": {
                "Pending Driver Acceptance"
            },
            "assignment_status": "Driver Accepted",
            "pickup_status": "Driver Accepted",
            "shipment_status": "Driver Accepted",
            "timestamp_column": "accepted_date",
            "release_driver": False,
            "customer_message": (
                "Your driver accepted the pickup assignment."
            ),
        },
        "Decline Assignment": {
            "allowed": {
                "Pending Driver Acceptance"
            },
            "assignment_status": "Driver Declined",
            "pickup_status": (
                "Driver Declined — Reassignment Needed"
            ),
            "shipment_status": (
                "Driver Reassignment Needed"
            ),
            "timestamp_column": "declined_date",
            "release_driver": True,
            "customer_message": (
                "Solomon Shipping is reassigning your pickup driver."
            ),
        },
        "Start Route": {
            "allowed": {
                "Driver Accepted",
                "Driver Delayed",
            },
            "assignment_status": "Driver En Route",
            "pickup_status": "Driver En Route",
            "shipment_status": "Driver En Route",
            "timestamp_column": "en_route_time",
            "release_driver": False,
            "customer_message": (
                "Your Solomon Shipping driver is on the way."
            ),
        },
        "Traffic Delay": {
            "allowed": {
                "Driver En Route",
                "Driver Delayed",
            },
            "assignment_status": "Driver Delayed",
            "pickup_status": "Driver Delayed — Traffic",
            "shipment_status": "Driver Delayed — Traffic",
            "timestamp_column": None,
            "release_driver": False,
            "customer_message": (
                "Your driver is delayed by traffic but is still on the way."
            ),
        },
        "Mark Arrived": {
            "allowed": {
                "Driver En Route",
                "Driver Delayed",
            },
            "assignment_status": "Driver Arrived",
            "pickup_status": "Driver Arrived",
            "shipment_status": "Driver Arrived",
            "timestamp_column": "arrival_time",
            "release_driver": False,
            "customer_message": (
                "Your Solomon Shipping driver has arrived."
            ),
        },
        "Ring Bell — No Answer": {
            "allowed": {
                "Driver Arrived",
                "Waiting for Customer",
            },
            "assignment_status": "Waiting for Customer",
            "pickup_status": "Driver Waiting — No Answer",
            "shipment_status": "Driver Waiting — No Answer",
            "timestamp_column": None,
            "release_driver": False,
            "customer_message": (
                "Your driver arrived and rang the bell, "
                "but did not receive an answer. Please contact the driver."
            ),
        },
        "Customer Contacted — Waiting": {
            "allowed": {
                "Driver Arrived",
                "Waiting for Customer",
            },
            "assignment_status": "Waiting for Customer",
            "pickup_status": "Driver Waiting for Customer",
            "shipment_status": "Driver Waiting for Customer",
            "timestamp_column": None,
            "release_driver": False,
            "customer_message": (
                "Your driver is at the pickup location and waiting."
            ),
        },
        "Confirm Picked Up": {
            "allowed": {
                "Driver Arrived",
                "Waiting for Customer",
            },
            "assignment_status": "Completed",
            "pickup_status": "Picked Up",
            "shipment_status": "Picked Up",
            "timestamp_column": "picked_up_time",
            "release_driver": False,
            "customer_message": (
                "Your shipment was picked up successfully."
            ),
        },
        "Customer Not Ready": {
            "allowed": {
                "Driver Arrived",
                "Waiting for Customer",
            },
            "assignment_status": "Customer Not Ready",
            "pickup_status": (
                "Customer Not Ready — Staff Review"
            ),
            "shipment_status": (
                "Customer Not Ready — Staff Review"
            ),
            "timestamp_column": "completion_time",
            "release_driver": True,
            "customer_message": (
                "The shipment was not ready for pickup. "
                "Solomon Shipping staff will follow up."
            ),
        },
        "Customer Requested Reschedule": {
            "allowed": {
                "Driver Accepted",
                "Driver En Route",
                "Driver Delayed",
                "Driver Arrived",
                "Waiting for Customer",
            },
            "assignment_status": (
                "Customer Requested Reschedule"
            ),
            "pickup_status": (
                "Customer Requested Reschedule"
            ),
            "shipment_status": (
                "Pickup Reschedule Requested"
            ),
            "timestamp_column": "completion_time",
            "release_driver": True,
            "customer_message": (
                "A pickup reschedule was requested. "
                "Solomon Shipping staff will confirm a new time."
            ),
        },
        "Address Problem": {
            "allowed": {
                "Driver En Route",
                "Driver Delayed",
                "Driver Arrived",
            },
            "assignment_status": "Address Issue",
            "pickup_status": (
                "Address Issue — Staff Review"
            ),
            "shipment_status": (
                "Address Issue — Staff Review"
            ),
            "timestamp_column": "completion_time",
            "release_driver": True,
            "customer_message": (
                "The driver reported a pickup-address issue. "
                "Solomon Shipping staff will follow up."
            ),
        },
        "Unable to Access Property": {
            "allowed": {
                "Driver Arrived",
                "Waiting for Customer",
            },
            "assignment_status": "Unable to Access",
            "pickup_status": (
                "Unable to Access — Staff Review"
            ),
            "shipment_status": (
                "Unable to Access — Staff Review"
            ),
            "timestamp_column": "completion_time",
            "release_driver": True,
            "customer_message": (
                "The driver could not access the pickup location. "
                "Solomon Shipping staff will follow up."
            ),
        },
        "Vehicle Problem": {
            "allowed": {
                "Driver Accepted",
                "Driver En Route",
                "Driver Delayed",
                "Driver Arrived",
            },
            "assignment_status": "Vehicle Issue",
            "pickup_status": (
                "Vehicle Issue — Reassignment Needed"
            ),
            "shipment_status": (
                "Vehicle Issue — Reassignment Needed"
            ),
            "timestamp_column": "completion_time",
            "release_driver": True,
            "customer_message": (
                "A vehicle issue affected this pickup. "
                "Solomon Shipping is reviewing the assignment."
            ),
        },
        "Unable to Complete": {
            "allowed": {
                "Driver Accepted",
                "Driver En Route",
                "Driver Delayed",
                "Driver Arrived",
                "Waiting for Customer",
            },
            "assignment_status": "Unable to Complete",
            "pickup_status": (
                "Pickup Issue — Staff Review"
            ),
            "shipment_status": (
                "Pickup Issue — Staff Review"
            ),
            "timestamp_column": "completion_time",
            "release_driver": True,
            "customer_message": (
                "The pickup could not be completed. "
                "Solomon Shipping staff will follow up."
            ),
        },
    }

    if action not in action_map:
        raise RuntimeError(
            "The selected driver action is not supported."
        )

    settings = action_map[action]

    issue_actions = {
        "Decline Assignment",
        "Customer Not Ready",
        "Customer Requested Reschedule",
        "Address Problem",
        "Unable to Access Property",
        "Vehicle Problem",
        "Unable to Complete",
    }

    issue_detail = (
        decline_reason.strip()
        if action == "Decline Assignment"
        else notes.strip()
    )

    if (
        action in issue_actions
        and not issue_detail
    ):
        raise RuntimeError(
            "Enter a short reason or note for this update."
        )

    with engine.begin() as connection:
        assignment = connection.execute(
            text(
                f"""
                SELECT
                    assignment_id,
                    pickup_id,
                    shipment_id,
                    driver_id,
                    assignment_status,
                    driver_notes
                FROM {SCHEMA}.driver_assignments
                WHERE assignment_id = :assignment_id
                FOR UPDATE;
                """
            ),
            {
                "assignment_id": assignment_id
            },
        ).mappings().first()

        if assignment is None:
            raise RuntimeError(
                "This assignment no longer exists."
            )

        if (
            clean(
                assignment.get("driver_id"),
                "",
            )
            != driver_id
        ):
            raise RuntimeError(
                "This assignment belongs to another driver."
            )

        current_status = clean(
            assignment.get(
                "assignment_status"
            ),
            "",
        )

        if current_status not in settings["allowed"]:
            raise RuntimeError(
                "This assignment has already changed. "
                "Refresh the Driver Portal."
            )

        pickup_id = clean(
            assignment.get("pickup_id"),
            "",
        )

        shipment_id = clean(
            assignment.get("shipment_id"),
            "",
        )

        note_entry = (
            f"[Driver update] {action}"
        )

        if issue_detail:
            note_entry += (
                "\nDetails: "
                + issue_detail
            )

        elif notes.strip():
            note_entry += (
                "\nDriver notes: "
                + notes.strip()
            )

        existing_notes = clean(
            assignment.get("driver_notes"),
            "",
        )

        updated_notes = (
            f"{existing_notes}\n\n{note_entry}"
            if existing_notes
            else note_entry
        )

        timestamp_column = settings[
            "timestamp_column"
        ]

        timestamp_sql = ""

        if timestamp_column:
            timestamp_sql = (
                f", {timestamp_column} = "
                f"COALESCE({timestamp_column}, CURRENT_TIMESTAMP)"
            )

        close_assignment = (
            settings["assignment_status"]
            not in ACTIVE_STATUSES
            and settings["assignment_status"]
            not in PENDING_STATUSES
        )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.driver_assignments
                SET
                    assignment_status =
                        :assignment_status
                    {timestamp_sql},
                    decline_reason = CASE
                        WHEN :is_decline
                            THEN :decline_reason
                        ELSE decline_reason
                    END,
                    driver_notes = :driver_notes,
                    last_status_date =
                        CURRENT_TIMESTAMP,
                    completion_time = CASE
                        WHEN :close_assignment
                            THEN COALESCE(
                                completion_time,
                                CURRENT_TIMESTAMP
                            )
                        ELSE completion_time
                    END,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE assignment_id =
                    :assignment_id;
                """
            ),
            {
                "assignment_status": settings[
                    "assignment_status"
                ],
                "is_decline": (
                    action == "Decline Assignment"
                ),
                "decline_reason": (
                    decline_reason.strip()
                    if action
                    == "Decline Assignment"
                    else None
                ),
                "driver_notes": updated_notes,
                "close_assignment": close_assignment,
                "assignment_id": assignment_id,
            },
        )

        pickup_driver_sql = (
            "driver_id = NULL,"
            if settings["release_driver"]
            else ""
        )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.pickup_schedule
                SET
                    {pickup_driver_sql}
                    pickup_status =
                        :pickup_status,
                    notes = CASE
                        WHEN notes IS NULL
                             OR BTRIM(notes) = ''
                            THEN :pickup_note
                        ELSE notes
                            || E'\n\n'
                            || :pickup_note
                    END,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE
                    pickup_id = :pickup_id
                    AND (
                        driver_id = :driver_id
                        OR :release_driver
                    );
                """
            ),
            {
                "pickup_status": settings[
                    "pickup_status"
                ],
                "pickup_note": note_entry,
                "pickup_id": pickup_id,
                "driver_id": driver_id,
                "release_driver": settings[
                    "release_driver"
                ],
            },
        )

        connection.execute(
            text(
                f"""
                UPDATE {SCHEMA}.shipments
                SET
                    current_status =
                        :shipment_status,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE shipment_id =
                    :shipment_id;
                """
            ),
            {
                "shipment_status": settings[
                    "shipment_status"
                ],
                "shipment_id": shipment_id,
            },
        )

        add_status_history(
            connection,
            shipment_id,
            settings["shipment_status"],
            driver_name or driver_id,
            note_entry,
        )

        customer_message = settings[
            "customer_message"
        ]

        if issue_detail and action in issue_actions:
            customer_message += (
                "\nDetails: "
                + issue_detail
            )

        insert_pickup_message(
            connection,
            shipment_id=shipment_id,
            pickup_id=pickup_id,
            sender_role="Driver",
            sender_id=driver_id,
            sender_name=driver_name or driver_id,
            recipient_role="Customer",
            message_type="Status Update",
            message_text=customer_message,
        )

        if action == "Confirm Picked Up":
            mark_picked_up_milestone(
                connection,
                shipment_id,
                driver_name or driver_id,
            )

    return settings["assignment_status"]


def assignment_display(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Prepare a compact assignment table."""

    if frame.empty:
        return pd.DataFrame()

    display = frame.copy()

    for column in [
        "pickup_date",
        "assigned_date",
        "last_status_date",
    ]:
        if column in display.columns:
            display[column] = pd.to_datetime(
                display[column],
                errors="coerce",
            ).dt.strftime("%b %d, %Y")

    selected = [
        "shipment_id",
        "customer_name",
        "pickup_date",
        "pickup_time_window",
        "pickup_address",
        "item_type",
        "quantity",
        "assignment_status",
    ]

    return display[selected].rename(
        columns={
            "shipment_id": "Shipment ID",
            "customer_name": "Customer",
            "pickup_date": "Pickup Date",
            "pickup_time_window": "Two-Hour Window",
            "pickup_address": "Pickup Address",
            "item_type": "Item",
            "quantity": "Quantity",
            "assignment_status": "Driver Status",
        }
    )


def render_assignment_details(
    record: dict[str, Any],
) -> None:
    """Display the information a driver needs for one pickup."""

    with st.container(border=True):
        st.markdown(
            "### "
            + clean(
                record.get("shipment_id")
            )
        )

        detail_columns = st.columns(3)

        detail_values = [
            (
                "Customer",
                clean(
                    record.get("customer_name")
                ),
            ),
            (
                "Pickup Date",
                clean(
                    pd.to_datetime(
                        record.get("pickup_date"),
                        errors="coerce",
                    ).strftime("%b %d, %Y")
                    if pd.notna(
                        pd.to_datetime(
                            record.get("pickup_date"),
                            errors="coerce",
                        )
                    )
                    else None
                ),
            ),
            (
                "Pickup Window",
                clean(
                    record.get(
                        "pickup_time_window"
                    )
                ),
            ),
            (
                "Item",
                clean(
                    record.get("item_type")
                ),
            ),
            (
                "Quantity",
                clean(
                    record.get("quantity")
                ),
            ),
            (
                "Status",
                clean(
                    record.get(
                        "assignment_status"
                    )
                ),
            ),
        ]

        for column, (
            label,
            value,
        ) in zip(
            detail_columns * 2,
            detail_values,
        ):
            with column:
                st.markdown(
                    f"**{label}**"
                )
                st.write(value)

        st.markdown("**Pickup Address**")
        st.write(
            clean(
                record.get("pickup_address")
            )
        )

        customer_phone = clean(
            record.get("customer_phone"),
            "",
        )

        action_columns = st.columns(3)

        address = clean(
            record.get("pickup_address"),
            "",
        )

        with action_columns[0]:
            if address:
                directions_url = (
                    "https://www.google.com/maps/search/"
                    "?api=1&query="
                    + quote_plus(address)
                )

                st.link_button(
                    "Open Directions",
                    directions_url,
                    use_container_width=True,
                )

        digits = re.sub(
            r"\D",
            "",
            customer_phone,
        )

        with action_columns[1]:
            if digits:
                st.link_button(
                    "Call Customer",
                    f"tel:{digits}",
                    use_container_width=True,
                )

        with action_columns[2]:
            if digits:
                sms_body = quote_plus(
                    "Hello, this is your Solomon Shipping driver "
                    f"regarding shipment {clean(record.get('shipment_id'))}."
                )

                st.link_button(
                    "Text Customer",
                    f"sms:{digits}?body={sms_body}",
                    use_container_width=True,
                )

        with st.expander(
            "Pickup and shipment notes"
        ):
            st.write(
                clean(
                    record.get("pickup_notes"),
                    "No pickup notes.",
                )
            )

            st.write(
                clean(
                    record.get("shipment_notes"),
                    "No shipment notes.",
                )
            )



def render_customer_communication(
    engine: Engine,
    record: dict[str, Any],
    driver_id: str,
    driver_name: str,
) -> None:
    """Render the in-app driver/customer message thread and send form."""

    pickup_id = clean(
        record.get("pickup_id"),
        "",
    )

    shipment_id = clean(
        record.get("shipment_id"),
        "",
    )

    if not pickup_id or not shipment_id:
        return

    st.markdown("### Customer Communication")

    st.caption(
        "Use Call or Text for immediate contact. Messages sent below are "
        "saved in Neon for the Customer, Staff, and Owner workflow."
    )

    try:
        messages = load_pickup_messages(
            engine,
            pickup_id,
        )

    except Exception as exc:
        st.error(
            "The message thread could not be loaded."
        )
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error(exc)}"
        )
        messages = pd.DataFrame()

    if messages.empty:
        st.info(
            "No in-app messages have been sent for this pickup."
        )

    else:
        with st.container(
            border=True,
            height=300,
        ):
            for _, message in messages.iterrows():
                sender_role = clean(
                    message.get("sender_role"),
                    "System",
                )

                sender_name = clean(
                    message.get("sender_name"),
                    sender_role,
                )

                created_at = pd.to_datetime(
                    message.get("created_at"),
                    errors="coerce",
                )

                timestamp = (
                    created_at.strftime(
                        "%b %d, %Y %I:%M %p"
                    )
                    if pd.notna(created_at)
                    else ""
                )

                icon = {
                    "Driver": "🚚",
                    "Customer": "👤",
                    "Staff": "🛠️",
                    "Owner": "👑",
                    "System": "🔔",
                }.get(
                    sender_role,
                    "💬",
                )

                st.markdown(
                    f"**{icon} {sender_name}** "
                    f"<span style='font-size:0.78rem; "
                    f"color:#666;'>{timestamp}</span>",
                    unsafe_allow_html=True,
                )

                st.write(
                    clean(
                        message.get("message_text"),
                        "",
                    )
                )

                st.divider()

    quick_messages = [
        "I am on my way.",
        "I have arrived and am outside.",
        "I rang the bell but did not receive an answer.",
        "Please have the shipment ready for pickup.",
        "I am delayed due to traffic.",
        "Please call me regarding access to the pickup location.",
        "Your shipment has been picked up.",
        "Custom message",
    ]

    with st.form(
        f"driver_customer_message_{pickup_id}"
    ):
        quick_choice = st.selectbox(
            "Quick Message",
            quick_messages,
        )

        custom_message = st.text_area(
            "Message to Customer",
            value=(
                ""
                if quick_choice
                == "Custom message"
                else quick_choice
            ),
            height=95,
            placeholder=(
                "Write a clear pickup-related message."
            ),
        )

        send_left, send_center, send_right = (
            st.columns([2.1, 1.8, 2.1])
        )

        with send_center:
            send_submitted = (
                st.form_submit_button(
                    "Send Message",
                    type="primary",
                    use_container_width=True,
                )
            )

    if send_submitted:
        if not custom_message.strip():
            st.error(
                "Enter a message before sending."
            )

        else:
            try:
                send_driver_message(
                    engine,
                    shipment_id=shipment_id,
                    pickup_id=pickup_id,
                    driver_id=driver_id,
                    driver_name=driver_name,
                    message_text=custom_message,
                )

                st.success(
                    "Message sent and saved."
                )
                st.rerun()

            except Exception as exc:
                st.error(
                    "The message could not be sent."
                )
                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error(exc)}"
                )



def select_assignment(
    frame: pd.DataFrame,
    key: str,
) -> dict[str, Any]:
    """Let the driver select one assignment from a tab."""

    assignment_ids = (
        frame["assignment_id"]
        .astype(str)
        .tolist()
    )

    lookup = {
        str(row["assignment_id"]): row
        for _, row in frame.iterrows()
    }

    def label(
        assignment_id: str,
    ) -> str:
        row = lookup[assignment_id]

        return (
            f"{clean(row.get('shipment_id'))}"
            f" — {clean(row.get('customer_name'))}"
            f" — {clean(row.get('pickup_time_window'))}"
        )

    selected_id = st.selectbox(
        "Select Assignment",
        assignment_ids,
        format_func=label,
        key=key,
    )

    return lookup[selected_id].to_dict()


def render_pending_assignments(
    engine: Engine,
    frame: pd.DataFrame,
    driver_id: str,
    driver_name: str,
) -> None:
    """Render assignments waiting for the driver's answer."""

    if frame.empty:
        st.success(
            "You have no assignments waiting for acceptance."
        )
        return

    st.warning(
        f"{len(frame)} assignment"
        f"{'s are' if len(frame) != 1 else ' is'} "
        "waiting for your response."
    )

    st.dataframe(
        assignment_display(frame),
        use_container_width=True,
        hide_index=True,
        height=min(
            420,
            80 + (len(frame) * 35),
        ),
    )

    record = select_assignment(
        frame,
        key="pending_assignment_select",
    )

    render_assignment_details(record)

    accept_column, decline_column = st.columns(2)

    with accept_column:
        if st.button(
            "Accept Assignment",
            type="primary",
            use_container_width=True,
            key="accept_driver_assignment",
        ):
            try:
                update_assignment(
                    engine,
                    assignment_id=clean(
                        record.get("assignment_id"),
                        "",
                    ),
                    driver_id=driver_id,
                    driver_name=driver_name,
                    action="Accept Assignment",
                )

                st.success(
                    "Assignment accepted."
                )
                st.rerun()

            except Exception as exc:
                st.error(
                    "The assignment could not be accepted."
                )
                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error(exc)}"
                )

    with decline_column:
        with st.form(
            "decline_driver_assignment_form"
        ):
            decline_reason = st.text_area(
                "Decline Reason",
                placeholder=(
                    "Schedule conflict, vehicle issue, "
                    "area conflict, emergency, or another reason."
                ),
                height=95,
            )

            decline_submitted = (
                st.form_submit_button(
                    "Decline Assignment",
                    use_container_width=True,
                )
            )

        if decline_submitted:
            if not decline_reason.strip():
                st.error(
                    "Enter a reason before declining."
                )
            else:
                try:
                    update_assignment(
                        engine,
                        assignment_id=clean(
                            record.get("assignment_id"),
                            "",
                        ),
                        driver_id=driver_id,
                        driver_name=driver_name,
                        action="Decline Assignment",
                        decline_reason=(
                            decline_reason
                        ),
                    )

                    st.success(
                        "Assignment declined. "
                        "Staff has been notified for reassignment."
                    )
                    st.rerun()

                except Exception as exc:
                    st.error(
                        "The assignment could not be declined."
                    )
                    st.caption(
                        "Technical details: "
                        f"{type(exc).__name__}: "
                        f"{safe_error(exc)}"
                    )


def render_active_assignments(
    engine: Engine,
    frame: pd.DataFrame,
    driver_id: str,
    driver_name: str,
) -> None:
    """Render accepted, delayed, waiting, and in-progress pickups."""

    if frame.empty:
        st.info(
            "You have no active pickups."
        )
        return

    st.dataframe(
        assignment_display(frame),
        use_container_width=True,
        hide_index=True,
        height=min(
            420,
            80 + (len(frame) * 35),
        ),
    )

    record = select_assignment(
        frame,
        key="active_assignment_select",
    )

    render_assignment_details(record)

    current_status = clean(
        record.get("assignment_status"),
        "",
    )

    available_actions = {
        "Driver Accepted": [
            "Start Route",
            "Customer Requested Reschedule",
            "Vehicle Problem",
            "Unable to Complete",
        ],
        "Driver En Route": [
            "Traffic Delay",
            "Mark Arrived",
            "Address Problem",
            "Vehicle Problem",
            "Customer Requested Reschedule",
            "Unable to Complete",
        ],
        "Driver Delayed": [
            "Start Route",
            "Traffic Delay",
            "Mark Arrived",
            "Address Problem",
            "Vehicle Problem",
            "Unable to Complete",
        ],
        "Driver Arrived": [
            "Ring Bell — No Answer",
            "Customer Contacted — Waiting",
            "Confirm Picked Up",
            "Customer Not Ready",
            "Customer Requested Reschedule",
            "Unable to Access Property",
            "Unable to Complete",
        ],
        "Waiting for Customer": [
            "Ring Bell — No Answer",
            "Customer Contacted — Waiting",
            "Confirm Picked Up",
            "Customer Not Ready",
            "Customer Requested Reschedule",
            "Unable to Access Property",
            "Unable to Complete",
        ],
    }.get(
        current_status,
        [],
    )

    if not available_actions:
        st.info(
            "Refresh the page to see the latest assignment status."
        )
        return

    st.markdown("### Update Pickup Status")

    with st.form(
        "driver_status_update_form"
    ):
        action = st.selectbox(
            "Driver Update",
            available_actions,
        )

        notes = st.text_area(
            "Driver Notes / Reason",
            placeholder=(
                "Required for issues, delays, access problems, "
                "reschedules, or unsuccessful pickup attempts."
            ),
            height=110,
        )

        submitted = st.form_submit_button(
            "Save Driver Update",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        try:
            new_status = update_assignment(
                engine,
                assignment_id=clean(
                    record.get("assignment_id"),
                    "",
                ),
                driver_id=driver_id,
                driver_name=driver_name,
                action=action,
                notes=notes,
            )

            st.success(
                f"Driver status updated: {new_status}."
            )
            st.rerun()

        except Exception as exc:
            st.error(
                "The driver update could not be saved."
            )
            st.caption(
                "Technical details: "
                f"{type(exc).__name__}: "
                f"{safe_error(exc)}"
            )

    st.divider()

    render_customer_communication(
        engine,
        record,
        driver_id,
        driver_name,
    )


def main() -> None:
    """Render the authenticated Driver Portal."""

    apply_custom_styles()
    sidebar_shipping_options()

    driver_id, session_driver_name = (
        verify_access()
    )

    try:
        engine = db_engine()
        verify_tables(engine)
        profile = load_driver_profile(
            engine,
            driver_id,
        )
        assignments = load_assignments(
            engine,
            driver_id,
        )

    except Exception as exc:
        st.error(
            "The Driver Portal could not load from Neon."
        )
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error(exc)}"
        )
        return

    driver_name = clean(
        profile.get("driver_name"),
        session_driver_name or driver_id,
    )

    st.session_state.driver_name = driver_name

    hero(
        title=f"Driver Portal — {driver_name}",
        subtitle=(
            "Review assigned pickups, accept or decline new work, "
            "call or message customers, and send detailed live pickup updates."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Assigned Pickups Only</span>
        <span class="badge-dark">Live Staff Updates</span>
        <span class="badge-red">Customer Status Tracking</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    pending = assignments[
        assignments["assignment_status"].isin(
            PENDING_STATUSES
        )
    ].copy()

    active = assignments[
        assignments["assignment_status"].isin(
            ACTIVE_STATUSES
        )
    ].copy()

    history = assignments[
        ~assignments["assignment_status"].isin(
            PENDING_STATUSES
            | ACTIVE_STATUSES
        )
    ].copy()

    today = date.today()

    completed_today = 0

    if not history.empty:
        completion_dates = pd.to_datetime(
            history["completion_time"],
            errors="coerce",
        ).dt.date

        completed_today = int(
            (
                history["assignment_status"]
                .eq("Completed")
                & completion_dates.eq(today)
            ).sum()
        )

    metrics = st.columns(4)

    metric_values = [
        (
            "Awaiting Response",
            len(pending),
        ),
        (
            "Active Pickups",
            len(active),
        ),
        (
            "Completed Today",
            completed_today,
        ),
        (
            "Vehicle",
            clean(
                profile.get("vehicle_type"),
                "Not Listed",
            ),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        metrics,
        metric_values,
    ):
        with column:
            st.metric(
                label,
                value,
            )

    with st.expander(
        "Driver Profile"
    ):
        profile_columns = st.columns(3)

        details = [
            (
                "Driver ID",
                clean(
                    profile.get("driver_id")
                ),
            ),
            (
                "Primary Area",
                clean(
                    profile.get("primary_area")
                ),
            ),
            (
                "Service Areas",
                clean(
                    profile.get("service_areas")
                ),
            ),
            (
                "Vehicle",
                clean(
                    profile.get("vehicle_type")
                ),
            ),
            (
                "Vehicle Plate",
                clean(
                    profile.get("vehicle_plate")
                ),
            ),
            (
                "Driver Status",
                clean(
                    profile.get("active_status")
                ),
            ),
        ]

        for column, (
            label,
            value,
        ) in zip(
            profile_columns * 2,
            details,
        ):
            with column:
                st.markdown(
                    f"**{label}**"
                )
                st.write(value)

    tabs = st.tabs(
        [
            "New Assignments",
            "Active Pickups",
            "History",
        ]
    )

    with tabs[0]:
        render_pending_assignments(
            engine,
            pending,
            driver_id,
            driver_name,
        )

    with tabs[1]:
        render_active_assignments(
            engine,
            active,
            driver_id,
            driver_name,
        )

    with tabs[2]:
        if history.empty:
            st.info(
                "No completed or closed assignments."
            )
        else:
            st.dataframe(
                assignment_display(history),
                use_container_width=True,
                hide_index=True,
                height=min(
                    520,
                    80 + (len(history) * 35),
                ),
            )

            st.download_button(
                "Download Assignment History",
                data=assignment_display(
                    history
                ).to_csv(
                    index=False
                ).encode("utf-8"),
                file_name=(
                    f"{driver_id}_assignment_history.csv"
                ),
                mime="text/csv",
                key="driver_history_csv",
            )


if __name__ == "__main__":
    main()
