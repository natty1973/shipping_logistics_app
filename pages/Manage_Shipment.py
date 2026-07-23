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
    page_title="Manage Shipment",
    page_icon="🛠️",
    layout="wide",
)

SCHEMA = "solomon_shipping"

CHANGE_TYPES = [
    "Request Pickup Reschedule",
    "Request Shipment Cancellation",
    "Update Pickup Notes",
    "Update Contact Information",
    "General Shipment Change Request",
]

RESCHEDULE_REASONS = [
    "Customer unavailable",
    "Pickup location changed",
    "Need more time to prepare items",
    "Weather or travel issue",
    "Incorrect pickup date selected",
    "Other",
]

PICKUP_WINDOWS = ["Morning", "Afternoon", "Evening", "Flexible"]


def get_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value

    try:
        value = st.secrets.get(name, "")
    except (FileNotFoundError, KeyError, TypeError, AttributeError):
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
            "application_name": "solomon_shipping_manage_page",
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

    message = re.sub(
        r"password\s*=\s*[^,\s]+",
        "password=***",
        message,
        flags=re.IGNORECASE,
    )

    return message


def verify_required_tables(engine: Engine) -> None:
    required = [
        f"{SCHEMA}.shipments",
        f"{SCHEMA}.shipment_change_history",
    ]

    missing: list[str] = []

    with engine.connect() as connection:
        for relation_name in required:
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


def load_shipment_ids(engine: Engine) -> list[str]:
    query = text(
        f"""
        SELECT shipment_id
        FROM {SCHEMA}.shipments
        WHERE shipment_id IS NOT NULL
          AND BTRIM(shipment_id) <> ''
        ORDER BY
            shipment_date DESC NULLS LAST,
            shipment_id DESC;
        """
    )

    with engine.connect() as connection:
        rows = connection.execute(query).scalars().all()

    return [
        str(value).strip()
        for value in rows
        if value
    ]


def find_shipment(
    engine: Engine,
    shipment_id: str,
) -> dict[str, Any] | None:
    query = text(
        f"""
        SELECT
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
            payment_status,
            service_type,
            shipment_mode,
            release_status
        FROM {SCHEMA}.shipments
        WHERE
            UPPER(BTRIM(shipment_id))
            =
            UPPER(BTRIM(:shipment_id))
        LIMIT 1;
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            query,
            {"shipment_id": shipment_id},
        ).mappings().first()

    return dict(row) if row else None


def load_change_history(
    engine: Engine,
    shipment_id: str,
) -> pd.DataFrame:
    query = text(
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
            UPPER(BTRIM(shipment_id))
            =
            UPPER(BTRIM(:shipment_id))
        ORDER BY change_date DESC;
        """
    )

    with engine.connect() as connection:
        return pd.read_sql_query(
            query,
            connection,
            params={"shipment_id": shipment_id},
        )


def generate_change_id() -> str:
    return (
        f"CHG-REQ-{datetime.now().strftime('%Y%m%d')}-"
        f"{uuid4().hex[:8].upper()}"
    )


def save_change_request(
    engine: Engine,
    record: dict[str, Any],
) -> None:
    insert_query = text(
        f"""
        INSERT INTO {SCHEMA}.shipment_change_history (
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
        )
        VALUES (
            :change_id,
            :shipment_id,
            :customer_id,
            :customer_name,
            CURRENT_TIMESTAMP,
            :change_type,
            :old_value,
            :new_value,
            :requested_by,
            'Customer',
            :request_reason,
            'Pending',
            NULL,
            NULL,
            NULL,
            :notes
        );
        """
    )

    with engine.begin() as connection:
        shipment_exists = connection.execute(
            text(
                f"""
                SELECT 1
                FROM {SCHEMA}.shipments
                WHERE
                    UPPER(BTRIM(shipment_id))
                    =
                    UPPER(BTRIM(:shipment_id));
                """
            ),
            {"shipment_id": record["shipment_id"]},
        ).scalar_one_or_none()

        if shipment_exists is None:
            raise RuntimeError(
                "The shipment no longer exists in Neon. "
                "Refresh and try again."
            )

        connection.execute(insert_query, record)


def format_value(
    value: Any,
    fallback: str = "Not Available",
) -> str:
    if value is None:
        return fallback

    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass

    clean_value = str(value).strip()

    return clean_value or fallback


def staff_or_owner_portal() -> bool:
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


