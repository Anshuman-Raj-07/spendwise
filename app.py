import os
from datetime import date
import streamlit as st
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from database.database import init_db, get_db
from database.models import Expense, Budget
from utils.helpers import seed_sample_data, format_currency
from ui.dashboard import render_dashboard
from ui.expenses import render_expenses
from ui.budgets import render_budgets
from ui.assistant import render_assistant
from ui.insights import render_insights
from ui.database_view import render_database_view
from services.ai_service import test_gemini_connection

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="SpendWise — AI-Powered Personal Expense Assistant",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom Styling for Modern Clean Look (Dark & Light Mode Adaptive) ---
st.markdown(
    """
    <style>
    /* Metric card refinements: Uses theme CSS variables for complete Dark & Light mode harmony */
    div[data-testid="stMetric"] {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.2);
        padding: 16px 20px;
        border-radius: 12px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
    }
    div[data-testid="stMetric"]:hover {
        border-color: rgba(128, 128, 128, 0.45);
        transition: 0.2s ease-in-out;
    }
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: var(--text-color);
        opacity: 0.85;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: var(--text-color);
        font-weight: 700;
    }
    /* Section styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 6px;
    }
    /* Sidebar header */
    .sidebar-header {
        font-size: 1.4rem;
        font-weight: 700;
        color: #38BDF8;
        margin-bottom: 4px;
    }
    .sidebar-subtitle {
        font-size: 0.85rem;
        color: var(--text-color);
        opacity: 0.75;
        margin-bottom: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize SQLite database schema
init_db()


def main():
    # Sidebar Navigation & Utilities
    with st.sidebar:
        st.markdown("<div class='sidebar-header'>💰 SpendWise</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='sidebar-subtitle'>AI-Powered Personal Expense Assistant</div>",
            unsafe_allow_html=True,
        )

        # Navigation menu
        nav_choice = st.radio(
            "Navigation",
            options=[
                "📊 Dashboard",
                "💳 Expenses",
                "🎯 Budgets",
                "💡 Insights & Comparison",
                "💬 Ask SpendWise",
                "🗄️ Database View",
            ],
            index=0,
        )

        st.markdown("---")

        # Google Gemini Configuration in Sidebar
        st.markdown("##### 🤖 Gemini AI Settings")
        env_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        session_key = st.session_state.get("gemini_api_key", env_key)

        api_key_input = st.text_input(
            "Gemini API Key",
            type="password",
            value=session_key if session_key != "your_gemini_api_key_here" else "",
            placeholder="AIzaSy...",
            help="Get your key from Google AI Studio. Stored in session memory.",
        )

        if api_key_input and api_key_input.strip():
            active_key = api_key_input.strip()
            st.session_state["gemini_api_key"] = active_key
            st.caption("🟢 Key Loaded • Using Gemini Latest Model (`gemini-flash-latest` / auto-detect)")

            if st.button("🔌 Test Gemini Connection", type="secondary", use_container_width=True):
                with st.spinner("Testing connection with Google Gemini..."):
                    diag = test_gemini_connection(active_key)
                    if diag.get("success"):
                        latest = diag.get("latest_model", "gemini-flash-latest")
                        tot = diag.get("total_models", 0)
                        st.success(f"✅ Connected! Active Model: `{latest}` ({tot} models available)")
                    else:
                        code = diag.get("status_code", "Error")
                        st.error(f"❌ Connection Failed (HTTP {code})")
                        if diag.get("error_summary"):
                            with st.expander("View Error Details"):
                                st.code(diag["error_summary"])
                        st.info(diag.get("help", "Please check your API key."))
        else:
            active_key = None
            st.info("⚪ Offline Mode (Deterministic logic)")
            st.caption("👉 Get a free key in 10s at [Google AI Studio](https://aistudio.google.com/app/apikey)")

        st.markdown("---")

        # Demo Data Generator
        st.markdown("##### 🚀 Quick Demo Data")
        st.caption("Populate 3 months of sample transactions and budgets for testing and exploration.")

        with get_db() as db:
            total_exp = db.query(Expense).count()
            total_bgt = db.query(Budget).count()

        st.markdown(f"**Current DB Status:** {total_exp} expenses, {total_bgt} budgets")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🌱 Seed Data", type="primary", use_container_width=True):
                with get_db() as db:
                    res = seed_sample_data(db, force_clean=False)
                    if res.get("already_seeded"):
                        st.info("Data already present. Use Reset to re-seed.")
                    else:
                        st.success(f"Added {res['expenses_added']} transactions!")
                        st.rerun()
        with col_btn2:
            if st.button("🔄 Reset DB", type="secondary", use_container_width=True):
                with get_db() as db:
                    res = seed_sample_data(db, force_clean=True)
                    st.warning("Database reset and re-seeded with fresh sample data!")
                    st.rerun()

        st.markdown("---")
        st.caption("SpendWise v1.0 • Built with Streamlit, SQLAlchemy & Google Gemini")

    # Route to selected view
    with get_db() as db:
        if nav_choice == "📊 Dashboard":
            render_dashboard(db)
        elif nav_choice == "💳 Expenses":
            render_expenses(db, api_key=active_key)
        elif nav_choice == "🎯 Budgets":
            render_budgets(db)
        elif nav_choice == "💡 Insights & Comparison":
            render_insights(db)
        elif nav_choice == "💬 Ask SpendWise":
            render_assistant(db, api_key=active_key)
        elif nav_choice == "🗄️ Database View":
            render_database_view(db)


if __name__ == "__main__":
    main()

