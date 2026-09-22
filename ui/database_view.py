from datetime import date
import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database.models import Expense, Budget, CATEGORIES
from utils.helpers import format_currency, get_month_name
from services.expense_service import get_expenses, batch_delete_expenses
from services.budget_service import batch_delete_budgets


def render_database_view(db: Session):
    """
    Renders the dedicated Database View module.
    Allows inspecting raw database tables, filtering records, and performing batch deletions.
    """
    st.title("🗄️ Database View & Batch Operations")
    st.markdown("Inspect raw database records, export data tables, and perform bulk deletions.")

    tab_expenses, tab_budgets = st.tabs(["💳 Expenses Table", "🎯 Budgets Table"])

    # =========================================================================
    # TAB 1: EXPENSES TABLE & BATCH DELETE
    # =========================================================================
    with tab_expenses:
        st.subheader("Expenses Database Records")

        # Top summary metrics
        total_exp_count = db.query(Expense).count()
        expenses_all = db.query(Expense).order_by(desc(Expense.date), desc(Expense.id)).all()
        total_value = sum(e.amount for e in expenses_all)

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Total Records", f"{total_exp_count:,}")
        with m2:
            st.metric("Total Stored Value", format_currency(total_value))
        with m3:
            cats_count = len(set(e.category for e in expenses_all)) if expenses_all else 0
            st.metric("Active Categories", f"{cats_count} / {len(CATEGORIES)}")

        st.markdown("---")

        # Filter controls
        f_col1, f_col2, f_col3 = st.columns([2, 2, 2])
        with f_col1:
            cat_choice = st.selectbox(
                "Filter Category",
                options=["All"] + CATEGORIES,
                key="db_cat_filter",
            )
        with f_col2:
            search_kw = st.text_input(
                "Search Description",
                placeholder="keyword...",
                key="db_search_kw",
            )
        with f_col3:
            limit_records = st.selectbox(
                "Max Rows Displayed",
                options=[50, 100, 200, 500, 1000],
                index=1,
                key="db_max_rows",
            )

        filtered_expenses = get_expenses(
            db,
            category=cat_choice if cat_choice != "All" else None,
            search=search_kw,
            limit=limit_records,
        )

        if not filtered_expenses:
            st.info("No expense records match the specified filters.")
        else:
            # Prepare DataFrame
            rows = []
            for e in filtered_expenses:
                rows.append({
                    "Select": False,
                    "ID": e.id,
                    "Date": e.date.isoformat(),
                    "Category": e.category,
                    "Description": e.description,
                    "Amount (₹)": e.amount,
                    "Created At (UTC)": e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
                })
            df_exp = pd.DataFrame(rows)

            st.markdown(
                f"**Displaying {len(filtered_expenses)} records** (Total: {format_currency(sum(e.amount for e in filtered_expenses))})"
            )

            # --- Batch Delete Controls ---
            with st.expander("🗑️ Batch Delete Expenses", expanded=True):
                st.markdown("Select specific transaction IDs or select all filtered records to delete.")
                all_ids = [e.id for e in filtered_expenses]

                col_b1, col_b2 = st.columns([3, 1])
                with col_b1:
                    selected_ids = st.multiselect(
                        "Choose Transaction IDs to delete:",
                        options=all_ids,
                        format_func=lambda x: f"ID #{x} — ₹{next((e.amount for e in filtered_expenses if e.id == x), 0):,.2f} ({next((e.description for e in filtered_expenses if e.id == x), '')})",
                        key="batch_del_ids",
                    )
                with col_b2:
                    select_all_btn = st.checkbox("Select All Filtered", key="chk_select_all_exp")
                    if select_all_btn:
                        selected_ids = all_ids

                if selected_ids:
                    st.warning(f"⚠️ You have selected **{len(selected_ids)} transactions** for deletion.")
                    confirm_del = st.checkbox("I confirm that I want to permanently delete these transactions.")
                    if st.button("🚨 Permanently Delete Selected", type="primary", disabled=not confirm_del):
                        deleted_num = batch_delete_expenses(db, selected_ids)
                        st.success(f"✅ Successfully deleted {deleted_num} expense records.")
                        st.rerun()

            # Display Data Table
            display_table = df_exp.drop(columns=["Select"])
            display_table["Amount (₹)"] = display_table["Amount (₹)"].apply(lambda x: f"₹{x:,.2f}")
            st.dataframe(display_table, use_container_width=True, hide_index=True)

            # CSV Download
            csv_exp = df_exp.drop(columns=["Select"]).to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Export Filtered Table to CSV",
                data=csv_exp,
                file_name=f"spendwise_db_expenses_{date.today().isoformat()}.csv",
                mime="text/csv",
                key="btn_csv_exp",
            )

    # =========================================================================
    # TAB 2: BUDGETS TABLE & BATCH DELETE
    # =========================================================================
    with tab_budgets:
        st.subheader("Budgets Database Records")

        budgets_all = db.query(Budget).order_by(desc(Budget.year), desc(Budget.month), Budget.category).all()
        total_budget_count = len(budgets_all)
        total_budget_cap = sum(b.monthly_limit for b in budgets_all)

        bm1, bm2 = st.columns(2)
        with bm1:
            st.metric("Total Budgets Configured", str(total_budget_count))
        with bm2:
            st.metric("Total Budget Value", format_currency(total_budget_cap))

        st.markdown("---")

        if not budgets_all:
            st.info("No budget records found in database.")
        else:
            b_rows = []
            for b in budgets_all:
                b_rows.append({
                    "ID": b.id,
                    "Category": b.category,
                    "Monthly Limit (₹)": b.monthly_limit,
                    "Month": f"{get_month_name(b.month)} ({b.month})",
                    "Year": b.year,
                })
            df_bgt = pd.DataFrame(b_rows)

            # Batch Delete Budgets
            with st.expander("🗑️ Batch Delete Budgets", expanded=False):
                bgt_ids = [b.id for b in budgets_all]
                selected_bgt_ids = st.multiselect(
                    "Choose Budget IDs to delete:",
                    options=bgt_ids,
                    format_func=lambda x: f"ID #{x} — {next((b.category for b in budgets_all if b.id == x), '')} ({format_currency(next((b.monthly_limit for b in budgets_all if b.id == x), 0))})",
                    key="batch_del_bgt_ids",
                )
                if selected_bgt_ids:
                    confirm_bgt = st.checkbox("Confirm deletion of selected budgets", key="chk_confirm_bgt")
                    if st.button("Delete Selected Budgets", type="primary", disabled=not confirm_bgt):
                        count_bgt_del = batch_delete_budgets(db, selected_bgt_ids)
                        st.success(f"✅ Deleted {count_bgt_del} budget records.")
                        st.rerun()

            display_bgt = df_bgt.copy()
            display_bgt["Monthly Limit (₹)"] = display_bgt["Monthly Limit (₹)"].apply(lambda x: f"₹{x:,.2f}")
            st.dataframe(display_bgt, use_container_width=True, hide_index=True)

            csv_bgt = df_bgt.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Export Budgets Table to CSV",
                data=csv_bgt,
                file_name=f"spendwise_db_budgets_{date.today().isoformat()}.csv",
                mime="text/csv",
                key="btn_csv_bgt",
            )

