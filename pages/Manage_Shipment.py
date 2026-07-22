from __future__ import annotations

from datetime import datetime
from random import randint

import pandas as pd
import streamlit as st

from src.data_loader import load_shipment_change_history, load_shipments
from src.styles import apply_custom_styles, hero, sidebar_shipping_options


st.set_page_config(
    page_title="Manage Shipment",
    page_icon="🛠️",
    layout="wide",
)


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


def initialize_change_request_storage() -> None:
    """
    Store new customer change requests in session state for the MVP.
    Later, this should be saved to a database.
    """

    if "customer_change_requests" not in st.session_state:
        st.session_state.customer_change_requests = []


def generate_change_id() -> str:
    """
    Generate a simple change request ID for the MVP.
    """

    today = datetime.now().strftime("%Y%m%d")
    random_number = randint(1000, 9999)
    return f"CHG-REQ-{today}-{random_number}"


def filter_history_for_shipment(
    change_history: pd.DataFrame,
    shipment_id: str,
) -> pd.DataFrame:
    """
    Return change history for a selected shipment.
    """

    if change_history.empty or "shipment_id" not in change_history.columns:
        return pd.DataFrame()

    filtered = change_history[
        change_history["shipment_id"].astype(str).str.lower()
        == shipment_id.lower()
    ].copy()

    if "change_date" in filtered.columns:
        filtered = filtered.sort_values("change_date", ascending=False)

    return filtered


def get_session_history_for_shipment(shipment_id: str) -> pd.DataFrame:
    """
    Return customer change requests submitted during this app session.
    """

    records = st.session_state.get("customer_change_requests", [])

    if not records:
        return pd.DataFrame()

    session_df = pd.DataFrame(records)

    if "shipment_id" not in session_df.columns:
        return pd.DataFrame()

    session_df = session_df[
        session_df["shipment_id"].astype(str).str.lower()
        == shipment_id.lower()
    ].copy()

    if "change_date" in session_df.columns:
        session_df = session_df.sort_values("change_date", ascending=False)

    return session_df


