from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from src.styles import (
    apply_custom_styles,
    configure_portal_home_page,
    hero,
    operations_pathway,
    sidebar_shipping_options,
)


st.set_page_config(
    page_title="Solomon Shipping and Trading Inc.",
    page_icon="🚢",
    layout="wide",
)


# ---------------------------------------------------------
# MVP Login Credentials
# ---------------------------------------------------------
STAFF_USERNAME = "staff"
STAFF_PASSWORD = "staff2026"

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "solomon2026"


# ---------------------------------------------------------
# Live Neon / PostgreSQL Dashboard Data
# ---------------------------------------------------------
DATABASE_SCHEMA = "solomon_shipping"


def get_secret(name: str) -> str:
    """Read a database setting from the environment or Streamlit Secrets."""

    environment_value = os.getenv(name, "").strip()

    if environment_value:
        return environment_value

    try:
        secret_value = st.secrets.get(name, "")
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        return ""

    return str(secret_value).strip() if secret_value is not None else ""


@st.cache_resource(show_spinner=False)
def get_database_engine() -> Engine:
    """Create a reusable Neon/PostgreSQL connection."""

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
            "application_name": "solomon_shipping_dashboard",
        },
    )

    with engine.connect() as connection:
        connection.execute(text("SELECT 1;"))

    return engine


def safe_error_message(error: Exception) -> str:
    """Remove credentials if a database error includes them."""

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


def to_decimal(value: Any) -> Decimal:
    """Convert a database amount to a two-decimal Decimal."""

    if value is None:
        return Decimal("0.00")

    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def format_usd(value: Any) -> str:
    """Format an owner-dashboard amount as USD."""

    return f"${to_decimal(value):,.2f}"


def verify_dashboard_tables(engine: Engine) -> None:
    """Confirm the core operational tables exist."""

    required_relations = [
        f"{DATABASE_SCHEMA}.customers",
        f"{DATABASE_SCHEMA}.shipments",
        f"{DATABASE_SCHEMA}.pickup_schedule",
    ]

    missing: list[str] = []

    with engine.connect() as connection:
        for relation_name in required_relations:
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


def table_exists(
    engine: Engine,
    table_name: str,
) -> bool:
    """Return whether an optional dashboard table exists."""

    relation_name = f"{DATABASE_SCHEMA}.{table_name}"

    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT TO_REGCLASS(:relation_name);"),
                {"relation_name": relation_name},
            ).scalar_one_or_none()
            is not None
        )


def load_request_queue(
    engine: Engine,
) -> pd.DataFrame:
    """
    Load new shipment requests and pickups that still need staff attention.

    A request remains in this queue until the shipment or pickup status is
    advanced beyond its initial pending state.
    """

    query = text(
        f"""
        WITH latest_pickup AS (
            SELECT DISTINCT ON (shipment_id)
                pickup_id,
                shipment_id,
                pickup_date,
                pickup_time_window,
                pickup_address,
                pickup_status,
                assigned_staff,
                driver_id,
                created_at,
                updated_at
            FROM {DATABASE_SCHEMA}.pickup_schedule
            ORDER BY
                shipment_id,
                updated_at DESC NULLS LAST,
                created_at DESC NULLS LAST
        )
        SELECT
            s.shipment_id,
            s.customer_name,
            s.shipment_date,
            s.origin_city,
            s.origin_state,
            s.destination_city,
            s.destination_country,
            s.service_type,
            s.shipment_mode,
            s.amount_charged,
            s.current_status,
            p.pickup_id,
            p.pickup_date,
            p.pickup_time_window,
            p.pickup_address,
            p.pickup_status,
            p.assigned_staff,
            p.driver_id,
            s.created_at AS request_created_at
        FROM {DATABASE_SCHEMA}.shipments AS s
        LEFT JOIN latest_pickup AS p
            ON p.shipment_id = s.shipment_id
        WHERE
            LOWER(BTRIM(COALESCE(s.current_status, '')))
                = 'request received'
            OR LOWER(BTRIM(COALESCE(p.pickup_status, '')))
                IN (
                    'pending',
                    'pending confirmation',
                    'awaiting confirmation'
                )
        ORDER BY
            s.created_at DESC NULLS LAST,
            s.shipment_date DESC NULLS LAST,
            s.shipment_id DESC
        LIMIT 50;
        """
    )

    with engine.connect() as connection:
        return pd.read_sql_query(
            query,
            connection,
        )


