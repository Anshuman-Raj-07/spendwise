import calendar
from datetime import date, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy.orm import Session

from utils.helpers import format_currency, get_month_date_range, get_month_name
from services.analytics_service import (
    get_monthly_summary,
    get_category_breakdown,
    get_daily_spending,
    get_monthly_trend,
    get_top_expenses,
)
from services.budget_service import get_budget_status


def render_dashboard(db: Session):
    """
    Renders the main SpendWise financial dashboard with top KPIs,
    filters (current month, previous month, custom date range), and Plotly charts.
    """
    st.title("📊 SpendWise Dashboard")
    st.markdown("Overview of your personal spending, budgets, and financial trends.")

    today = date.today()

    # --- Date Filter Selection ---
    col_filter, col_spacer = st.columns([2, 3])
    with col_filter:
        filter_option = st.selectbox(
            "📅 Select Time Period",
            options=["Current Month", "Previous Month", "Custom Date Range"],
            index=0,
        )

    if filter_option == "Current Month":
        start_date, end_date = get_month_date_range(today.year, today.month)
        selected_month, selected_year = today.month, today.year
    elif filter_option == "Previous Month":
        if today.month == 1:
            p_month, p_year = 12, today.year - 1
        else:
            p_month, p_year = today.month - 1, today.year
        start_date, end_date = get_month_date_range(p_year, p_month)
        selected_month, selected_year = p_month, p_year
    else:  # Custom Date Range
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            start_date = st.date_input("Start Date", value=today - timedelta(days=30))
        with col_d2:
            end_date = st.date_input("End Date", value=today)
        selected_month, selected_year = today.month, today.year

    # --- Top KPI Summary Cards ---
    summary = get_monthly_summary(db, selected_month, selected_year)
    category_data = get_category_breakdown(db, start_date, end_date)
    period_spent = sum(c["total_amount"] for c in category_data)
    period_txns = sum(c["transaction_count"] for c in category_data)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(
            label="Total Spent",
            value=format_currency(period_spent),
            help="Total expenditures within the selected date range.",
        )
    with m2:
        st.metric(
            label="Monthly Budget",
            value=format_currency(summary["total_budget"]),
            help="Configured total budget for the month.",
        )
    with m3:
        remaining = summary["remaining_budget"]
        delta_color = "normal" if remaining >= 0 else "inverse"
        st.metric(
            label="Remaining Budget",
            value=format_currency(remaining),
            delta=f"{format_currency(abs(remaining))} {'left' if remaining >= 0 else 'over'}",
            delta_color=delta_color,
        )
    with m4:
        st.metric(
            label="Transactions",
            value=str(period_txns),
            help="Number of transactions logged in this period.",
        )

    st.markdown("---")

    # If no data is available
    if period_spent == 0:
        st.info("ℹ️ No expenses recorded for this period. Add expenses from the sidebar or click 'Seed Demo Data' to view sample analytics.")
        return

    # --- Charts Row 1: Donut (Category Breakdown) & Daily Spending Line Chart ---
    chart_col1, chart_col2 = st.columns([1, 1])

    with chart_col1:
        st.subheader("🍩 Spending by Category")
        df_cat = pd.DataFrame(category_data)
        if not df_cat.empty:
            fig_pie = px.pie(
                df_cat,
                values="total_amount",
                names="category",
                hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Prism,
            )
            fig_pie.update_traces(
                textposition="inside",
                textinfo="percent+label",
                hovertemplate="<b>%{label}</b><br>Amount: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
            )
            fig_pie.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                height=320,
            )
            st.plotly_chart(fig_pie, use_container_width=True, theme="streamlit")

    with chart_col2:
        st.subheader("📈 Daily Spending Trend")
        daily_data = get_daily_spending(db, start_date, end_date)
        if daily_data:
            df_daily = pd.DataFrame(daily_data)
            fig_line = px.line(
                df_daily,
                x="date",
                y="daily_total",
                markers=True,
                labels={"date": "Date", "daily_total": "Spent (₹)"},
            )
            fig_line.update_traces(
                line_color="#38BDF8",
                line_width=3,
                marker=dict(size=8, color="#0284C7"),
                hovertemplate="<b>Date: %{x}</b><br>Spent: ₹%{y:,.2f}<extra></extra>",
            )
            fig_line.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=320,
                xaxis_title="",
                yaxis_title="Amount (₹)",
            )
            st.plotly_chart(fig_line, use_container_width=True, theme="streamlit")
        else:
            st.caption("No daily trend data available for this range.")

    st.markdown("---")

    # --- Charts Row 2: Monthly Bar Chart & Top Spending Categories / Transactions ---
    col_monthly, col_top = st.columns([1, 1])

    with col_monthly:
        st.subheader("📊 6-Month Spending Trend")
        trend_data = get_monthly_trend(db, num_months=6)
        if trend_data:
            df_trend = pd.DataFrame(trend_data)
            fig_bar = px.bar(
                df_trend,
                x="label",
                y="total_spent",
                labels={"label": "Month", "total_spent": "Total Spent (₹)"},
                text_auto=",.0f",
            )
            fig_bar.update_traces(
                marker_color="#34D399",
                hovertemplate="<b>%{x}</b><br>Total Spent: ₹%{y:,.2f}<extra></extra>",
            )
            fig_bar.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=320,
                xaxis_title="",
                yaxis_title="Amount (₹)",
            )
            st.plotly_chart(fig_bar, use_container_width=True, theme="streamlit")

    with col_top:
        st.subheader("🏆 Top Spending Transactions")
        top_txns = get_top_expenses(db, start_date, end_date, limit=5)
        if top_txns:
            df_top = pd.DataFrame(top_txns)[["description", "category", "amount", "date"]]
            df_top.rename(
                columns={
                    "description": "Description",
                    "category": "Category",
                    "amount": "Amount (₹)",
                    "date": "Date",
                },
                inplace=True,
            )
            df_top["Amount (₹)"] = df_top["Amount (₹)"].apply(lambda x: f"₹{x:,.2f}")
            st.dataframe(df_top, use_container_width=True, hide_index=True)
        else:
            st.caption("No transactions found.")

    # --- Category Breakdown Summary Table ---
    st.subheader("📑 Spending by Category Summary")
    df_cat_summary = pd.DataFrame(category_data)
    if not df_cat_summary.empty:
        df_cat_summary.rename(
            columns={
                "category": "Category",
                "total_amount": "Total Spent (₹)",
                "transaction_count": "Transactions",
                "percentage": "Share (%)",
            },
            inplace=True,
        )
        df_cat_summary["Total Spent (₹)"] = df_cat_summary["Total Spent (₹)"].apply(lambda x: f"₹{x:,.2f}")
        df_cat_summary["Share (%)"] = df_cat_summary["Share (%)"].apply(lambda x: f"{x:.1f}%")
        st.dataframe(df_cat_summary, use_container_width=True, hide_index=True)