def main() -> None:
    """
    Customer-facing Manage Shipment page.

    Customers can request shipment changes, pickup reschedules, or cancellations.
    Customers cannot directly approve, confirm, assign drivers, or mark pickups complete.
    Staff/Owner will review these requests later.
    """

    apply_custom_styles()
    sidebar_shipping_options()
    initialize_change_request_storage()

    shipments = load_shipments()
    change_history = load_shipment_change_history()

    hero(
        title="Manage Shipment",
        subtitle=(
            "Request a pickup reschedule, cancellation, contact update, or other shipment change. "
            "Solomon Shipping staff will review and confirm approved changes."
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

    if shipments.empty:
        st.warning("No shipment data found. Please check that shipments.csv is inside the data folder.")
        return

    if "shipment_id" not in shipments.columns:
        st.warning("The shipments file must include a shipment_id column.")
        return

    st.subheader("Find Your Shipment")

    shipment_ids = sorted(shipments["shipment_id"].dropna().astype(str).unique())

    lookup_col1, lookup_col2 = st.columns([2, 1])

    with lookup_col1:
        typed_shipment_id = st.text_input(
            "Enter Shipment ID",
            placeholder="Example: SST-2026-0001",
        )

    with lookup_col2:
        selected_shipment_id = st.selectbox(
            "Or select a shipment",
            options=[""] + shipment_ids,
        )

    shipment_id_to_lookup = typed_shipment_id.strip() or selected_shipment_id

    if not shipment_id_to_lookup:
        st.info("Enter or select a shipment ID to manage a shipment.")
        return

    matched_shipment = shipments[
        shipments["shipment_id"].astype(str).str.lower()
        == shipment_id_to_lookup.lower()
    ].copy()

    if matched_shipment.empty:
        st.error("No shipment found with that ID. Please check the shipment ID and try again.")
        return

    shipment_record = matched_shipment.iloc[0]

    customer_name = str(shipment_record.get("customer_name", "Not Available"))
    current_status = str(shipment_record.get("current_status", "Not Available"))
    destination_city = str(shipment_record.get("destination_city", "Not Available"))
    destination_country = str(shipment_record.get("destination_country", "Not Available"))
    estimated_delivery_date = str(shipment_record.get("estimated_delivery_date", "Not Available"))

    st.divider()

    st.subheader("Shipment Summary")

    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)

    with summary_col1:
        with st.container(border=True):
            st.markdown("#### Shipment ID")
            st.write(shipment_id_to_lookup)

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
            st.write(estimated_delivery_date)

    with st.container(border=True):
        st.markdown("#### Destination")
        st.write(f"{destination_city}, {destination_country}")

    st.divider()

    st.subheader("Request a Change")

    st.markdown(
        """
        Customers may request a change, but official schedule changes, cancellations,
        and approvals must be reviewed by Solomon Shipping staff or owner.
        """
    )

    with st.form("manage_shipment_form"):
        change_type = st.selectbox(
            "What would you like to request?",
            CHANGE_TYPES,
        )

        reason = ""

        new_pickup_date = None
        new_pickup_window = None
        updated_phone = ""
        updated_email = ""
        updated_notes = ""

        if change_type == "Request Pickup Reschedule":
            reschedule_col1, reschedule_col2 = st.columns(2)

            with reschedule_col1:
                new_pickup_date = st.date_input("Requested New Pickup Date")

            with reschedule_col2:
                new_pickup_window = st.selectbox(
                    "Requested New Pickup Window",
                    ["Morning", "Afternoon", "Evening", "Flexible"],
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
            contact_col1, contact_col2 = st.columns(2)

            with contact_col1:
                updated_phone = st.text_input("Updated Phone Number")

            with contact_col2:
                updated_email = st.text_input("Updated Email Address")

            reason = "Customer requested contact information update"

        elif change_type == "Update Pickup Notes":
            reason = "Customer updated pickup notes"

        else:
            reason = "Customer submitted general shipment change request"

        updated_notes = st.text_area(
            "Additional Details",
            placeholder="Explain what you need changed or add any helpful notes for Solomon Shipping staff.",
            height=130,
        )

        submitted = st.form_submit_button(
            "Submit Change Request",
            use_container_width=True,
        )

    if submitted:
        change_id = generate_change_id()

        if change_type == "Request Pickup Reschedule":
            old_value = "Existing pickup preference / schedule"
            new_value = f"{new_pickup_date} {new_pickup_window}"
            approval_status = "Pending"

        elif change_type == "Request Shipment Cancellation":
            old_value = current_status
            new_value = "Cancellation Requested"
            approval_status = "Pending"

        elif change_type == "Update Contact Information":
            old_value = "Existing contact information"
            new_value = f"Phone: {updated_phone}; Email: {updated_email}"
            approval_status = "Pending"

        elif change_type == "Update Pickup Notes":
            old_value = "Existing pickup notes"
            new_value = updated_notes
            approval_status = "Pending"

        else:
            old_value = "Existing shipment details"
            new_value = updated_notes
            approval_status = "Pending"

        change_record = {
            "change_id": change_id,
            "shipment_id": shipment_id_to_lookup,
            "customer_id": shipment_record.get("customer_id", ""),
            "customer_name": customer_name,
            "change_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "change_type": change_type,
            "old_value": old_value,
            "new_value": new_value,
            "requested_by": customer_name,
            "requested_role": "Customer",
            "request_reason": reason,
            "approval_status": approval_status,
            "approved_by": "",
            "approved_role": "",
            "approved_date": "",
            "notes": updated_notes,
        }

        st.session_state.customer_change_requests.append(change_record)

        st.success(
            f"Your change request has been submitted. Change Request ID: {change_id}"
        )

        st.info(
            "This request is pending Solomon Shipping staff review. "
            "For the MVP, this request is stored during the current app session. "
            "Later, it will be saved to the database and appear automatically for staff and owner approval."
        )

        st.markdown("### Submitted Change Request")
        st.dataframe(pd.DataFrame([change_record]), use_container_width=True)

    st.divider()

    st.subheader("Shipment Change History")

    existing_history = filter_history_for_shipment(
        change_history=change_history,
        shipment_id=shipment_id_to_lookup,
    )

    session_history = get_session_history_for_shipment(shipment_id_to_lookup)

    history_frames = []

    if not existing_history.empty:
        history_frames.append(existing_history)

    if not session_history.empty:
        history_frames.append(session_history)

    if history_frames:
        full_history = pd.concat(history_frames, ignore_index=True)

        if "change_date" in full_history.columns:
            full_history = full_history.sort_values("change_date", ascending=False)

        st.dataframe(full_history, use_container_width=True)
    else:
        st.info("No change history found for this shipment yet.")

    st.divider()

    st.subheader("What Happens Next?")

    next_col1, next_col2, next_col3 = st.columns(3)

    with next_col1:
        with st.container(border=True):
            st.markdown("### 1. Request Submitted")
            st.write("Your change request is recorded as pending.")

    with next_col2:
        with st.container(border=True):
            st.markdown("### 2. Staff Review")
            st.write("Solomon Shipping staff reviews the request and confirms next steps.")

    with next_col3:
        with st.container(border=True):
            st.markdown("### 3. Update Confirmed")
            st.write("Approved updates are reflected in shipment or pickup status.")


if __name__ == "__main__":
    main()