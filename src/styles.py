from __future__ import annotations

from pathlib import Path

import streamlit as st


def apply_custom_styles() -> None:
    """
    Apply Solomon Shipping custom CSS styling across the Streamlit app.
    """

    st.markdown(
        """
        <style>
        /* ---------------------------------------------------------
           Main App Background
        --------------------------------------------------------- */
        .stApp {
            background: #F5F7FA;
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1250px;
        }

        /* ---------------------------------------------------------
           Premium Sidebar Styling
        --------------------------------------------------------- */
        section[data-testid="stSidebar"] {
            background:
                radial-gradient(circle at top left, rgba(247, 215, 116, 0.20), transparent 28%),
                linear-gradient(180deg, #053B2D 0%, #0B6E4F 42%, #06291F 76%, #111111 100%);
            border-right: 1px solid rgba(255,255,255,0.10);
            box-shadow: 10px 0 28px rgba(0,0,0,0.24);
            min-width: 340px !important;
            width: 340px !important;
        }

        section[data-testid="stSidebar"] > div {
            padding-top: 0.2rem !important;
            width: 340px !important;
        }

        section[data-testid="stSidebar"]::before {
            content: "🚚 Welcome Aboard";
            display: block;
            color: #F7D774;
            font-size: 1.38rem;
            font-weight: 950;
            line-height: 1.15;
            letter-spacing: -0.035em;
            padding: 0.55rem 1.15rem 0.05rem 1.15rem;
            margin-bottom: 0;
            text-shadow: 0 2px 4px rgba(0,0,0,0.35);
            font-family: "Segoe UI", "Inter", Arial, sans-serif;
        }

        section[data-testid="stSidebar"]::after {
            content: "Reliable shipping. Smooth tracking. Trusted delivery.";
            display: block;
            color: rgba(255,255,255,0.92);
            font-size: 0.82rem;
            font-weight: 750;
            line-height: 1.25;
            padding: 0.08rem 1.15rem 0.4rem 1.15rem;
            border-bottom: 1px solid rgba(255,255,255,0.14);
            margin-bottom: 0.2rem;
            font-family: "Segoe UI", "Inter", Arial, sans-serif;
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {
            padding-top: 0 !important;
        }

        section[data-testid="stSidebar"] ul {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }

        section[data-testid="stSidebar"] li {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }

        section[data-testid="stSidebar"] a {
            color: #FFF7D6 !important;
            font-size: 1.02rem !important;
            font-weight: 850 !important;
            letter-spacing: 0.005em;
            border-radius: 14px !important;
            padding: 0.58rem 0.85rem !important;
            margin: 0.06rem 0.62rem !important;
            transition: all 0.22s ease-in-out;
            font-family: "Segoe UI", "Inter", Arial, sans-serif !important;
            min-height: 0 !important;
        }

        section[data-testid="stSidebar"] a span,
        section[data-testid="stSidebar"] a p,
        section[data-testid="stSidebar"] a div {
            color: #FFF7D6 !important;
            font-size: 1.02rem !important;
            font-weight: 850 !important;
            font-family: "Segoe UI", "Inter", Arial, sans-serif !important;
            line-height: 1.15 !important;
        }

        section[data-testid="stSidebar"] a:hover {
            background: rgba(247, 215, 116, 0.16) !important;
            color: #FFFFFF !important;
            transform: translateX(3px);
            box-shadow: inset 3px 0 0 #F7D774;
        }

        section[data-testid="stSidebar"] a:hover span,
        section[data-testid="stSidebar"] a:hover p,
        section[data-testid="stSidebar"] a:hover div {
            color: #FFFFFF !important;
        }

        section[data-testid="stSidebar"] a[aria-current="page"] {
            background: linear-gradient(135deg, #F7D774 0%, #FFF2B8 100%) !important;
            color: #053B2D !important;
            font-weight: 950 !important;
            box-shadow: 0 8px 18px rgba(0,0,0,0.22);
            border: 1px solid rgba(255,255,255,0.75);
        }

        section[data-testid="stSidebar"] a[aria-current="page"] span,
        section[data-testid="stSidebar"] a[aria-current="page"] p,
        section[data-testid="stSidebar"] a[aria-current="page"] div {
            color: #053B2D !important;
            font-weight: 950 !important;
            font-size: 1.02rem !important;
        }

        section[data-testid="stSidebar"] button {
            color: #FFFFFF !important;
        }

        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p {
            color: #FFF7D6 !important;
            font-size: 0.9rem !important;
            font-family: "Segoe UI", "Inter", Arial, sans-serif !important;
            font-weight: 750 !important;
            line-height: 1.2 !important;
        }

        /* ---------------------------------------------------------
           Sidebar Shipping / Contact Panel
        --------------------------------------------------------- */
        .sidebar-shipping-panel {
            margin: 0.55rem 0.75rem 0.6rem 0.75rem;
            padding: 0.68rem 0.75rem;
            border-radius: 15px;
            background: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(247, 215, 116, 0.38);
            box-shadow: 0 8px 18px rgba(0,0,0,0.16);
            backdrop-filter: blur(6px);
        }

        .sidebar-shipping-title {
            color: #F7D774;
            font-size: 0.98rem;
            font-weight: 950;
            margin-bottom: 0.4rem;
            letter-spacing: -0.02em;
            white-space: nowrap;
        }

        .sidebar-shipping-item {
            color: #FFFFFF;
            font-size: 0.78rem;
            font-weight: 750;
            line-height: 1.25;
            margin-bottom: 0.24rem;
            white-space: nowrap;
        }

        .sidebar-shipping-footer {
            color: #F7D774;
            font-size: 0.75rem;
            font-weight: 900;
            margin-top: 0.45rem;
            padding-top: 0.42rem;
            border-top: 1px solid rgba(247, 215, 116, 0.28);
            letter-spacing: 0.01em;
            white-space: nowrap;
        }

        .sidebar-contact-title {
            color: #F7D774;
            font-size: 0.92rem;
            font-weight: 950;
            margin-top: 0.65rem;
            padding-top: 0.55rem;
            border-top: 1px solid rgba(247, 215, 116, 0.28);
        }

        .sidebar-contact-item {
            color: #FFFFFF;
            font-size: 0.77rem;
            font-weight: 750;
            line-height: 1.32;
            margin-top: 0.18rem;
        }

        /* ---------------------------------------------------------
           Headings
        --------------------------------------------------------- */
        h1, h2, h3 {
            color: #111111;
            font-family: "Segoe UI", "Inter", Arial, sans-serif;
            letter-spacing: -0.03em;
        }

        h1 {
            font-weight: 900;
        }

        h2 {
            font-weight: 850;
        }

        h3 {
            font-weight: 800;
        }

        /* ---------------------------------------------------------
           Branded Hero Section
        --------------------------------------------------------- */
        .hero-card {
            background:
                radial-gradient(circle at top right, rgba(255,255,255,0.10), transparent 22%),
                radial-gradient(circle at bottom left, rgba(247, 215, 116, 0.13), transparent 24%),
                linear-gradient(135deg, #0B6E4F 0%, #063D2D 38%, #111111 100%);
            padding: 2.5rem;
            border-radius: 24px;
            color: white;
            margin-bottom: 1.5rem;
            box-shadow: 0 18px 42px rgba(0,0,0,0.20);
            border: 1px solid rgba(255,255,255,0.12);
            position: relative;
            overflow: hidden;
        }

        .hero-card::before {
            content: "🚚";
            position: absolute;
            top: 1.3rem;
            right: 2rem;
            width: 78px;
            height: 78px;
            border-radius: 24px;
            background: rgba(247, 215, 116, 0.16);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.3rem;
            border: 1px solid rgba(247, 215, 116, 0.30);
            box-shadow: 0 12px 28px rgba(0,0,0,0.18);
        }

        .hero-card::after {
            content: "";
            position: absolute;
            bottom: -100px;
            left: -100px;
            width: 260px;
            height: 260px;
            background: rgba(193,18,31,0.16);
            border-radius: 50%;
        }

        .hero-title {
            position: relative;
            z-index: 2;
            font-size: 2.45rem;
            font-weight: 950;
            margin-bottom: 0.55rem;
            color: #F7D774;
            letter-spacing: -0.045em;
            text-shadow: 0 2px 4px rgba(0,0,0,0.24);
            max-width: 930px;
        }

        .hero-subtitle {
            position: relative;
            z-index: 2;
            font-size: 1.08rem;
            color: #F4F4F4;
            max-width: 950px;
            line-height: 1.6;
            font-weight: 500;
        }

        /* ---------------------------------------------------------
           Section Cards
        --------------------------------------------------------- */
        .section-card {
            background: #FFFFFF;
            padding: 1.25rem 1.35rem;
            border-radius: 18px;
            border-left: 6px solid #0B6E4F;
            box-shadow: 0 8px 22px rgba(0,0,0,0.07);
            margin-bottom: 1rem;
            min-height: 145px;
        }

        .section-card-red {
            background: #FFFFFF;
            padding: 1.25rem 1.35rem;
            border-radius: 18px;
            border-left: 6px solid #C1121F;
            box-shadow: 0 8px 22px rgba(0,0,0,0.07);
            margin-bottom: 1rem;
            min-height: 145px;
        }

        .section-title {
            font-size: 1.15rem;
            font-weight: 850;
            color: #111111;
            margin-bottom: 0.35rem;
        }

        .section-text {
            font-size: 0.94rem;
            color: #333333;
            line-height: 1.48;
        }

        /* ---------------------------------------------------------
           Metric Cards
        --------------------------------------------------------- */
        div[data-testid="stMetric"] {
            background-color: #FFFFFF;
            padding: 1rem;
            border-radius: 16px;
            border: 1px solid #E5E7EB;
            box-shadow: 0 8px 18px rgba(0,0,0,0.06);
        }

        div[data-testid="stMetricLabel"] {
            color: #333333;
            font-weight: 750;
        }

        div[data-testid="stMetricValue"] {
            color: #0B6E4F;
            font-weight: 950;
        }

        /* ---------------------------------------------------------
           Buttons
        --------------------------------------------------------- */
        .stButton > button {
            background-color: #0B6E4F;
            color: white;
            border-radius: 12px;
            border: none;
            padding: 0.6rem 1.25rem;
            font-weight: 850;
            box-shadow: 0 8px 16px rgba(11,110,79,0.18);
        }

        .stButton > button:hover {
            background-color: #084C38;
            color: white;
            border: none;
            transform: translateY(-1px);
        }

        .stDownloadButton > button {
            background-color: #C1121F;
            color: white;
            border-radius: 12px;
            border: none;
            padding: 0.6rem 1.25rem;
            font-weight: 850;
            box-shadow: 0 8px 16px rgba(193,18,31,0.18);
        }

        .stDownloadButton > button:hover {
            background-color: #8F0D17;
            color: white;
            border: none;
            transform: translateY(-1px);
        }

        /* Compact green customer receipt buttons */
        div[class*="st-key-customer_receipt_download"] .stDownloadButton > button {
            background: linear-gradient(135deg, #0B6E4F 0%, #084C38 100%) !important;
            color: #FFFFFF !important;
            border: 1px solid rgba(5, 59, 45, 0.22) !important;
            border-radius: 10px !important;
            padding: 0.48rem 0.72rem !important;
            min-height: 2.35rem !important;
            font-size: 0.82rem !important;
            font-weight: 900 !important;
            box-shadow: 0 6px 14px rgba(11, 110, 79, 0.20) !important;
            white-space: nowrap !important;
        }

        div[class*="st-key-customer_receipt_download"] .stDownloadButton > button:hover {
            background: linear-gradient(135deg, #084C38 0%, #053B2D 100%) !important;
            color: #FFFFFF !important;
            transform: translateY(-1px);
        }

        /* Small bottom-right home button */
        div[class*="st-key-back_to_home_bar"] .stButton > button {
            background: #0B6E4F !important;
            color: #FFFFFF !important;
            border-radius: 10px !important;
            padding: 0.48rem 0.72rem !important;
            font-size: 0.84rem !important;
            font-weight: 900 !important;
            min-height: 2.35rem !important;
            box-shadow: 0 6px 14px rgba(11, 110, 79, 0.18) !important;
            white-space: nowrap !important;
        }

        div[class*="st-key-back_to_home_bar"] .stButton > button:hover {
            background: #084C38 !important;
            color: #FFFFFF !important;
        }

        a[data-testid="stPageLink-NavLink"] {
            font-weight: 800;
            border-radius: 12px;
        }

        /* ---------------------------------------------------------
           Tables
        --------------------------------------------------------- */
        div[data-testid="stDataFrame"] {
            background: white;
            border-radius: 14px;
            padding: 0.3rem;
            box-shadow: 0 6px 16px rgba(0,0,0,0.04);
        }

        /* ---------------------------------------------------------
           Badges
        --------------------------------------------------------- */
        .badge-green {
            display: inline-block;
            background: #E6F4EF;
            color: #0B6E4F;
            padding: 0.38rem 0.72rem;
            border-radius: 999px;
            font-weight: 850;
            font-size: 0.84rem;
            margin-right: 0.35rem;
            border: 1px solid #CFE9DE;
        }

        .badge-red {
            display: inline-block;
            background: #FDECEC;
            color: #C1121F;
            padding: 0.38rem 0.72rem;
            border-radius: 999px;
            font-weight: 850;
            font-size: 0.84rem;
            margin-right: 0.35rem;
            border: 1px solid #F7CACA;
        }

        .badge-dark {
            display: inline-block;
            background: #111111;
            color: #FFFFFF;
            padding: 0.38rem 0.72rem;
            border-radius: 999px;
            font-weight: 850;
            font-size: 0.84rem;
            margin-right: 0.35rem;
            border: 1px solid #111111;
        }

        input, textarea {
            border-radius: 10px !important;
        }

        div[data-baseweb="select"] > div {
            border-radius: 10px !important;
        }

        /* ---------------------------------------------------------
           Developer Footer
        --------------------------------------------------------- */
        .stApp::after {
            content: "Developed by Niota Labs LLC";
            position: fixed;
            right: 18px;
            bottom: 10px;
            z-index: 9999;
            color: #053B2D;
            font-size: 0.86rem;
            font-weight: 900;
            font-family: "Segoe UI", "Inter", Arial, sans-serif;
            background: linear-gradient(135deg, #F7D774 0%, #FFF2B8 100%);
            padding: 0.38rem 0.78rem;
            border-radius: 999px;
            border: 1px solid rgba(5, 59, 45, 0.18);
            box-shadow: 0 6px 18px rgba(0,0,0,0.18);
            pointer-events: none;
            letter-spacing: 0.01em;
        }

        @media screen and (max-width: 900px) {
            .hero-title {
                font-size: 1.8rem;
            }

            .hero-card {
                padding: 1.6rem;
            }

            .hero-card::before {
                display: none;
            }

            section[data-testid="stSidebar"] {
                min-width: 300px !important;
                width: 300px !important;
            }

            section[data-testid="stSidebar"] > div {
                width: 300px !important;
            }

            section[data-testid="stSidebar"] a,
            section[data-testid="stSidebar"] a span,
            section[data-testid="stSidebar"] a p,
            section[data-testid="stSidebar"] a div {
                font-size: 1rem !important;
            }

            .sidebar-shipping-item,
            .sidebar-shipping-footer {
                white-space: normal;
            }

            .stApp::after {
                font-size: 0.72rem;
                right: 10px;
                bottom: 8px;
                padding: 0.3rem 0.6rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _home_script_path() -> str:
    """Return the first common Streamlit entrypoint found in the repo root."""

    for candidate in (
        "app.py",
        "Home.py",
        "home.py",
        "main.py",
        "streamlit_app.py",
    ):
        if Path(candidate).exists():
            return candidate

    return "app.py"


def sidebar_shipping_options() -> None:
    """
    Render shipping options and contact information in the sidebar
    using Streamlit-native components so raw HTML does not display.
    """

    with st.sidebar:
        st.markdown("### Our Shipping Options")

        st.markdown("✈️ **Express Air** — 3–5 Business Days")
        st.markdown("✈️ **Standard Air** — 7–10 Business Days")
        st.markdown("🚢 **Express Sea** — Approx. 3 Weeks")
        st.markdown("🚢 **Standard Sea** — 4–6 Weeks")

        st.markdown("**Fast • Reliable • Affordable Shipping**")

        st.divider()

        st.markdown("### Contact Information")
        st.markdown("**Solomon Shipping and Trading Inc.**")
        st.markdown("📍 200 Main St Rear")
        st.markdown("City of Orange, NJ 07050")
        st.markdown("☎️ 973-675-4921")

        portal_mode = st.session_state.get("portal_mode")

        if portal_mode in {
            "customer",
            "staff",
            "owner",
        }:
            st.divider()
            st.page_link(
                _home_script_path(),
                label="Back to Home",
                icon="🏠",
            )


def render_back_to_home(
    key: str = "back_to_home",
) -> None:
    """
    Render a compact bottom-right button that returns to the
    current portal's default home page through the app entrypoint.
    """

    st.write("")

    left, right = st.columns(
        [5.4, 1.35],
        vertical_alignment="bottom",
    )

    with right:
        with st.container(
            key=f"back_to_home_bar_{key}"
        ):
            if st.button(
                "🏠 Back to Home",
                key=key,
                use_container_width=True,
            ):
                st.switch_page(
                    _home_script_path()
                )


def hero(title: str, subtitle: str) -> None:
    """
    Render a branded hero banner.
    """

    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-title">{title}</div>
            <div class="hero-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_card(title: str, text: str, accent: str = "green") -> None:
    """
    Render a reusable section card.
    """

    card_class = "section-card-red" if accent == "red" else "section-card"

    st.markdown(
        f"""
        <div class="{card_class}">
            <div class="section-title">{title}</div>
            <div class="section-text">{text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def operations_pathway() -> None:
    """
    Render a clean, professional operations pathway using Streamlit-native layout.
    Each pathway card includes a link to the matching platform page.
    """

    st.markdown("## Solomon Shipping Operations Platform")
    st.markdown(
        """
        **From request to delivery — managed in one place.**  
        A connected logistics workflow designed to move shipments from customer request
        to pickup, tracking, payment review, reporting, and AI-assisted support.
        """
    )

    st.write("")

    col1, arrow1, col2, arrow2, col3 = st.columns([1.3, 0.25, 1.3, 0.25, 1.3])

    with col1:
        with st.container(border=True):
            st.markdown("### 📝 Request Shipment")
            st.write("Capture customer, destination, item, pickup, and shipment details.")
            st.page_link(
                "pages/Request_Shipment.py",
                label="Open Request Shipment",
                icon="➡️",
            )

    with arrow1:
        st.markdown(
            "<h2 style='text-align:center; color:#0B6E4F; margin-top:3rem;'>→</h2>",
            unsafe_allow_html=True,
        )

    with col2:
        with st.container(border=True):
            st.markdown("### 🚚 Schedule Pickup")
            st.write("Assign pickup dates, time windows, addresses, and staff.")
            st.page_link(
                "pages/Schedule_Pickup.py",
                label="Open Schedule Pickup",
                icon="➡️",
            )

    with arrow2:
        st.markdown(
            "<h2 style='text-align:center; color:#0B6E4F; margin-top:3rem;'>→</h2>",
            unsafe_allow_html=True,
        )

    with col3:
        with st.container(border=True):
            st.markdown("### 📦 Shipment Status")
            st.write("Monitor shipment movement from pickup through final delivery.")
            st.page_link(
                "pages/Track_Shipment.py",
                label="Open Shipment Status",
                icon="➡️",
            )

    st.write("")

    col4, arrow3, col5, arrow4, col6 = st.columns([1.3, 0.25, 1.3, 0.25, 1.3])

    with col4:
        with st.container(border=True):
            st.markdown("### 💳 Payments")
            st.write("Review invoices, balances, partial payments, and collected revenue.")
            st.page_link(
                "pages/Payments.py",
                label="Open Payments",
                icon="➡️",
            )

    with arrow3:
        st.markdown(
            "<h2 style='text-align:center; color:#C1121F; margin-top:3rem;'>→</h2>",
            unsafe_allow_html=True,
        )

    with col5:
        with st.container(border=True):
            st.markdown("### 📊 Reports")
            st.write("Generate operational and financial reports for better decisions.")
            st.page_link(
                "pages/Reports.py",
                label="Open Reports",
                icon="➡️",
            )

    with arrow4:
        st.markdown(
            "<h2 style='text-align:center; color:#C1121F; margin-top:3rem;'>→</h2>",
            unsafe_allow_html=True,
        )

    with col6:
        with st.container(border=True):
            st.markdown("### 🤖 AI Assistant")
            st.write("Ask questions and surface shipment, pickup, and payment insights.")
            st.page_link(
                "pages/AI_Assistant.py",
                label="Open AI Assistant",
                icon="➡️",
            )