def load_dashboard_counts(
    engine: Engine,
) -> dict[str, Any]:
    """Load live operational and owner-level totals from Neon."""

    core_query = text(
        f"""
        SELECT
            (
                SELECT COUNT(*)
                FROM {DATABASE_SCHEMA}.customers
            ) AS total_customers,
            (
                SELECT COUNT(*)
                FROM {DATABASE_SCHEMA}.shipments
            ) AS total_shipments,
            (
                SELECT COUNT(*)
                FROM {DATABASE_SCHEMA}.shipments
                WHERE LOWER(BTRIM(COALESCE(current_status, '')))
                    = 'request received'
            ) AS new_requests,
            (
                SELECT COUNT(*)
                FROM {DATABASE_SCHEMA}.pickup_schedule
                WHERE LOWER(BTRIM(COALESCE(pickup_status, '')))
                    IN (
                        'pending',
                        'pending confirmation',
                        'awaiting confirmation'
                    )
            ) AS pending_pickups,
            (
                SELECT COUNT(*)
                FROM {DATABASE_SCHEMA}.pickup_schedule
                WHERE LOWER(BTRIM(COALESCE(pickup_status, '')))
                    IN (
                        'pending',
                        'pending confirmation',
                        'awaiting confirmation'
                    )
                  AND NULLIF(BTRIM(COALESCE(driver_id, '')), '')
                      IS NULL
            ) AS unassigned_pickups,
            (
                SELECT COUNT(*)
                FROM {DATABASE_SCHEMA}.shipments
                WHERE LOWER(BTRIM(COALESCE(current_status, '')))
                    LIKE '%in transit%'
            ) AS in_transit,
            (
                SELECT COUNT(*)
                FROM {DATABASE_SCHEMA}.shipments
                WHERE LOWER(BTRIM(COALESCE(current_status, '')))
                    LIKE '%delivered%'
            ) AS delivered;
        """
    )

    with engine.connect() as connection:
        result = connection.execute(
            core_query
        ).mappings().one()

    counts: dict[str, Any] = dict(result)
    counts["revenue_collected"] = Decimal("0.00")
    counts["outstanding_balance"] = Decimal("0.00")

    if table_exists(engine, "payments"):
        with engine.connect() as connection:
            counts["revenue_collected"] = (
                connection.execute(
                    text(
                        f"""
                        SELECT COALESCE(
                            SUM(amount_paid),
                            0
                        )
                        FROM {DATABASE_SCHEMA}.payments;
                        """
                    )
                ).scalar_one()
            )

    if table_exists(engine, "branch_payments"):
        with engine.connect() as connection:
            counts["outstanding_balance"] = (
                connection.execute(
                    text(
                        f"""
                        WITH latest_accounts AS (
                            SELECT DISTINCT ON (shipment_id)
                                shipment_id,
                                balance_due
                            FROM {DATABASE_SCHEMA}.branch_payments
                            ORDER BY
                                shipment_id,
                                updated_at DESC NULLS LAST,
                                created_at DESC NULLS LAST
                        )
                        SELECT COALESCE(
                            SUM(balance_due),
                            0
                        )
                        FROM latest_accounts;
                        """
                    )
                ).scalar_one()
            )

    return counts


