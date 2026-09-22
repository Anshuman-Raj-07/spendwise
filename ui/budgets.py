from datetime import date
import calendar
import streamlit as st
from sqlalchemy.orm import Session

from database.models import CATEGORIES
from utils.helpers import format_currency, get_month_name
from services.budget_service import (
    set_or_update_budget,
    get_budget_status,
    delete_budget,
)


def render_budgets(db: Session):
    """
    Renders the Budget Management page.
    Allows setting monthly category limits and visualizes progress bars with threshold alerts (80%, 100%+).
    """
    st.title("🎯 Monthly Budgets")
    st.markdown("Set spending targets for each category and track real-time utilization.")

    today = date.today()

    # Month & Year selector
    col_sel1, col_sel2, col_spacer = st.columns([2, 2, 4])
    with col_sel1:
        months_list = [(i, calendar.month_name[i]) for i in range(1, 13)]
        selected_month = st.selectbox(
            "Month",
            options=[m[0] for m in months_list],
            format_func=lambda x: calendar.month_name[x],
            index=today.month - 1,
        )
    with col_sel2:
        selected_year = st.selectbox(
            "Year",
            options=list(range(today.year - 2, today.year + 3)),
            index=2,  # Current year
        )

    st.markdown("---")

    # Fetch status for selected month/year
    budget_status = get_budget_status(db, selected_month, selected_year)

    # Top summary metrics
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Budgeted", format_currency(budget_status["total_budgeted"]))
    with m2:
        st.metric("Total Spent", format_currency(budget_status["total_spent"]))
    with m3:
        rem = budget_status["overall_remaining"]
        st.metric("Overall Remaining", format_currency(rem), delta=f"{format_currency(abs(rem))} {'left' if rem >= 0 else 'deficit'}")
    with m4:
        pct = budget_status["overall_percentage"]
        st.metric("Overall Used", f"{pct:.1f}%")

    st.markdown("---")

    # Alerts section if any exceeded or warning
    if budget_status["exceeded_count"] > 0 or budget_status["warning_count"] > 0:
        st.subheader("⚠️ Budget Alerts")
        for cat in budget_status["categories"]:
            if cat["is_exceeded"]:
                st.error(cat["alert_message"])
            elif cat["is_warning"]:
                st.warning(cat["alert_message"])

    # Progress by Category
    st.subheader(f"📊 Budget Progress for {get_month_name(selected_month)} {selected_year}")

    if not budget_status["categories"]:
        st.info("No budgets or expenses found for this month.")
    else:
        for cat_info in budget_status["categories"]:
            cat_name = cat_info["category"]
            limit = cat_info["monthly_limit"]
            spent = cat_info["spent"]
            pct = cat_info["percentage"]

            col_name, col_vals, col_pct = st.columns([3, 4, 2])
            with col_name:
                st.markdown(f"**{cat_name}**")
            with col_vals:
                if limit > 0:
                    st.caption(f"{format_currency(spent)} of {format_currency(limit)}")
                else:
                    st.caption(f"{format_currency(spent)} spent (No budget set)")
            with col_pct:
                if limit > 0:
                    if cat_info["is_exceeded"]:
                        st.markdown(f"<span style='color:#EF5350; font-weight:bold;'>{pct:.1f}% (Exceeded)</span>", unsafe_allow_html=True)
                    elif cat_info["is_warning"]:
                        st.markdown(f"<span style='color:#FFA726; font-weight:bold;'>{pct:.1f}% (High)</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<span style='color:#4ADE80; font-weight:bold;'>{pct:.1f}%</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color: var(--text-color); opacity: 0.7;'>Uncapped</span>", unsafe_allow_html=True)

            # Progress Bar (clamp between 0.0 and 1.0 for st.progress)
            clamped_pct = min(1.0, max(0.0, pct / 100.0)) if limit > 0 else 0.0
            st.progress(clamped_pct)
            st.write("")

    st.markdown("---")

    # Set or Update Category Budget Form
    with st.expander("⚙️ Set or Update Category Budget", expanded=False):
        with st.form("set_budget_form"):
            b_col1, b_col2 = st.columns(2)
            with b_col1:
                b_category = st.selectbox("Category", CATEGORIES)
            with b_col2:
                b_amount = st.number_input(
                    "Monthly Limit (₹)",
                    min_value=100.0,
                    max_value=1_000_000.0,
                    value=3000.0,
                    step=500.0,
                    format="%.2f",
                )

            submit_budget = st.form_submit_button("Save Budget Target", type="primary")
            if submit_budget:
                try:
                    updated = set_or_update_budget(
                        db,
                        category=b_category,
                        monthly_limit=b_amount,
                        month=selected_month,
                        year=selected_year,
                    )
                    st.success(
                        f"✅ Set budget of {format_currency(updated.monthly_limit)} for {updated.category} in {get_month_name(selected_month)} {selected_year}."
                    )
                    st.rerun()
                except ValueError as ve:
                    st.error(f"Error: {str(ve)}")