def build_change_values(
    change_type: str,
    current_status: str,
    new_pickup_date: date | None,
    new_pickup_window: str | None,
    updated_phone: str,
    updated_email: str,
    updated_notes: str,
) -> tuple[str, str]:
    if change_type == "Request Pickup Reschedule":
        return (
            "Existing pickup preference / schedule",
            f"{new_pickup_date} — {new_pickup_window}",
        )

    if change_type == "Request Shipment Cancellation":
        return (
            current_status,
            "Cancellation Requested",
        )

    if change_type == "Update Contact Information":
        phone = (
            updated_phone.strip()
            or "No phone change provided"
        )

        email = (
            updated_email.strip()
            or "No email change provided"
        )

        return (
            "Existing contact information",
            f"Phone: {phone}; Email: {email}",
        )

    if change_type == "Update Pickup Notes":
        return (
            "Existing pickup notes",
            updated_notes.strip(),
        )

    return (
        "Existing shipment details",
        updated_notes.strip(),
    )


def validate_request(
    change_type: str,
    updated_phone: str,
    updated_email: str,
    updated_notes: str,
) -> str | None:
    if change_type == "Update Contact Information":
        if (
            not updated_phone.strip()
            and not updated_email.strip()
        ):
            return (
                "Enter an updated phone number, "
                "an updated email address, or both."
            )

    if change_type in {
        "Update Pickup Notes",
        "General Shipment Change Request",
    }:
        if not updated_notes.strip():
            return (
                "Please explain the requested change "
                "in Additional Details."
            )

    return None