def prepare_request_queue_display(
    request_queue: pd.DataFrame,
) -> pd.DataFrame:
    """Create a clean staff/owner view of the pending request queue."""

    if request_queue.empty:
        return pd.DataFrame()

    display = request_queue.copy()

    display["route"] = (
        display["origin_city"].fillna("")
        + ", "
        + display["origin_state"].fillna("")
        + " → "
        + display["destination_city"].fillna("")
        + ", "
        + display["destination_country"].fillna("")
    )

    display["assigned_driver"] = (
        display["driver_id"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Not Assigned")
    )

    display["estimated_price"] = display[
        "amount_charged"
    ].apply(format_usd)

    for date_column in [
        "shipment_date",
        "pickup_date",
        "request_created_at",
    ]:
        if date_column in display.columns:
            display[date_column] = pd.to_datetime(
                display[date_column],
                errors="coerce",
            ).dt.strftime("%b %d, %Y")

    display_columns = [
        "shipment_id",
        "customer_name",
        "route",
        "service_type",
        "pickup_date",
        "pickup_time_window",
        "estimated_price",
        "current_status",
        "pickup_status",
        "assigned_driver",
    ]

    available_columns = [
        column
        for column in display_columns
        if column in display.columns
    ]

    return display[available_columns].rename(
        columns={
            "shipment_id": "Shipment ID",
            "customer_name": "Customer",
            "route": "Route",
            "service_type": "Service",
            "pickup_date": "Preferred Pickup",
            "pickup_time_window": "Preferred Window",
            "estimated_price": "Estimate",
            "current_status": "Shipment Status",
            "pickup_status": "Pickup Status",
            "assigned_driver": "Driver",
        }
    )


def render_new_request_queue(
    engine: Engine,
    heading: str,
    show_owner_note: bool = False,
) -> None:
    """Render the live new-request alert and queue."""

    request_queue = load_request_queue(engine)
    counts = load_dashboard_counts(engine)

    st.subheader(heading)

    metric_columns = st.columns(3)

    with metric_columns[0]:
        st.metric(
            "New Shipment Requests",
            int(counts["new_requests"]),
        )

    with metric_columns[1]:
        st.metric(
            "Pickups Awaiting Confirmation",
            int(counts["pending_pickups"]),
        )

    with metric_columns[2]:
        st.metric(
            "Pickups Without a Driver",
            int(counts["unassigned_pickups"]),
        )

    if request_queue.empty:
        st.success(
            "There are no new shipment requests "
            "or pending pickup confirmations."
        )
        return

    new_request_count = int(
        counts["new_requests"]
    )

    if new_request_count > 0:
        st.warning(
            f"{new_request_count} new shipment request"
            f"{'s' if new_request_count != 1 else ''} "
            "need review."
        )
    else:
        st.info(
            "There are pending pickup records "
            "that still need attention."
        )

    display = prepare_request_queue_display(
        request_queue
    )

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        height=min(
            520,
            78 + (len(display) * 35),
        ),
    )

    action_left, action_middle, action_right = (
        st.columns([1.35, 3.3, 1.35])
    )

    with action_left:
        st.page_link(
            "pages/Schedule_Pickup.py",
            label="Review and Schedule",
            icon="🚚",
            width="stretch",
        )

    with action_right:
        if st.button(
            "Refresh Requests",
            key=(
                "owner_refresh_requests"
                if show_owner_note
                else "staff_refresh_requests"
            ),
            use_container_width=True,
        ):
            st.rerun()

    if show_owner_note:
        st.caption(
            "The queue is read directly from Neon. "
            "A request leaves this list after staff "
            "advances the shipment or pickup status."
        )


# ---------------------------------------------------------
# Session State
# ---------------------------------------------------------
if "portal_mode" not in st.session_state:
    st.session_state.portal_mode = None

if "staff_authenticated" not in st.session_state:
    st.session_state.staff_authenticated = False

if "owner_authenticated" not in st.session_state:
    st.session_state.owner_authenticated = False


# ---------------------------------------------------------
# Session / Navigation Helpers
# ---------------------------------------------------------
def switch_portal() -> None:
    """
    Return user to the portal selection screen and clear protected session state.
    """

    st.session_state.portal_mode = None
    st.session_state.staff_authenticated = False
    st.session_state.owner_authenticated = False
    st.rerun()


def enter_customer_portal() -> None:
    """
    Send user directly into customer portal.
    Customer portal does not require login for this MVP.
    """

    st.session_state.portal_mode = "customer"
    st.session_state.staff_authenticated = False
    st.session_state.owner_authenticated = False
    st.rerun()


def go_to_staff_login() -> None:
    """
    Send user to staff login screen.
    """

    st.session_state.portal_mode = "staff_login"
    st.session_state.staff_authenticated = False
    st.session_state.owner_authenticated = False
    st.rerun()


