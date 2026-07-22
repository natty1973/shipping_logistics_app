from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from src.data_loader import load_branch_payments
from src.styles import apply_custom_styles, hero, sidebar_shipping_options
from src.utils import format_currency


st.set_page_config(
    page_title="Payment Lookup",
    page_icon="💳",
    layout="wide",
)


def initialize_payment_session_storage() -> None:
    """
    Store staff payment updates during the current MVP session.
    Later, these should be written to the database.
    """

    if "staff_payment_updates" not in st.session_state:
        st.session_state.staff_payment_updates = []


def get_portal_label() -> str:
    """
    Return the portal role.
    """

    portal_mode = st.session_state.get("portal_mode", "")

    if portal_mode == "owner":
        return "Owner"

    if portal_mode == "staff":
        return "Staff"

    return "Staff"


def safe_money(value: object) -> float:
    """
    Convert value to a safe float.
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def search_payments(branch_payments: pd.DataFrame, lookup_value: str) -> pd.DataFrame:
    """
    Search branch payments by shipment, invoice, sender, receiver, status, or notes.
    """

    if branch_payments.empty or not lookup_value:
        return pd.DataFrame()

    search_columns = [
        "shipment_id",
        "invoice_number",
        "sender_name",
        "receiver_name",
        "payment_terms",
        "payment_responsibility",
        "payment_status",
        "release_status",
        "payment_collected_at",
        "collected_by",
        "notes",
    ]

    available_columns = [col for col in search_columns if col in branch_payments.columns]

    if not available_columns:
        return pd.DataFrame()

    search_text = branch_payments[available_columns].astype(str).agg(" ".join, axis=1)

    return branch_payments[
        search_text.str.lower().str.contains(lookup_value.lower(), na=False)
    ].copy()


def calculate_updated_payment(
    current_record: pd.Series,
    payment_location: str,
    amount_received: float,
) -> dict[str, object]:
    """
    Calculate updated branch payment amounts and release status.
    """

    amount_charged = safe_money(current_record.get("amount_charged", 0))
    current_paid_nj = safe_money(current_record.get("amount_paid_nj", 0))
    current_paid_guyana = safe_money(current_record.get("amount_paid_guyana", 0))

    updated_paid_nj = current_paid_nj
    updated_paid_guyana = current_paid_guyana

    if payment_location == "New Jersey Branch":
        updated_paid_nj += amount_received
    else:
        updated_paid_guyana += amount_received

    updated_total_paid = updated_paid_nj + updated_paid_guyana
    updated_balance_due = max(amount_charged - updated_total_paid, 0)

    if updated_balance_due <= 0:
        updated_payment_status = "Paid"
        updated_release_status = "Cleared for Pickup"
    elif updated_total_paid > 0:
        updated_payment_status = "Partial"
        updated_release_status = "Hold Until Balance Paid"
    else:
        updated_payment_status = "Unpaid"
        updated_release_status = "Hold Until Paid"

    return {
        "amount_charged": amount_charged,
        "previous_paid_nj": current_paid_nj,
        "previous_paid_guyana": current_paid_guyana,
        "updated_paid_nj": updated_paid_nj,
        "updated_paid_guyana": updated_paid_guyana,
        "updated_total_paid": updated_total_paid,
        "updated_balance_due": updated_balance_due,
        "updated_payment_status": updated_payment_status,
        "updated_release_status": updated_release_status,
    }


def main() -> None:
    """
    Staff-facing payment lookup and payment recording page.

    Staff can:
    - search one shipment or invoice
    - see payment terms
    - see balance due
    - record a payment preview
    - see release status

    Staff should not see company-wide totals or owner financial summaries.
    """

    apply_custom_styles()
    sidebar_shipping_options()
    initialize_payment_session_storage()

    role_label = get_portal_label()

    branch_payments = load_branch_payments()

    hero(
        title="Payment Lookup",
        subtitle=(
            "Look up an individual shipment or invoice, check payment terms, record branch payment, "
            "and confirm whether the barrel can be released."
        ),
    )

    st.markdown(
        f"""
        <span class="badge-green">{role_label} Payment Tool</span>
        <span class="badge-dark">Individual Shipment Lookup</span>
        <span class="badge-red">No Company-Wide Totals</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    if branch_payments.empty:
        st.warning(
            "No branch payment data found. Please confirm branch_payments.csv is inside the data folder."
        )
        return

    st.subheader("Find Shipment Payment")

    lookup_value = st.text_input(
        "Search by shipment ID, invoice number, sender, receiver, payment status, or release status",
        placeholder="Example: SST-2026-0002, INV-2026-0002, receiver name, freight collect",
    )

    if not lookup_value:
        st.info("Enter a shipment ID, invoice number, sender, or receiver to look up payment information.")
        return

    matched_payments = search_payments(branch_payments, lookup_value)

    if matched_payments.empty:
        st.error("No matching payment record found.")
        return

    st.markdown("### Matching Payment Records")

    display_columns = [
        "shipment_id",
        "invoice_number",
        "sender_name",
        "receiver_name",
        "payment_terms",
        "payment_responsibility",
        "amount_charged",
        "amount_paid_nj",
        "amount_paid_guyana",
        "total_amount_paid",
        "balance_due",
        "payment_status",
        "release_status",
        "payment_collected_at",
        "notes",
    ]

    available_display_columns = [
        col for col in display_columns if col in matched_payments.columns
    ]

    st.dataframe(
        matched_payments[available_display_columns],
        use_container_width=True,
    )

    st.divider()

    st.subheader("Select Record to Review / Record Payment")

    record_options = matched_payments["shipment_id"].dropna().astype(str).unique().tolist()

    selected_shipment_id = st.selectbox(
        "Select Shipment ID",
        options=record_options,
    )

    selected_record_df = matched_payments[
        matched_payments["shipment_id"].astype(str) == selected_shipment_id
    ].copy()

    if selected_record_df.empty:
        st.error("Selected shipment record could not be found.")
        return

    record = selected_record_df.iloc[0]

    amount_charged = safe_money(record.get("amount_charged", 0))
    amount_paid_nj = safe_money(record.get("amount_paid_nj", 0))
    amount_paid_guyana = safe_money(record.get("amount_paid_guyana", 0))
    total_paid = safe_money(record.get("total_amount_paid", 0))
    balance_due = safe_money(record.get("balance_due", 0))

    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)

    with summary_col1:
        st.metric("Amount Charged", format_currency(amount_charged))

    with summary_col2:
        st.metric("Paid in NJ", format_currency(amount_paid_nj))

    with summary_col3:
        st.metric("Paid in Guyana", format_currency(amount_paid_guyana))

    with summary_col4:
        st.metric("Balance Due", format_currency(balance_due))

    detail_col1, detail_col2, detail_col3 = st.columns(3)

    with detail_col1:
        with st.container(border=True):
            st.markdown("#### Payment Terms")
            st.write(record.get("payment_terms", "Not Available"))

    with detail_col2:
        with st.container(border=True):
            st.markdown("#### Payment Status")
            st.write(record.get("payment_status", "Not Available"))

    with detail_col3:
        with st.container(border=True):
            st.markdown("#### Release Status")
            st.write(record.get("release_status", "Not Available"))

    if balance_due <= 0:
        st.success("This shipment appears fully paid and can be released if all other shipment conditions are met.")
    else:
        st.warning("This shipment has a remaining balance. Do not release until payment is completed or approved.")

    st.divider()

    st.subheader("Record Payment")

    with st.form("staff_record_payment_form"):
        col1, col2 = st.columns(2)

        with col1:
            payment_location = st.selectbox(
                "Payment Collected At",
                [
                    "New Jersey Branch",
                    "Guyana Office",
                ],
            )

            payment_method = st.selectbox(
                "Payment Method",
                [
                    "Cash",
                    "Card",
                    "Zelle",
                    "Bank Transfer",
                    "Mobile Money",
                    "Other",
                ],
            )

            amount_received = st.number_input(
                "Amount Received",
                min_value=0.0,
                step=5.0,
                value=0.0,
            )

        with col2:
            collected_by = st.text_input(
                "Collected By",
                value=role_label,
            )

            payment_date = st.date_input("Payment Date")

            receipt_number = st.text_input(
                "Receipt Number, if available",
                placeholder="Example: RCPT-1001",
            )

        payment_notes = st.text_area(
            "Payment Notes",
            placeholder="Add payment details, receipt notes, receiver/sender notes, or release instructions.",
            height=120,
        )

        submitted = st.form_submit_button(
            "Preview Payment Update",
            use_container_width=True,
        )

    if submitted:
        if amount_received <= 0:
            st.error("Please enter an amount received greater than 0.")
            return

        calculated = calculate_updated_payment(
            current_record=record,
            payment_location=payment_location,
            amount_received=amount_received,
        )

        payment_update_record = {
            "shipment_id": selected_shipment_id,
            "invoice_number": record.get("invoice_number", ""),
            "sender_name": record.get("sender_name", ""),
            "receiver_name": record.get("receiver_name", ""),
            "payment_terms": record.get("payment_terms", ""),
            "payment_location": payment_location,
            "payment_method": payment_method,
            "amount_received": amount_received,
            "collected_by": collected_by,
            "collected_by_role": role_label,
            "payment_date": str(payment_date),
            "receipt_number": receipt_number,
            "previous_paid_nj": calculated["previous_paid_nj"],
            "previous_paid_guyana": calculated["previous_paid_guyana"],
            "updated_paid_nj": calculated["updated_paid_nj"],
            "updated_paid_guyana": calculated["updated_paid_guyana"],
            "updated_total_paid": calculated["updated_total_paid"],
            "updated_balance_due": calculated["updated_balance_due"],
            "updated_payment_status": calculated["updated_payment_status"],
            "updated_release_status": calculated["updated_release_status"],
            "payment_notes": payment_notes,
            "update_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        st.session_state.staff_payment_updates.append(payment_update_record)

        st.success("Payment update preview saved for this session.")

        st.markdown("### Payment Update Preview")
        st.dataframe(pd.DataFrame([payment_update_record]), use_container_width=True)

        if calculated["updated_balance_due"] <= 0:
            st.success("After this payment, the shipment would be marked as paid and cleared for pickup/release.")
        else:
            st.warning(
                f"After this payment, the remaining balance would be "
                f"{format_currency(calculated['updated_balance_due'])}."
            )

        st.info(
            "MVP note: this payment update is stored only during the current app session. "
            "Later, it will update the branch_payments table/database and create a payment history record."
        )

    st.divider()

    st.subheader("Session Payment Updates")

    session_updates = st.session_state.get("staff_payment_updates", [])

    if session_updates:
        st.dataframe(pd.DataFrame(session_updates), use_container_width=True)
    else:
        st.info("No payment updates have been recorded in this session yet.")


if __name__ == "__main__":
    main()