def main() -> None:
    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Manage Shipment",
        subtitle=(
            "Request a pickup reschedule, cancellation, "
            "contact update, or other shipment change. "
            "Solomon Shipping staff will review and confirm "
            "approved changes."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Customer Request</span>
        <span class="badge-dark">Reschedule / Cancel</span>
        <span class="badge-red">Staff Review Required</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = get_database_engine()
        verify_required_tables(engine)

    except Exception as exc:
        st.error(
            "The Manage Shipment page could not connect "
            "to the Solomon Shipping records in Neon."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    st.subheader("Find Your Shipment")

    typed_shipment_id = ""
    selected_shipment_id = ""

    if staff_or_owner_portal():
        try:
            shipment_ids = load_shipment_ids(engine)

        except Exception as exc:
            st.error(
                "The current shipment list could not "
                "be loaded from Neon."
            )

            st.caption(
                "Technical details: "
                f"{type(exc).__name__}: "
                f"{safe_error_message(exc)}"
            )

            return

        lookup_col1, lookup_col2 = st.columns([2, 1])

        with lookup_col1:
            typed_shipment_id = st.text_input(
                "Enter Shipment ID",
                placeholder="Example: SST-2026-0026",
            )

        with lookup_col2:
            selected_option = st.selectbox(
                "Or select a shipment",
                options=[
                    "Choose an option",
                    *shipment_ids,
                ],
            )

            if selected_option != "Choose an option":
                selected_shipment_id = selected_option

    else:
        typed_shipment_id = st.text_input(
            "Enter Shipment ID",
            placeholder="Example: SST-2026-0026",
        )

        st.caption(
            "Enter the Shipment ID shown on your "
            "shipment confirmation."
        )

    shipment_id_to_lookup = (
        typed_shipment_id.strip()
        or selected_shipment_id.strip()
    )

    if not shipment_id_to_lookup:
        st.info(
            "Enter a shipment ID to manage a shipment."
        )
        return

    try:
        shipment = find_shipment(
            engine,
            shipment_id_to_lookup,
        )

    except Exception as exc:
        st.error(
            "The shipment lookup could not be completed."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        return

    if shipment is None:
        st.error(
            "No shipment found with that ID. "
            "Please check the Shipment ID and try again."
        )
        return

    shipment_id = format_value(
        shipment.get("shipment_id"),
        shipment_id_to_lookup,
    )

    customer_id = format_value(
        shipment.get("customer_id"),
        "",
    )

    customer_name = format_value(
        shipment.get("customer_name")
    )

    current_status = format_value(
        shipment.get("current_status")
    )

    destination_city = format_value(
        shipment.get("destination_city")
    )

    destination_country = format_value(
        shipment.get("destination_country")
    )

    estimated_delivery = format_value(
        shipment.get("estimated_delivery_date"),
        "Pending confirmation",
    )

    st.divider()
    st.subheader("Shipment Summary")

    (
        summary_col1,
        summary_col2,
        summary_col3,
        summary_col4,
    ) = st.columns(4)

    with summary_col1:
        with st.container(border=True):
            st.markdown("#### Shipment ID")
            st.write(shipment_id)

    with summary_col2:
        with st.container(border=True):
            st.markdown("#### Customer")
            st.write(customer_name)

    with summary_col3:
        with st.container(border=True):
            st.markdown("#### Current Status")
            st.write(current_status)

    with summary_col4:
        with st.container(border=True):
            st.markdown("#### Estimated Delivery")
            st.write(estimated_delivery)

    with st.container(border=True):
        st.markdown("#### Destination")
        st.write(
            f"{destination_city}, "
            f"{destination_country}"
        )

    st.divider()
    st.subheader("Request a Change")

    st.write(
        "Customers may request a change, but official "
        "schedule changes, cancellations, and approvals "
        "must be reviewed by Solomon Shipping staff "
        "or the owner."
    )

    with st.form(
        "manage_shipment_form",
        clear_on_submit=False,
    ):
        change_type = st.selectbox(
            "What would you like to request?",
            CHANGE_TYPES,
        )

        reason = ""
        new_pickup_date: date | None = None
        new_pickup_window: str | None = None
        updated_phone = ""
        updated_email = ""

        if change_type == "Request Pickup Reschedule":
            (
                reschedule_col1,
                reschedule_col2,
            ) = st.columns(2)

            with reschedule_col1:
                new_pickup_date = st.date_input(
                    "Requested New Pickup Date",
                    value=date.today(),
                    min_value=date.today(),
                )

            with reschedule_col2:
                new_pickup_window = st.selectbox(
                    "Requested New Pickup Window",
                    PICKUP_WINDOWS,
                )

            reason = st.selectbox(
                "Reason for Reschedule",
                RESCHEDULE_REASONS,
            )

        elif change_type == "Request Shipment Cancellation":
            reason = st.selectbox(
                "Reason for Cancellation",
                [
                    "No longer shipping items",
                    "Need to ship at a later date",
                    "Wrong destination entered",
                    "Found another shipping option",
                    "Pickup no longer needed",
                    "Other",
                ],
            )

        elif change_type == "Update Contact Information":
            (
                contact_col1,
                contact_col2,
            ) = st.columns(2)

            with contact_col1:
                updated_phone = st.text_input(
                    "Updated Phone Number"
                )

            with contact_col2:
                updated_email = st.text_input(
                    "Updated Email Address"
                )

            reason = (
                "Customer requested contact "
                "information update"
            )

        elif change_type == "Update Pickup Notes":
            reason = "Customer updated pickup notes"

        else:
            reason = (
                "Customer submitted general shipment "
                "change request"
            )

        updated_notes = st.text_area(
            "Additional Details",
            placeholder=(
                "Explain what you need changed or add "
                "helpful notes for Solomon Shipping staff."
            ),
            height=130,
        )

        submitted = st.form_submit_button(
            "Submit Change Request",
            use_container_width=True,
        )

    if submitted:
        validation_error = validate_request(
            change_type,
            updated_phone,
            updated_email,
            updated_notes,
        )

        if validation_error:
            st.error(validation_error)

        else:
            old_value, new_value = build_change_values(
                change_type,
                current_status,
                new_pickup_date,
                new_pickup_window,
                updated_phone,
                updated_email,
                updated_notes,
            )

            change_id = generate_change_id()

            change_record = {
                "change_id": change_id,
                "shipment_id": shipment_id,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "change_type": change_type,
                "old_value": old_value,
                "new_value": new_value,
                "requested_by": customer_name,
                "request_reason": reason,
                "notes": updated_notes.strip(),
            }

            try:
                with st.spinner(
                    "Saving your change request to Neon..."
                ):
                    save_change_request(
                        engine,
                        change_record,
                    )

                st.success(
                    "Your change request was submitted "
                    "successfully. "
                    f"Change Request ID: {change_id}"
                )

                st.info(
                    "The request is pending Solomon Shipping "
                    "staff review. The shipment has not been "
                    "changed or cancelled yet."
                )

                confirmation = {
                    **change_record,
                    "change_date": datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "approval_status": "Pending",
                }

                st.markdown(
                    "### Submitted Change Request"
                )

                st.dataframe(
                    pd.DataFrame([confirmation]),
                    use_container_width=True,
                )

            except Exception as exc:
                st.error(
                    "The change request could not be "
                    "saved to Neon."
                )

                st.caption(
                    "Technical details: "
                    f"{type(exc).__name__}: "
                    f"{safe_error_message(exc)}"
                )

    st.divider()
    st.subheader("Shipment Change History")

    try:
        history = load_change_history(
            engine,
            shipment_id,
        )

    except Exception as exc:
        st.error(
            "The shipment change history could not "
            "be loaded."
        )

        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

        history = pd.DataFrame()

    if history.empty:
        st.info(
            "No change history found for this shipment yet."
        )
    else:
        st.dataframe(
            history,
            use_container_width=True,
        )

    st.divider()
    st.subheader("What Happens Next?")

    next_col1, next_col2, next_col3 = st.columns(3)

    with next_col1:
        with st.container(border=True):
            st.markdown("### 1. Request Submitted")
            st.write(
                "Your change request is saved in Neon "
                "with Pending status."
            )

    with next_col2:
        with st.container(border=True):
            st.markdown("### 2. Staff Review")
            st.write(
                "Solomon Shipping staff reviews the "
                "request and confirms the next steps."
            )

    with next_col3:
        with st.container(border=True):
            st.markdown("### 3. Update Confirmed")
            st.write(
                "Approved updates are reflected in the "
                "shipment or pickup record."
            )


if __name__ == "__main__":
    main()