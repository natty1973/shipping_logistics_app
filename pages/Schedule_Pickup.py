from __future__ import annotations

from datetime import datetime
from random import randint

import pandas as pd
import streamlit as st

from src.data_loader import (
    load_drivers,
    load_pickup_capacity,
    load_pickups,
    load_shipment_change_history,
    load_shipments,
)
from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(
    page_title="Schedule Pickup",
    page_icon="🚚",
    layout="wide",
)


PICKUP_STATUSES = [
    "Pending",
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


APPROVAL_DECISIONS = [
    "Approve",
    "Reject",
    "Needs Follow-Up",
]


CHANGE_TYPES_TO_REVIEW = [
    "Request Pickup Reschedule",
    "Request Shipment Cancellation",
    "Update Pickup Notes",
    "Update Contact Information",
    "General Shipment Change Request",
    "Reschedule Requested",
    "Cancellation Requested",
]


DEFAULT_PICKUP_AREAS = [
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


def initialize_pickup_session_storage() -> None:
    """
    Store staff/owner pickup updates during the current MVP session.
    Later, these records should be saved to a database.
    """

    if "pickup_updates" not in st.session_state:
        st.session_state.pickup_updates = []

    if "reviewed_change_requests" not in st.session_state:
        st.session_state.reviewed_change_requests = []


def generate_update_id(prefix: str = "PU") -> str:
    """
    Generate a simple update ID for the MVP.
    """

    today = datetime.now().strftime("%Y%m%d")
    random_number = randint(1000, 9999)
    return f"{prefix}-{today}-{random_number}"


def get_portal_label() -> str:
    """
    Return current user role based on portal mode.
    """

    portal_mode = st.session_state.get("portal_mode", "")

    if portal_mode == "owner":
        return "Owner"

    if portal_mode == "staff":
        return "Staff"

    return "Staff"


def safe_get(record: pd.Series, column: str, default: str = "Not Available") -> str:
    """
    Safely get a value from a pandas Series.
    """

    value = record.get(column, default)

    if pd.isna(value):
        return default

    return str(value)


def prepare_pickup_dataframe(pickups: pd.DataFrame) -> pd.DataFrame:
    """
    Standardize pickup dataframe display columns when available.
    """

    if pickups.empty:
        return pickups

    display_df = pickups.copy()

    preferred_columns = [
        "pickup_id",
        "shipment_id",
        "customer_id",
        "customer_name",
        "pickup_date",
        "pickup_window",
        "preferred_pickup_date",
        "preferred_pickup_window",
        "confirmed_pickup_date",
        "confirmed_pickup_window",
        "pickup_area",
        "pickup_address",
        "pickup_city",
        "pickup_state",
        "pickup_zip",
        "assigned_staff",
        "assigned_driver",
        "pickup_status",
        "driver_status",
        "customer_notified",
        "notes",
    ]

    available_columns = [col for col in preferred_columns if col in display_df.columns]

    if available_columns:
        return display_df[available_columns].copy()

    return display_df


def get_driver_options(drivers: pd.DataFrame) -> list[str]:
    """
    Create driver dropdown options from drivers.csv.
    """

    if drivers.empty or "driver_name" not in drivers.columns:
        return [
            "Unassigned",
            "Kevin Brown",
            "Dwayne Harris",
            "Alicia Grant",
            "Jason Clarke",
            "Other",
        ]

    active_drivers = drivers.copy()

    if "active_status" in active_drivers.columns:
        active_drivers = active_drivers[
            active_drivers["active_status"].astype(str).isin(["Active", "Backup"])
        ]

    driver_names = active_drivers["driver_name"].dropna().astype(str).tolist()

    return ["Unassigned"] + sorted(driver_names) + ["Other"]


def get_pickup_area_options(
    pickups: pd.DataFrame,
    pickup_capacity: pd.DataFrame,
) -> list[str]:
    """
    Create pickup area dropdown options using pickup_capacity, pickups, and defaults.
    """

    areas = set(DEFAULT_PICKUP_AREAS)

    if not pickup_capacity.empty and "pickup_area" in pickup_capacity.columns:
        areas.update(pickup_capacity["pickup_area"].dropna().astype(str).tolist())

    if not pickups.empty and "pickup_area" in pickups.columns:
        areas.update(pickups["pickup_area"].dropna().astype(str).tolist())

    return sorted(areas)


def filter_capacity(
    pickup_capacity: pd.DataFrame,
    pickup_area: str,
    pickup_date: str,
) -> pd.DataFrame:
    """
    Return capacity record for selected pickup area and date.
    """

    if pickup_capacity.empty:
        return pd.DataFrame()

    required_columns = ["pickup_area", "pickup_date"]

    if any(column not in pickup_capacity.columns for column in required_columns):
        return pd.DataFrame()

    filtered = pickup_capacity[
        (pickup_capacity["pickup_area"].astype(str).str.lower() == pickup_area.lower())
        & (pickup_capacity["pickup_date"].astype(str) == str(pickup_date))
    ].copy()

    return filtered


def render_capacity_status(capacity_record: pd.DataFrame) -> None:
    """
    Render capacity status cards for selected area/date.
    """

    if capacity_record.empty:
        st.info(
            "No capacity record found for this area/date. Staff can still schedule manually, "
            "but capacity should be reviewed."
        )
        return

    record = capacity_record.iloc[0]

    max_pickups = int(record.get("max_pickups", 0))
    scheduled_pickups = int(record.get("scheduled_pickups", 0))
    available_slots = int(record.get("available_slots", 0))
    capacity_status = str(record.get("capacity_status", "Not Available"))
    assigned_driver_ids = str(record.get("assigned_driver_ids", "Not Available"))

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Max Pickups", max_pickups)

    with col2:
        st.metric("Scheduled", scheduled_pickups)

    with col3:
        st.metric("Available Slots", available_slots)

    with col4:
        st.metric("Capacity Status", capacity_status)

    with st.container(border=True):
        st.markdown("#### Assigned Driver IDs")
        st.write(assigned_driver_ids)

    if capacity_status.lower() == "full" or available_slots <= 0:
        st.error(
            "This route/date is currently full. Consider choosing another date, "
            "adding a backup driver, or placing the pickup on a waitlist."
        )
    elif capacity_status.lower() == "limited":
        st.warning(
            "This route/date has limited availability. Confirm carefully before scheduling."
        )
    else:
        st.success("This route/date has pickup availability.")


def filter_pending_change_requests(change_history: pd.DataFrame) -> pd.DataFrame:
    """
    Return pending customer change requests that staff/owner may need to review.
    """

    if change_history.empty:
        return pd.DataFrame()

    filtered = change_history.copy()

    if "approval_status" in filtered.columns:
        filtered = filtered[
            filtered["approval_status"].astype(str).str.lower().eq("pending")
        ]

    if "change_type" in filtered.columns:
        filtered = filtered[
            filtered["change_type"].astype(str).isin(CHANGE_TYPES_TO_REVIEW)
        ]

    if "change_date" in filtered.columns:
        filtered = filtered.sort_values("change_date", ascending=False)

    return filtered


def get_session_customer_change_requests() -> pd.DataFrame:
    """
    Pull customer-submitted change requests from session state.
    These come from the customer Manage Shipment page during the current session.
    """

    records = st.session_state.get("customer_change_requests", [])

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    if "approval_status" in df.columns:
        df = df[df["approval_status"].astype(str).str.lower().eq("pending")]

    if "change_date" in df.columns:
        df = df.sort_values("change_date", ascending=False)

    return df


def combine_change_requests(
    csv_change_history: pd.DataFrame,
    session_change_requests: pd.DataFrame,
) -> pd.DataFrame:
    """
    Combine CSV-based pending requests with session-submitted requests.
    """

    frames = []

    if not csv_change_history.empty:
        frames.append(csv_change_history)

    if not session_change_requests.empty:
        frames.append(session_change_requests)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    if "change_date" in combined.columns:
        combined = combined.sort_values("change_date", ascending=False)

    return combined


def render_driver_directory(drivers: pd.DataFrame) -> None:
    """
    Show driver directory and service areas.
    """

    st.subheader("Driver Directory")

    if drivers.empty:
        st.info("No driver data found. Please check that drivers.csv is inside the data folder.")
        return

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

    available_columns = [column for column in display_columns if column in drivers.columns]

    st.dataframe(drivers[available_columns], use_container_width=True)


def render_capacity_board(pickup_capacity: pd.DataFrame) -> None:
    """
    Show pickup capacity board by area/date.
    """

    st.subheader("Pickup Capacity Board")

    if pickup_capacity.empty:
        st.info("No pickup capacity data found. Please check that pickup_capacity.csv is inside the data folder.")
        return

    filtered_capacity = pickup_capacity.copy()

    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        if "pickup_area" in filtered_capacity.columns:
            area_options = sorted(filtered_capacity["pickup_area"].dropna().astype(str).unique())
            selected_areas = st.multiselect(
                "Filter by Pickup Area",
                options=area_options,
                default=area_options,
            )

            filtered_capacity = filtered_capacity[
                filtered_capacity["pickup_area"].astype(str).isin(selected_areas)
            ]

    with filter_col2:
        if "capacity_status" in filtered_capacity.columns:
            status_options = sorted(filtered_capacity["capacity_status"].dropna().astype(str).unique())
            selected_statuses = st.multiselect(
                "Filter by Capacity Status",
                options=status_options,
                default=status_options,
            )

            filtered_capacity = filtered_capacity[
                filtered_capacity["capacity_status"].astype(str).isin(selected_statuses)
            ]

    if "pickup_date" in filtered_capacity.columns:
        filtered_capacity = filtered_capacity.sort_values(["pickup_date", "pickup_area"])

    st.dataframe(filtered_capacity, use_container_width=True)


def main() -> None:
    """
    Staff/Owner Schedule Pickup page.

    This page is for operational control:
    - review pickup requests
    - review area/date capacity
    - review driver availability
    - approve/reject customer change requests
    - assign driver/staff
    - update pickup status
    - mark pickups completed
    """

    apply_custom_styles()
    sidebar_shipping_options()
    initialize_pickup_session_storage()

    role_label = get_portal_label()

    pickups = load_pickups()
    shipments = load_shipments()
    drivers = load_drivers()
    pickup_capacity = load_pickup_capacity()
    change_history = load_shipment_change_history()

    hero(
        title="Schedule Pickup",
        subtitle=(
            "Review pickup requests, check route capacity, assign drivers, confirm pickup windows, "
            "approve customer changes, and update pickup status."
        ),
    )

    st.markdown(
        f"""
        <span class="badge-green">{role_label} Operations</span>
        <span class="badge-dark">Pickup Scheduling</span>
        <span class="badge-red">Driver Capacity</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    # ---------------------------------------------------------
    # Dispatch Overview
    # ---------------------------------------------------------
    st.subheader("Dispatch Overview")

    total_drivers = len(drivers) if not drivers.empty else 0

    active_drivers = 0
    if not drivers.empty and "active_status" in drivers.columns:
        active_drivers = int(drivers["active_status"].astype(str).eq("Active").sum())

    total_capacity = 0
    scheduled_pickups = 0
    available_slots = 0

    if not pickup_capacity.empty:
        if "max_pickups" in pickup_capacity.columns:
            total_capacity = int(pickup_capacity["max_pickups"].fillna(0).sum())

        if "scheduled_pickups" in pickup_capacity.columns:
            scheduled_pickups = int(pickup_capacity["scheduled_pickups"].fillna(0).sum())

        if "available_slots" in pickup_capacity.columns:
            available_slots = int(pickup_capacity["available_slots"].fillna(0).sum())

    pending_changes = combine_change_requests(
        csv_change_history=filter_pending_change_requests(change_history),
        session_change_requests=get_session_customer_change_requests(),
    )

    overview_col1, overview_col2, overview_col3, overview_col4 = st.columns(4)

    with overview_col1:
        st.metric("Total Drivers", total_drivers)

    with overview_col2:
        st.metric("Active Drivers", active_drivers)

    with overview_col3:
        st.metric("Available Slots", available_slots)

    with overview_col4:
        st.metric("Pending Changes", len(pending_changes))

    st.divider()

    # ---------------------------------------------------------
    # Capacity and Driver Tabs
    # ---------------------------------------------------------
    top_tabs = st.tabs(
        [
            "Pickup Work Queue",
            "Capacity Board",
            "Driver Directory",
            "Customer Change Requests",
            "Session Activity",
        ]
    )

    # ---------------------------------------------------------
    # Pickup Work Queue
    # ---------------------------------------------------------
    with top_tabs[0]:
        if pickups.empty:
            st.warning("No pickup schedule data found. Please check that pickup_schedule.csv is inside the data folder.")
        else:
            st.subheader("Pickup Work Queue")

            st.markdown(
                """
                Use this section to look up a pickup, check route capacity, assign a driver,
                confirm pickup timing, update status, or mark pickup completed.
                """
            )

            lookup_options = []

            if "pickup_id" in pickups.columns:
                lookup_options.extend(pickups["pickup_id"].dropna().astype(str).tolist())

            if "shipment_id" in pickups.columns:
                lookup_options.extend(pickups["shipment_id"].dropna().astype(str).tolist())

            lookup_options = sorted(set(lookup_options))

            lookup_col1, lookup_col2 = st.columns([2, 1])

            with lookup_col1:
                search_term = st.text_input(
                    "Search pickup ID, shipment ID, customer name, address, area, assigned driver, or status",
                )

            with lookup_col2:
                selected_lookup = st.selectbox(
                    "Or select pickup/shipment",
                    options=[""] + lookup_options,
                )

            filtered_pickups = pickups.copy()

            lookup_value = search_term.strip() or selected_lookup

            if lookup_value:
                searchable_columns = [
                    "pickup_id",
                    "shipment_id",
                    "customer_id",
                    "customer_name",
                    "pickup_address",
                    "pickup_city",
                    "pickup_state",
                    "pickup_zip",
                    "pickup_area",
                    "assigned_staff",
                    "assigned_driver",
                    "pickup_status",
                    "driver_status",
                    "notes",
                ]

                available_search_columns = [
                    col for col in searchable_columns if col in filtered_pickups.columns
                ]

                if available_search_columns:
                    search_text = filtered_pickups[available_search_columns].astype(str).agg(
                        " ".join,
                        axis=1,
                    )

                    filtered_pickups = filtered_pickups[
                        search_text.str.lower().str.contains(
                            lookup_value.lower(),
                            na=False,
                        )
                    ]

            st.markdown("### Pickup Records")

            if filtered_pickups.empty:
                st.info("No pickup records matched your search.")
            else:
                st.dataframe(
                    prepare_pickup_dataframe(filtered_pickups),
                    use_container_width=True,
                )

            st.divider()

            st.subheader("Update Pickup")

            if filtered_pickups.empty:
                st.info("Search for or select a pickup record above to update pickup details.")
            else:
                selected_record_options = []

                if "pickup_id" in filtered_pickups.columns:
                    selected_record_options = (
                        filtered_pickups["pickup_id"].dropna().astype(str).unique().tolist()
                    )
                    selected_label = "Select Pickup ID"
                    selected_column = "pickup_id"
                elif "shipment_id" in filtered_pickups.columns:
                    selected_record_options = (
                        filtered_pickups["shipment_id"].dropna().astype(str).unique().tolist()
                    )
                    selected_label = "Select Shipment ID"
                    selected_column = "shipment_id"
                else:
                    selected_record_options = filtered_pickups.index.astype(str).tolist()
                    selected_label = "Select Record"
                    selected_column = None

                selected_record_id = st.selectbox(
                    selected_label,
                    options=selected_record_options,
                )

                if selected_column:
                    selected_pickup_df = filtered_pickups[
                        filtered_pickups[selected_column].astype(str) == selected_record_id
                    ].copy()
                else:
                    selected_pickup_df = filtered_pickups.loc[
                        [int(selected_record_id)]
                    ].copy()

                if not selected_pickup_df.empty:
                    pickup_record = selected_pickup_df.iloc[0]

                    pickup_id = safe_get(pickup_record, "pickup_id", selected_record_id)
                    shipment_id = safe_get(pickup_record, "shipment_id")
                    customer_name = safe_get(pickup_record, "customer_name")
                    current_pickup_status = safe_get(pickup_record, "pickup_status", "Pending")
                    current_pickup_date = safe_get(pickup_record, "pickup_date", "")
                    current_pickup_window = safe_get(pickup_record, "pickup_window", "Flexible")
                    current_pickup_area = safe_get(pickup_record, "pickup_area", "Other")
                    current_driver_status = safe_get(pickup_record, "driver_status", "Not Available")
                    current_assigned_driver = safe_get(pickup_record, "assigned_driver", "Unassigned")

                    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)

                    with summary_col1:
                        with st.container(border=True):
                            st.markdown("#### Pickup ID")
                            st.write(pickup_id)

                    with summary_col2:
                        with st.container(border=True):
                            st.markdown("#### Shipment ID")
                            st.write(shipment_id)

                    with summary_col3:
                        with st.container(border=True):
                            st.markdown("#### Customer")
                            st.write(customer_name)

                    with summary_col4:
                        with st.container(border=True):
                            st.markdown("#### Current Status")
                            st.write(current_pickup_status)

                    st.markdown("### Check Capacity Before Scheduling")

                    capacity_col1, capacity_col2 = st.columns(2)

                    pickup_area_options = get_pickup_area_options(
                        pickups=pickups,
                        pickup_capacity=pickup_capacity,
                    )

                    if current_pickup_area not in pickup_area_options:
                        pickup_area_options.append(current_pickup_area)

                    with capacity_col1:
                        selected_pickup_area = st.selectbox(
                            "Pickup Area",
                            pickup_area_options,
                            index=(
                                pickup_area_options.index(current_pickup_area)
                                if current_pickup_area in pickup_area_options
                                else 0
                            ),
                        )

                    with capacity_col2:
                        selected_capacity_date = st.date_input(
                            "Pickup Date for Capacity Check",
                        )

                    capacity_record = filter_capacity(
                        pickup_capacity=pickup_capacity,
                        pickup_area=selected_pickup_area,
                        pickup_date=str(selected_capacity_date),
                    )

                    render_capacity_status(capacity_record)

                    st.divider()

                    with st.form("pickup_update_form"):
                        st.markdown("### Confirm / Update Pickup Details")

                        update_col1, update_col2 = st.columns(2)

                        with update_col1:
                            confirmed_pickup_date = st.date_input(
                                "Confirmed Pickup Date",
                                value=selected_capacity_date,
                            )

                            confirmed_pickup_window = st.selectbox(
                                "Confirmed Pickup Window",
                                PICKUP_WINDOWS,
                                index=(
                                    PICKUP_WINDOWS.index(current_pickup_window)
                                    if current_pickup_window in PICKUP_WINDOWS
                                    else 0
                                ),
                            )

                            pickup_status = st.selectbox(
                                "Pickup Status",
                                PICKUP_STATUSES,
                                index=(
                                    PICKUP_STATUSES.index(current_pickup_status)
                                    if current_pickup_status in PICKUP_STATUSES
                                    else 0
                                ),
                            )

                            updated_pickup_area = st.selectbox(
                                "Confirmed Pickup Area",
                                pickup_area_options,
                                index=(
                                    pickup_area_options.index(selected_pickup_area)
                                    if selected_pickup_area in pickup_area_options
                                    else 0
                                ),
                            )

                        with update_col2:
                            driver_options = get_driver_options(drivers)

                            assigned_driver = st.selectbox(
                                "Assign Driver / Staff",
                                driver_options,
                                index=(
                                    driver_options.index(current_assigned_driver)
                                    if current_assigned_driver in driver_options
                                    else 0
                                ),
                            )

                            custom_driver = ""

                            if assigned_driver == "Other":
                                custom_driver = st.text_input("Enter Driver / Staff Name")

                            driver_status = st.selectbox(
                                "Driver Status",
                                [
                                    "Not Assigned",
                                    "Assigned",
                                    "On the Way",
                                    "Arrived",
                                    "Picked Up",
                                    "Delayed",
                                    "Completed",
                                ],
                                index=0,
                            )

                            customer_notified = st.checkbox("Customer Notified")

                            mark_completed = st.checkbox("Mark Pickup Completed")

                        internal_notes = st.text_area(
                            "Internal Pickup Notes",
                            placeholder="Add staff notes about pickup confirmation, driver assignment, customer contact, route capacity, or completion details.",
                            height=120,
                        )

                        update_submitted = st.form_submit_button(
                            "Save Pickup Update",
                            use_container_width=True,
                        )

                    if update_submitted:
                        final_driver = (
                            custom_driver.strip()
                            if assigned_driver == "Other"
                            else assigned_driver
                        )

                        final_status = "Completed" if mark_completed else pickup_status

                        update_id = generate_update_id("PU-UPD")

                        update_record = {
                            "update_id": update_id,
                            "pickup_id": pickup_id,
                            "shipment_id": shipment_id,
                            "customer_name": customer_name,
                            "update_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "updated_by_role": role_label,
                            "pickup_area": updated_pickup_area,
                            "confirmed_pickup_date": str(confirmed_pickup_date),
                            "confirmed_pickup_window": confirmed_pickup_window,
                            "assigned_driver": final_driver,
                            "pickup_status": final_status,
                            "driver_status": driver_status,
                            "customer_notified": customer_notified,
                            "internal_notes": internal_notes,
                        }

                        st.session_state.pickup_updates.append(update_record)

                        st.success(f"Pickup update saved. Update ID: {update_id}")

                        st.markdown("### Saved Pickup Update")
                        st.dataframe(pd.DataFrame([update_record]), use_container_width=True)

                        st.info(
                            "MVP note: this update is stored during the current app session. "
                            "Later, this will update the pickup schedule table in the database."
                        )

    # ---------------------------------------------------------
    # Capacity Board
    # ---------------------------------------------------------
    with top_tabs[1]:
        render_capacity_board(pickup_capacity)

    # ---------------------------------------------------------
    # Driver Directory
    # ---------------------------------------------------------
    with top_tabs[2]:
        render_driver_directory(drivers)

    # ---------------------------------------------------------
    # Customer Change Requests Review
    # ---------------------------------------------------------
    with top_tabs[3]:
        st.subheader("Customer Change Requests for Review")

        st.markdown(
            """
            Review customer requests for pickup reschedule, shipment cancellation,
            contact updates, or other shipment changes. Staff and owner users can approve,
            reject, or mark requests for follow-up.
            """
        )

        pending_csv_requests = filter_pending_change_requests(change_history)
        pending_session_requests = get_session_customer_change_requests()

        pending_requests = combine_change_requests(
            csv_change_history=pending_csv_requests,
            session_change_requests=pending_session_requests,
        )

        if pending_requests.empty:
            st.success("There are no pending customer change requests at this time.")
        else:
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

            available_display_columns = [
                col for col in display_columns if col in pending_requests.columns
            ]

            st.dataframe(
                pending_requests[available_display_columns],
                use_container_width=True,
            )

            st.markdown("### Review a Change Request")

            change_ids = pending_requests["change_id"].dropna().astype(str).unique().tolist()

            selected_change_id = st.selectbox(
                "Select Change Request",
                options=change_ids,
            )

            selected_change_df = pending_requests[
                pending_requests["change_id"].astype(str) == selected_change_id
            ].copy()

            if not selected_change_df.empty:
                selected_change = selected_change_df.iloc[0]

                review_col1, review_col2, review_col3 = st.columns(3)

                with review_col1:
                    with st.container(border=True):
                        st.markdown("#### Shipment ID")
                        st.write(safe_get(selected_change, "shipment_id"))

                with review_col2:
                    with st.container(border=True):
                        st.markdown("#### Change Type")
                        st.write(safe_get(selected_change, "change_type"))

                with review_col3:
                    with st.container(border=True):
                        st.markdown("#### Requested By")
                        st.write(safe_get(selected_change, "requested_by"))

                with st.form("change_request_review_form"):
                    decision = st.selectbox(
                        "Decision",
                        APPROVAL_DECISIONS,
                    )

                    reviewer_name = st.text_input(
                        "Reviewed By",
                        value=role_label,
                    )

                    review_notes = st.text_area(
                        "Review Notes",
                        placeholder="Add approval, rejection, follow-up, or customer communication notes.",
                        height=120,
                    )

                    review_submitted = st.form_submit_button(
                        "Save Review Decision",
                        use_container_width=True,
                    )

                if review_submitted:
                    review_id = generate_update_id("REV")

                    approval_status = {
                        "Approve": "Approved",
                        "Reject": "Rejected",
                        "Needs Follow-Up": "Needs Follow-Up",
                    }[decision]

                    review_record = {
                        "review_id": review_id,
                        "change_id": selected_change_id,
                        "shipment_id": safe_get(selected_change, "shipment_id"),
                        "customer_name": safe_get(selected_change, "customer_name"),
                        "change_type": safe_get(selected_change, "change_type"),
                        "old_value": safe_get(selected_change, "old_value"),
                        "new_value": safe_get(selected_change, "new_value"),
                        "reviewed_by": reviewer_name,
                        "reviewed_by_role": role_label,
                        "review_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "approval_status": approval_status,
                        "review_notes": review_notes,
                    }

                    st.session_state.reviewed_change_requests.append(review_record)

                    st.success(f"Review decision saved. Review ID: {review_id}")

                    st.markdown("### Review Summary")
                    st.dataframe(pd.DataFrame([review_record]), use_container_width=True)

                    st.info(
                        "MVP note: this review is stored during the current app session. "
                        "Later, this will update the shipment change history table and notify the customer."
                    )

    # ---------------------------------------------------------
    # Session Activity
    # ---------------------------------------------------------
    with top_tabs[4]:
        st.subheader("Session Activity")

        activity_tabs = st.tabs(
            [
                "Pickup Updates",
                "Reviewed Change Requests",
                "CSV Change History",
                "Pickup Capacity Data",
                "Drivers Data",
            ]
        )

        with activity_tabs[0]:
            pickup_updates = st.session_state.get("pickup_updates", [])

            if pickup_updates:
                st.dataframe(pd.DataFrame(pickup_updates), use_container_width=True)
            else:
                st.info("No pickup updates have been saved in this session.")

        with activity_tabs[1]:
            reviewed_requests = st.session_state.get("reviewed_change_requests", [])

            if reviewed_requests:
                st.dataframe(pd.DataFrame(reviewed_requests), use_container_width=True)
            else:
                st.info("No change requests have been reviewed in this session.")

        with activity_tabs[2]:
            if change_history.empty:
                st.info("No shipment change history file found.")
            else:
                display_history = change_history.copy()

                if "change_date" in display_history.columns:
                    display_history = display_history.sort_values("change_date", ascending=False)

                st.dataframe(display_history, use_container_width=True)

        with activity_tabs[3]:
            if pickup_capacity.empty:
                st.info("No pickup capacity data found.")
            else:
                st.dataframe(pickup_capacity, use_container_width=True)

        with activity_tabs[4]:
            if drivers.empty:
                st.info("No driver data found.")
            else:
                st.dataframe(drivers, use_container_width=True)


if __name__ == "__main__":
    main()