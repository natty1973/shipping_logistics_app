from __future__ import annotations

import streamlit as st

from src.data_loader import load_all_data
from src.metrics import (
    get_total_customers,
    get_total_shipments,
    get_pending_pickups,
    get_in_transit_shipments,
    get_delivered_shipments,
    get_total_revenue_collected,
    get_total_outstanding_balance,
)
from src.styles import (
    apply_custom_styles,
    configure_portal_home_page,
    hero,
    operations_pathway,
    sidebar_shipping_options,
)
from src.utils import format_currency


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
    """
    Staff-facing landing page.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    hero(
        title="Staff Portal",
        subtitle=(
            "Support customers, enter shipment requests, schedule pickups, check shipment status, "
            "and help with payment lookup without accessing owner-level financial analytics."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Staff Operations</span>
        <span class="badge-dark">Customer Support</span>
        <span class="badge-red">Limited Internal View</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    st.subheader("Staff Tools")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True):
            st.markdown("### 📝 Request Shipment")
            st.write(
                "Create a shipment request on behalf of a customer who calls, visits, or messages the office."
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
                "Confirm pickups, review reschedule/cancellation requests, assign drivers, and update pickup status."
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
                "Look up a shipment and help customers understand where their package is."
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
                "Look up an individual customer invoice or shipment payment status."
            )
            st.page_link(
                "pages/My_Payments.py",
                label="Open Payment Lookup",
                icon="➡️",
            )

    with col5:
        with st.container(border=True):
            st.markdown("### ☎️ Support Request")
            st.write(
                "Create a support request for shipment, pickup, payment, or delivery questions."
            )
            st.page_link(
                "pages/Contact_Support.py",
                label="Open Support Form",
                icon="➡️",
            )

    st.info(
        "Staff view is intentionally limited. Company-wide revenue, reports, and AI business analytics are available only in the Owner Portal."
    )


# ---------------------------------------------------------
# Owner Command Center
# ---------------------------------------------------------
def owner_command_center_page() -> None:
    """
    Owner command center.
    """

    apply_custom_styles()
    sidebar_shipping_options()

    data = load_all_data()

    customers = data["customers"]
    shipments = data["shipments"]
    pickups = data["pickups"]
    payments = data["payments"]

    hero(
        title="Owner Command Center",
        subtitle=(
            "Monitor shipments, pickups, customer activity, revenue, outstanding balances, "
            "reports, AI insights, and operational performance across Solomon Shipping."
        ),
    )

    st.markdown(
        """
        <span class="badge-green">Owner Portal</span>
        <span class="badge-dark">Business Intelligence</span>
        <span class="badge-red">Financial Dashboard</span>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Customers", get_total_customers(customers))

    with col2:
        st.metric("Shipments", get_total_shipments(shipments))

    with col3:
        st.metric(
            "Revenue Collected",
            format_currency(get_total_revenue_collected(payments)),
        )

    with col4:
        st.metric(
            "Outstanding Balance",
            format_currency(get_total_outstanding_balance(payments)),
        )

    col5, col6, col7 = st.columns(3)

    with col5:
        st.metric("Pending Pickups", get_pending_pickups(pickups))

    with col6:
        st.metric("In Transit", get_in_transit_shipments(shipments))

    with col7:
        st.metric("Delivered", get_delivered_shipments(shipments))

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