def go_to_owner_login() -> None:
    """
    Send user to owner login screen.
    """

    st.session_state.portal_mode = "owner_login"
    st.session_state.staff_authenticated = False
    st.session_state.owner_authenticated = False
    st.rerun()


def authenticate_staff(username: str, password: str) -> bool:
    """
    Validate staff login credentials for the MVP.
    """

    return username == STAFF_USERNAME and password == STAFF_PASSWORD


def authenticate_owner(username: str, password: str) -> bool:
    """
    Validate owner login credentials for the MVP.
    """

    return username == OWNER_USERNAME and password == OWNER_PASSWORD


def render_back_to_portal_button() -> None:
    """
    Render a consistent sidebar button so users can return to portal selection.
    """

    with st.sidebar:
        if st.button(
            "← Back to Portal Selection",
            use_container_width=True,
            key="back_to_portal_selection",
        ):
            switch_portal()


def render_small_back_button(key: str) -> None:
    """
    Render a smaller back button for login pages.
    """

    st.write("")

    back_col1, back_col2, back_col3 = st.columns([1.25, 0.5, 1.25])

    with back_col2:
        if st.button(
            "← Back",
            use_container_width=True,
            key=key,
        ):
            switch_portal()


# ---------------------------------------------------------
# Portal Selection Page
# ---------------------------------------------------------
def portal_selection_page() -> None:
    """
    First screen users see.
    Users choose Customer, Staff, or Owner access.
    """

    apply_custom_styles()

    hero(
        title="Solomon Shipping and Trading Inc.",
        subtitle=(
            "Express deliveries weekly with fast, reliable, and flexible shipping options by air and sea. "
            "Choose the portal that matches how you want to use the platform."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Air & Sea Shipping</span>
        <span class="badge-dark">Fast Tracking</span>
        <span class="badge-red">Reliable Delivery</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    st.subheader("Select Your Portal")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True):
            st.markdown("## 👤 Customer Portal")
            st.write(
                "Request a shipment, manage shipment changes, check shipment status, "
                "review your payment, and contact support."
            )

            st.markdown(
                """
                Best for customers who want to:
                - Request shipping service
                - Track a package
                - Request pickup changes or cancellation
                - Check payment status
                - Contact Solomon Shipping support
                """
            )

            if st.button("Enter Customer Portal", use_container_width=True):
                enter_customer_portal()

    with col2:
        with st.container(border=True):
            st.markdown("## 🛠️ Staff Portal")
            st.write(
                "Secure access for staff to support customers and manage day-to-day shipment operations."
            )

            st.markdown(
                """
                Staff access includes:
                - Enter shipment requests for customers
                - Schedule pickups
                - Check shipment status
                - Help customers with payment lookup
                - Contact/support workflow
                """
            )

            if st.button("Staff Login", use_container_width=True):
                go_to_staff_login()

    with col3:
        with st.container(border=True):
            st.markdown("## 👑 Owner Portal")
            st.write(
                "Private owner access for company-wide financials, reports, and AI-powered business insights."
            )

            st.markdown(
                """
                Owner access includes:
                - Revenue and balances
                - Full payments dashboard
                - Reports
                - AI assistant
                - Business performance metrics
                """
            )

            if st.button("Owner Login", use_container_width=True):
                go_to_owner_login()

    st.divider()

    st.subheader("Our Shipping Options")

    ship_col1, ship_col2, ship_col3, ship_col4 = st.columns(4)

    with ship_col1:
        with st.container(border=True):
            st.markdown("### ✈️ Express Air")
            st.write("3–5 business days")

    with ship_col2:
        with st.container(border=True):
            st.markdown("### ✈️ Standard Air")
            st.write("7–10 business days")

    with ship_col3:
        with st.container(border=True):
            st.markdown("### 🚢 Express Sea")
            st.write("Approx. 3 weeks")

    with ship_col4:
        with st.container(border=True):
            st.markdown("### 🚢 Standard Sea")
            st.write("4–6 weeks")


# ---------------------------------------------------------
# Login Pages
# ---------------------------------------------------------
def staff_login_page() -> None:
    """
    Staff login page.
    """

    apply_custom_styles()

    hero(
        title="Staff Login",
        subtitle=(
            "Secure access for Solomon Shipping staff. Please sign in to support "
            "customer requests, pickups, shipment status, and service workflows."
        ),
    )

    st.markdown(
        """
        <span class="badge-dark">Staff Access</span>
        <span class="badge-green">Customer Support</span>
        <span class="badge-red">Operational View</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    login_col1, login_col2, login_col3 = st.columns([1, 1.4, 1])

    with login_col2:
        with st.container(border=True):
            st.markdown("### 🔐 Sign in to Staff Portal")

            with st.form("staff_login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")

                submitted = st.form_submit_button(
                    "Login",
                    use_container_width=True,
                )

            if submitted:
                if authenticate_staff(username.strip(), password.strip()):
                    st.session_state.portal_mode = "staff"
                    st.session_state.staff_authenticated = True
                    st.session_state.owner_authenticated = False
                    st.success("Login successful. Opening Staff Portal...")
                    st.rerun()
                else:
                    st.error("Invalid username or password. Please try again.")

    render_small_back_button("staff_login_back_button")


def owner_login_page() -> None:
    """
    Owner login page.
    """

    apply_custom_styles()

    hero(
        title="Owner Login",
        subtitle=(
            "Private owner access for company-wide financials, reports, revenue, "
            "outstanding balances, and AI-powered business insights."
        ),
    )

    st.markdown(
        """
        <span class="badge-dark">Owner Access</span>
        <span class="badge-green">Business Intelligence</span>
        <span class="badge-red">Financial View</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    login_col1, login_col2, login_col3 = st.columns([1, 1.4, 1])

    with login_col2:
        with st.container(border=True):
            st.markdown("### 🔐 Sign in to Owner Portal")

            with st.form("owner_login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")

                submitted = st.form_submit_button(
                    "Login",
                    use_container_width=True,
                )

            if submitted:
                if authenticate_owner(username.strip(), password.strip()):
                    st.session_state.portal_mode = "owner"
                    st.session_state.owner_authenticated = True
                    st.session_state.staff_authenticated = False
                    st.success("Login successful. Opening Owner Portal...")
                    st.rerun()
                else:
                    st.error("Invalid username or password. Please try again.")

    render_small_back_button("owner_login_back_button")


# ---------------------------------------------------------
# Customer Home Page
# ---------------------------------------------------------
def customer_home_page() -> None:
    """
    Customer-facing landing page.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Customer Portal",
        subtitle=(
            "Request a shipment, manage pickup changes or cancellations, track your package, "
            "review your payment, and contact Solomon Shipping support from one simple customer portal."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Customer Services</span>
        <span class="badge-dark">Air & Sea Shipping</span>
        <span class="badge-red">Fast • Reliable • Affordable</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    st.subheader("What would you like to do today?")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True):
            st.markdown("### 📝 Request Shipment")
            st.write(
                "Start a new shipment request by entering pickup, destination, item, and contact details."
            )
            st.page_link(
                "pages/Request_Shipment.py",
                label="Start Shipment Request",
                icon="➡️",
            )

    with col2:
        with st.container(border=True):
            st.markdown("### 🛠️ Manage Shipment")
            st.write(
                "Request pickup reschedule, cancellation, contact update, or other shipment changes."
            )
            st.page_link(
                "pages/Manage_Shipment.py",
                label="Manage Shipment",
                icon="➡️",
            )

    with col3:
        with st.container(border=True):
            st.markdown("### 📦 Shipment Status")
            st.write(
                "Check your current shipment status and view package movement history."
            )
            st.page_link(
                "pages/Track_Shipment.py",
                label="Track Shipment",
                icon="➡️",
            )

    col4, col5 = st.columns(2)

    with col4:
        with st.container(border=True):
            st.markdown("### 💳 My Payments")
            st.write(
                "Look up your invoice, payment status, amount paid, and any remaining balance."
            )
            st.page_link(
                "pages/My_Payments.py",
                label="View My Payments",
                icon="➡️",
            )

    with col5:
        with st.container(border=True):
            st.markdown("### ☎️ Contact Support")
            st.write(
                "Send a support request for pickup questions, shipment updates, payments, or delivery help."
            )
            st.page_link(
                "pages/Contact_Support.py",
                label="Contact Support",
                icon="➡️",
            )


# ---------------------------------------------------------
# Staff Home Page
# ---------------------------------------------------------
def staff_home_page() -> None:
    """Staff-facing landing page with a live Neon request queue."""

    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Staff Portal",
        subtitle=(
            "Review new shipment requests, confirm pickups, assign drivers, "
            "check shipment status, and support individual customer payments."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Staff Operations</span>
        <span class="badge-dark">Live Neon Requests</span>
        <span class="badge-red">Pickup Action Queue</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = get_database_engine()
        verify_dashboard_tables(engine)

        render_new_request_queue(
            engine,
            heading="New Requests and Pickup Queue",
        )

    except Exception as exc:
        st.error(
            "The Staff Portal could not load "
            "the live request queue from Neon."
        )
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )

    st.divider()
    st.subheader("Staff Tools")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True):
            st.markdown("### 📝 Request Shipment")
            st.write(
                "Create a shipment request on behalf of a customer "
                "who calls, visits, or messages the office."
            )
            st.page_link(
                "pages/Request_Shipment.py",
                label="Create Shipment Request",
                icon="➡️",
            )

    with col2:
        with st.container(border=True):
            st.markdown("### 🚚 Schedule Pickup")
            st.write(
                "Confirm pickup windows, assign drivers, "
                "and update pickup status."
            )
            st.page_link(
                "pages/Schedule_Pickup.py",
                label="Schedule Pickup",
                icon="➡️",
            )

    with col3:
        with st.container(border=True):
            st.markdown("### 📦 Shipment Status")
            st.write(
                "Look up a shipment and help customers "
                "understand its current status."
            )
            st.page_link(
                "pages/Track_Shipment.py",
                label="Check Shipment Status",
                icon="➡️",
            )

    col4, col5 = st.columns(2)

    with col4:
        with st.container(border=True):
            st.markdown("### 💳 Payment Lookup")
            st.write(
                "Look up an individual customer invoice "
                "or shipment payment status."
            )
            st.page_link(
                "pages/Payment_Lookup.py",
                label="Open Payment Lookup",
                icon="➡️",
            )

    with col5:
        with st.container(border=True):
            st.markdown("### ☎️ Support Request")
            st.write(
                "Create or review support activity for shipment, "
                "pickup, payment, or delivery questions."
            )
            st.page_link(
                "pages/Contact_Support.py",
                label="Open Support Form",
                icon="➡️",
            )

    st.info(
        "Staff access remains operational. Company-wide revenue, "
        "reports, and AI business analytics are available only "
        "in the Owner Portal."
    )


# ---------------------------------------------------------
# Owner Command Center
# ---------------------------------------------------------
def owner_command_center_page() -> None:
    """Owner command center backed by live Neon data."""

    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Owner Command Center",
        subtitle=(
            "Monitor new shipment requests, pending pickups, driver assignment, "
            "customer activity, revenue, outstanding balances, and operations."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner Portal</span>
        <span class="badge-dark">Live Neon Intelligence</span>
        <span class="badge-red">Financial + Request Queue</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    try:
        engine = get_database_engine()
        verify_dashboard_tables(engine)
        counts = load_dashboard_counts(engine)

    except Exception as exc:
        st.error(
            "The Owner Command Center could not load "
            "the live dashboard data from Neon."
        )
        st.caption(
            "Technical details: "
            f"{type(exc).__name__}: "
            f"{safe_error_message(exc)}"
        )
        return

    first_row = st.columns(4)

    first_metrics = [
        (
            "Customers",
            int(counts["total_customers"]),
        ),
        (
            "Shipments",
            int(counts["total_shipments"]),
        ),
        (
            "Revenue Collected",
            format_usd(
                counts["revenue_collected"]
            ),
        ),
        (
            "Outstanding Balance",
            format_usd(
                counts["outstanding_balance"]
            ),
        ),
    ]

    for column, (label, value) in zip(
        first_row,
        first_metrics,
    ):
        with column:
            st.metric(label, value)

    second_row = st.columns(3)

    second_metrics = [
        (
            "Pending Pickups",
            int(counts["pending_pickups"]),
        ),
        (
            "In Transit",
            int(counts["in_transit"]),
        ),
        (
            "Delivered",
            int(counts["delivered"]),
        ),
    ]

    for column, (label, value) in zip(
        second_row,
        second_metrics,
    ):
        with column:
            st.metric(label, value)

    st.divider()

    render_new_request_queue(
        engine,
        heading="New Requests Requiring Attention",
        show_owner_note=True,
    )

    st.divider()

    operations_pathway()


# ---------------------------------------------------------
# Page Definitions
# ---------------------------------------------------------
request_shipment = st.Page(
    "pages/Request_Shipment.py",
    title="Request Shipment",
    icon="📝",
)

manage_shipment = st.Page(
    "pages/Manage_Shipment.py",
    title="Manage Shipment",
    icon="🛠️",
)

schedule_pickup = st.Page(
    "pages/Schedule_Pickup.py",
    title="Schedule Pickup",
    icon="🚚",
)

shipment_status = st.Page(
    "pages/Track_Shipment.py",
    title="Shipment Status",
    icon="📦",
)

customer_home = st.Page(
    customer_home_page,
    title="Customer Home",
    icon="🏠",
    default=True,
)

my_payments = st.Page(
    "pages/My_Payments.py",
    title="My Payments",
    icon="💳",
)

contact_support = st.Page(
    "pages/Contact_Support.py",
    title="Contact Support",
    icon="☎️",
)

staff_home = st.Page(
    staff_home_page,
    title="Staff Home",
    icon="🏠",
    default=True,
)

staff_payment_lookup = st.Page(
    "pages/Payment_Lookup.py",
    title="Payment Lookup",
    icon="💳",
)


staff_support = st.Page(
    "pages/Contact_Support.py",
    title="Support Request",
    icon="☎️",
)

owner_command_center = st.Page(
    owner_command_center_page,
    title="Owner Command Center",
    icon="👑",
    default=True,
)

payments = st.Page(
    "pages/Payments.py",
    title="Payments",
    icon="💳",
)

reports = st.Page(
    "pages/Reports.py",
    title="Reports",
    icon="📄",
)

ai_assistant = st.Page(
    "pages/AI_Assistant.py",
    title="AI Assistant",
    icon="🤖",
)


# ---------------------------------------------------------
# Navigation
# ---------------------------------------------------------
# Reset the callable Home-page reference on every app rerun.
configure_portal_home_page(None)

if st.session_state.portal_mode is None:
    navigation = st.navigation(
        [
            st.Page(
                portal_selection_page,
                title="Select Portal",
                icon="🚪",
                default=True,
            )
        ]
    )

elif st.session_state.portal_mode == "staff_login":
    navigation = st.navigation(
        [
            st.Page(
                staff_login_page,
                title="Staff Login",
                icon="🔐",
                default=True,
            )
        ]
    )

elif st.session_state.portal_mode == "owner_login":
    navigation = st.navigation(
        [
            st.Page(
                owner_login_page,
                title="Owner Login",
                icon="🔐",
                default=True,
            )
        ]
    )

elif st.session_state.portal_mode == "customer":
    configure_portal_home_page(customer_home)
    render_back_to_portal_button()

    navigation = st.navigation(
        [
            customer_home,
            request_shipment,
            manage_shipment,
            shipment_status,
            my_payments,
            contact_support,
        ]
    )

elif st.session_state.portal_mode == "staff" and st.session_state.staff_authenticated:
    configure_portal_home_page(staff_home)
    render_back_to_portal_button()

    navigation = st.navigation(
        [
            staff_home,
            request_shipment,
            schedule_pickup,
            shipment_status,
            staff_payment_lookup,
            staff_support,
        ]
    )

elif st.session_state.portal_mode == "owner" and st.session_state.owner_authenticated:
    configure_portal_home_page(owner_command_center)
    render_back_to_portal_button()

    navigation = st.navigation(
        [
            owner_command_center,
            request_shipment,
            schedule_pickup,
            shipment_status,
            payments,
            reports,
            ai_assistant,
        ]
    )

else:
    st.session_state.portal_mode = None
    st.session_state.staff_authenticated = False
    st.session_state.owner_authenticated = False
    st.rerun()


navigation.run()