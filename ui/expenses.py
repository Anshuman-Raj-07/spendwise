from datetime import date, datetime
import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session

from database.models import CATEGORIES
from utils.helpers import format_currency
from services.expense_service import (
    add_expense,
    get_expenses,
    delete_expense,
    batch_delete_expenses,
    update_expense,
    get_all_categories,
)
from services.ai_service import parse_expense_with_ai


def render_expenses(db: Session, api_key: str = None):
    """
    Renders the Expenses management page with three tabs:
    1. 📋 View & Manage Expenses (Search, Filter, Export, Delete)
    2. ✍️ Manual Expense Entry
    3. 🤖 Add Expense with AI (NLP extraction -> Editable Confirmation -> Save)
    """
    st.title("💳 Expense Management")

    tab_view, tab_manual, tab_ai = st.tabs([
        "📋 View All Expenses",
        "✍️ Manual Add Expense",
        "🤖 Add with AI",
    ])

    # =========================================================================
    # TAB 1: VIEW & MANAGE EXPENSES
    # =========================================================================
    with tab_view:
        st.subheader("Filter & Search Transactions")

        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            cat_filter = st.selectbox(
                "Category",
                options=["All"] + CATEGORIES,
                index=0,
                key="view_cat_filter",
            )
        with col2:
            search_query = st.text_input(
                "Search Description",
                placeholder="e.g. coffee, uber, book",
                key="view_search",
            )
        with col3:
            sort_order = st.selectbox("Sort By", ["Newest First", "Oldest First", "Highest Amount"], key="view_sort")

        expenses = get_expenses(
            db,
            category=cat_filter if cat_filter != "All" else None,
            search=search_query,
        )

        # Apply sorting
        if sort_order == "Oldest First":
            expenses = sorted(expenses, key=lambda x: (x.date, x.id))
        elif sort_order == "Highest Amount":
            expenses = sorted(expenses, key=lambda x: x.amount, reverse=True)

        if not expenses:
            st.info("No expenses found matching the selected criteria.")
        else:
            total_filtered = sum(e.amount for e in expenses)
            st.markdown(
                f"**Showing {len(expenses)} transactions** | Total: **{format_currency(total_filtered)}**"
            )

            # Convert to DataFrame for display and CSV export
            data_rows = []
            for e in expenses:
                data_rows.append({
                    "ID": e.id,
                    "Date": e.date.isoformat(),
                    "Category": e.category,
                    "Description": e.description,
                    "Amount (₹)": e.amount,
                })
            df = pd.DataFrame(data_rows)

            # Display table
            display_df = df.copy()
            display_df["Amount (₹)"] = display_df["Amount (₹)"].apply(lambda x: f"₹{x:,.2f}")
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            # CSV Download button
            csv_data = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Export to CSV",
                data=csv_data,
                file_name=f"spendwise_expenses_{date.today().isoformat()}.csv",
                mime="text/csv",
            )

            st.markdown("---")
            # Quick & Batch Delete Actions
            with st.expander("🗑️ Delete or Batch Delete Transactions"):
                del_mode = st.radio("Deletion Mode", ["Batch Delete Multiple", "Single ID Delete"], horizontal=True, key="exp_del_mode")

                if del_mode == "Single ID Delete":
                    col_d1, col_d2 = st.columns([3, 1])
                    with col_d1:
                        del_id = st.number_input(
                            "Enter Transaction ID to delete",
                            min_value=1,
                            step=1,
                            key="delete_txn_id",
                        )
                    with col_d2:
                        st.write("")
                        st.write("")
                        if st.button("Delete Transaction", type="secondary"):
                            success = delete_expense(db, int(del_id))
                            if success:
                                st.success(f"Transaction #{del_id} deleted successfully.")
                                st.rerun()
                            else:
                                st.error(f"Transaction #{del_id} not found.")
                else:
                    all_exp_ids = [e.id for e in expenses]
                    selected_batch = st.multiselect(
                        "Select transactions to delete:",
                        options=all_exp_ids,
                        format_func=lambda x: f"ID #{x} — ₹{next((e.amount for e in expenses if e.id == x), 0):,.2f} ({next((e.description for e in expenses if e.id == x), '')})",
                        key="expenses_tab_batch_ids",
                    )
                    if selected_batch:
                        st.warning(f"Selected {len(selected_batch)} transactions for deletion.")
                        if st.button(f"🚨 Delete {len(selected_batch)} Selected Transactions", type="primary"):
                            cnt = batch_delete_expenses(db, selected_batch)
                            st.success(f"Successfully deleted {cnt} transactions.")
                            st.rerun()

    # =========================================================================
    # TAB 2: MANUAL EXPENSE ENTRY
    # =========================================================================
    with tab_manual:
        st.subheader("Add Expense Manually")
        st.caption("Fill in the transaction details to record your expense.")

        with st.form("manual_expense_form", clear_on_submit=True):
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                amount_input = st.number_input(
                    "Amount (₹)*",
                    min_value=0.01,
                    max_value=10_000_000.0,
                    value=100.0,
                    step=10.0,
                    format="%.2f",
                )
                category_input = st.selectbox(
                    "Category*",
                    options=CATEGORIES,
                    index=0,
                )
            with col_m2:
                expense_date = st.date_input(
                    "Date*",
                    value=date.today(),
                    max_value=date.today() + pd.Timedelta(days=365),
                )
                description_input = st.text_input(
                    "Description*",
                    placeholder="e.g. Lunch at college canteen",
                )

            submitted = st.form_submit_button("➕ Add Expense", type="primary")

            if submitted:
                if not description_input or not description_input.strip():
                    st.error("Description cannot be empty.")
                else:
                    try:
                        new_exp = add_expense(
                            db,
                            amount=amount_input,
                            category=category_input,
                            description=description_input,
                            expense_date=expense_date,
                        )
                        st.success(
                            f"✅ Expense of {format_currency(new_exp.amount)} for '{new_exp.description}' added successfully!"
                        )
                    except ValueError as ve:
                        st.error(f"Validation Error: {str(ve)}")

    # =========================================================================
    # TAB 3: ADD EXPENSE WITH AI
    # =========================================================================
    with tab_ai:
        st.subheader("🤖 Add Expense with Natural Language")
        st.markdown(
            "Type a natural sentence describing what you spent, and SpendWise AI will automatically "
            "extract the amount, category, date, and description for your confirmation."
        )

        # Quick sample buttons
        st.caption("Try an example:")
        c1, c2, c3 = st.columns(3)
        sample_prompt = None
        if c1.button("🍔 Lunch at college ₹250 today"):
            sample_prompt = "I spent 250 rupees on lunch at the college canteen today."
        if c2.button("🚗 Auto ride ₹120 this morning"):
            sample_prompt = "Spent 120 on an auto ride to college this morning."
        if c3.button("⌨️ Mechanical keyboard ₹2500"):
            sample_prompt = "Bought a new mechanical keyboard for my laptop for 2500 yesterday."

        nl_input = st.text_area(
            "Enter your expense in plain English:",
            value=sample_prompt or st.session_state.get("ai_expense_input", ""),
            placeholder="e.g., Spent 350 on groceries at supermarket yesterday",
            key="ai_expense_text_area",
            height=80,
        )

        parse_btn = st.button("✨ Extract Expense with AI", type="primary")

        if parse_btn:
            if not nl_input or not nl_input.strip():
                st.warning("Please enter some text first.")
            else:
                with st.spinner("Analyzing text with AI..."):
                    extracted = parse_expense_with_ai(
                        nl_input,
                        reference_date=date.today(),
                        api_key=api_key,
                    )
                    st.session_state["extracted_expense"] = extracted

        # Display extracted result for user review and confirmation
        if "extracted_expense" in st.session_state and st.session_state["extracted_expense"]:
            ext = st.session_state["extracted_expense"]

            if ext.get("warning"):
                st.warning(ext["warning"])
            elif ext.get("error"):
                st.info(ext["error"])

            st.markdown("### 🔍 Extracted Transaction Details")
            st.info("You can review and edit any field below before saving.")

            with st.form("confirm_ai_expense_form"):
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    conf_amount = st.number_input(
                        "Amount (₹)",
                        min_value=0.01,
                        value=float(ext.get("amount", 100.0)) if ext.get("amount", 0) > 0 else 100.0,
                        step=10.0,
                        format="%.2f",
                    )
                    cat_index = 0
                    if ext.get("category") in CATEGORIES:
                        cat_index = CATEGORIES.index(ext.get("category"))
                    conf_category = st.selectbox(
                        "Category",
                        options=CATEGORIES,
                        index=cat_index,
                    )
                with col_e2:
                    default_date = date.today()
                    if ext.get("date"):
                        try:
                            default_date = datetime.strptime(ext["date"], "%Y-%m-%d").date()
                        except ValueError:
                            default_date = date.today()

                    conf_date = st.date_input(
                        "Date",
                        value=default_date,
                    )
                    conf_desc = st.text_input(
                        "Description",
                        value=ext.get("description", ""),
                    )

                save_confirmed = st.form_submit_button("💾 Confirm & Save Expense", type="primary")

                if save_confirmed:
                    try:
                        saved = add_expense(
                            db,
                            amount=conf_amount,
                            category=conf_category,
                            description=conf_desc,
                            expense_date=conf_date,
                        )
                        st.success(
                            f"🎉 Successfully saved: {format_currency(saved.amount)} ({saved.category}) - '{saved.description}' on {saved.date}!"
                        )
                        # Clear session state
                        st.session_state.pop("extracted_expense", None)
                    except ValueError as err:
                        st.error(f"Error saving: {str(err)}")

