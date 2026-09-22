from datetime import date
import calendar
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy.orm import Session

from utils.helpers import format_currency, get_month_name
from services.analytics_service import (
    generate_insights,
    compare_months,
    get_monthly_summary,
)


def render_insights(db: Session):
    """
    Renders the Insights & Monthly Comparison page:
    1. Deterministic Data-Driven Spending Insights
    2. Linear Spending Rate Projection with explicit disclaimers
    3. Side-by-Side Monthly Comparison with Category Deltas and Bar Chart
    """
    st.title("💡 Spending Insights & Comparison")
    st.markdown("Deep-dive analytics, month-over-month comparisons, and rate projections.")

    today = date.today()

    # --- Section 1: Month-over-Month Comparison ---
    st.subheader("🔄 Month-over-Month Comparison")
    st.caption("Select any two months to analyze changes in spending habits.")

    months_list = [(i, calendar.month_name[i]) for i in range(1, 13)]

    # Compute default previous and current month
    m2_def, y2_def = today.month, today.year
    if m2_def == 1:
        m1_def, y1_def = 12, y2_def - 1
    else:
        m1_def, y1_def = m2_def - 1, y2_def

    comp_col1, comp_col2 = st.columns(2)
    with comp_col1:
        st.markdown("**Base Month (Earlier)**")
        c1_m, c1_y = st.columns(2)
        with c1_m:
            month1 = st.selectbox(
                "Base Month",
                options=[m[0] for m in months_list],
                format_func=lambda x: calendar.month_name[x],
                index=m1_def - 1,
                key="comp_m1",
            )
        with c1_y:
            year1 = st.selectbox(
                "Base Year",
                options=list(range(today.year - 2, today.year + 2)),
                index=2 if today.year - 2 <= y1_def <= today.year + 1 else 0,
                key="comp_y1",
            )

    with comp_col2:
        st.markdown("**Comparison Month (Later)**")
        c2_m, c2_y = st.columns(2)
        with c2_m:
            month2 = st.selectbox(
                "Comparison Month",
                options=[m[0] for m in months_list],
                format_func=lambda x: calendar.month_name[x],
                index=m2_def - 1,
                key="comp_m2",
            )
        with c2_y:
            year2 = st.selectbox(
                "Comparison Year",
                options=list(range(today.year - 2, today.year + 2)),
                index=2 if today.year - 2 <= y2_def <= today.year + 1 else 0,
                key="comp_y2",
            )

    comp_result = compare_months(db, month1, year1, month2, year2)

    # Comparison metrics
    cm1, cm2, cm3, cm4 = st.columns(4)
    with cm1:
        st.metric(f"{comp_result['month1_label']} Total", format_currency(comp_result["month1_total"]))
    with cm2:
        st.metric(f"{comp_result['month2_label']} Total", format_currency(comp_result["month2_total"]))
    with cm3:
        delta = comp_result["total_difference"]
        delta_pct = comp_result["total_percentage_change"]
        st.metric(
            "Total Difference",
            format_currency(abs(delta)),
            delta=f"{delta_pct:+.1f}% ({format_currency(delta)})",
            delta_color="inverse" if delta > 0 else "normal",
        )
    with cm4:
        sign = "increased" if delta > 0 else ("decreased" if delta < 0 else "remained flat")
        st.info(f"Spending **{sign}** overall.")

    # Side by side bar chart
    if comp_result["categories"]:
        df_comp = pd.DataFrame(comp_result["categories"])

        # Filter out categories with 0 in both months for cleaner chart
        df_comp_active = df_comp[(df_comp["month1_spent"] > 0) | (df_comp["month2_spent"] > 0)].copy()

        if not df_comp_active.empty:
            fig_comp = go.Figure()
            fig_comp.add_trace(go.Bar(
                x=df_comp_active["category"],
                y=df_comp_active["month1_spent"],
                name=comp_result["month1_label"],
                marker_color="#90CAF9",
            ))
            fig_comp.add_trace(go.Bar(
                x=df_comp_active["category"],
                y=df_comp_active["month2_spent"],
                name=comp_result["month2_label"],
                marker_color="#1E88E5",
            ))
            fig_comp.update_layout(
                barmode="group",
                title=f"Category Spending: {comp_result['month1_label']} vs {comp_result['month2_label']}",
                margin=dict(t=40, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=350,
                xaxis_title="Category",
                yaxis_title="Amount (₹)",
            )
            st.plotly_chart(fig_comp, use_container_width=True, theme="streamlit")

        # Comparison Table
        st.markdown("##### Detailed Category Breakdown")
        df_table = df_comp.copy()
        df_table.rename(
            columns={
                "category": "Category",
                "month1_spent": f"{comp_result['month1_label']} (₹)",
                "month2_spent": f"{comp_result['month2_label']} (₹)",
                "difference": "Difference (₹)",
                "percentage_change": "% Change",
            },
            inplace=True,
        )
        df_table[f"{comp_result['month1_label']} (₹)"] = df_table[f"{comp_result['month1_label']} (₹)"].apply(lambda x: f"₹{x:,.2f}")
        df_table[f"{comp_result['month2_label']} (₹)"] = df_table[f"{comp_result['month2_label']} (₹)"].apply(lambda x: f"₹{x:,.2f}")
        df_table["Difference (₹)"] = df_table["Difference (₹)"].apply(lambda x: f"{'+₹' if x > 0 else ('-₹' if x < 0 else '₹')}{abs(x):,.2f}")
        df_table["% Change"] = df_table["% Change"].apply(lambda x: f"{x:+.1f}%")

        st.dataframe(df_table, use_container_width=True, hide_index=True)

    st.markdown("---")

    # --- Section 2: Automated Spending Insights ---
    st.subheader(f"🧠 Spending Insights ({get_month_name(today.month)} {today.year})")
    insights_list = generate_insights(db, today.month, today.year)

    for item in insights_list:
        icon = item.get("icon", "💡")
        text = item.get("text", "")
        st.markdown(f"#### {icon} {text}")

    st.markdown("---")

    # --- Section 3: Spending Projection ---
    st.subheader("🔮 Monthly Spending Projection")
    summary = get_monthly_summary(db, today.month, today.year)

    p_col1, p_col2 = st.columns([2, 3])
    with p_col1:
        st.metric("Current Month Spent", format_currency(summary["total_spent"]))
        st.metric("Days Elapsed", f"{summary['days_elapsed']} / {summary['days_in_month']} days")
        st.metric("Daily Average Spend", format_currency(summary["daily_rate"]))

    with p_col2:
        st.markdown("##### Projected Monthly Total")
        st.markdown(
            f"<h2 style='color:#38BDF8;'>{format_currency(summary['projected_total'])}</h2>",
            unsafe_allow_html=True,
        )
        st.caption(
            "📐 **Formula:** `(Current Spending / Days Elapsed) * Total Days in Month`\n\n"
            "*Notice: This is a simple linear extrapolation based on your current daily spending rate. "
            "It is not a guaranteed financial prediction.*"
        )

