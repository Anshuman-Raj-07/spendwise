from datetime import date
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import Budget, Expense, CATEGORIES
from utils.helpers import get_month_date_range


def set_or_update_budget(
    db: Session,
    category: str,
    monthly_limit: float,
    month: int,
    year: int,
) -> Budget:
    """
    Creates or updates a monthly budget for a specific category.
    """
    if category not in CATEGORIES:
        category = "Other"

    if monthly_limit <= 0:
        raise ValueError("Budget limit must be greater than zero.")
    if not (1 <= month <= 12):
        raise ValueError("Month must be between 1 and 12.")
    if year < 2000 or year > 2100:
        raise ValueError("Year is out of valid range.")

    budget = (
        db.query(Budget)
        .filter(
            Budget.category == category,
            Budget.month == month,
            Budget.year == year,
        )
        .first()
    )

    if budget:
        budget.monthly_limit = round(float(monthly_limit), 2)
    else:
        budget = Budget(
            category=category,
            monthly_limit=round(float(monthly_limit), 2),
            month=month,
            year=year,
        )
        db.add(budget)

    db.commit()
    db.refresh(budget)
    return budget


def get_budgets_for_month(db: Session, month: int, year: int) -> List[Budget]:
    """
    Retrieves all budget targets configured for a specific month and year.
    """
    return (
        db.query(Budget)
        .filter(Budget.month == month, Budget.year == year)
        .order_by(Budget.category)
        .all()
    )


def delete_budget(db: Session, budget_id: int) -> bool:
    """
    Removes a budget entry by its ID.
    """
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return False
    db.delete(budget)
    db.commit()
    return True


def batch_delete_budgets(db: Session, budget_ids: List[int]) -> int:
    """
    Deletes multiple budget records by their IDs in a single atomic database transaction.
    Returns the number of records successfully deleted.
    """
    if not budget_ids:
        return 0

    deleted_count = (
        db.query(Budget)
        .filter(Budget.id.in_(budget_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted_count


def get_budget_status(
    db: Session,
    month: int,
    year: int,
) -> Dict[str, Any]:
    """
    Calculates detailed budget status for a given month and year:
    - Compares configured budget vs actual spending for each category
    - Identifies warning states (>= 80%) and exceeded states (> 100%)
    - Provides overall budget utilization metrics
    """
    start_date, end_date = get_month_date_range(year, month)

    # 1. Fetch actual spending per category for this month
    spending_query = (
        db.query(
            Expense.category,
            func.sum(Expense.amount).label("total_spent"),
        )
        .filter(Expense.date >= start_date, Expense.date <= end_date)
        .group_by(Expense.category)
        .all()
    )
    spent_by_cat = {row[0]: float(row[1]) for row in spending_query}

    # 2. Fetch all configured budgets for this month
    budgets = get_budgets_for_month(db, month, year)
    budget_by_cat = {b.category: b.monthly_limit for b in budgets}

    # 3. Combine categories (both budgeted and any unbudgeted spending)
    all_categories = sorted(list(set(list(budget_by_cat.keys()) + list(spent_by_cat.keys()))))

    category_statuses = []
    total_budgeted = sum(budget_by_cat.values())
    total_spent = sum(spent_by_cat.values())

    for cat in all_categories:
        limit = budget_by_cat.get(cat, 0.0)
        spent = spent_by_cat.get(cat, 0.0)
        remaining = limit - spent if limit > 0 else 0.0
        pct = (spent / limit * 100) if limit > 0 else (100.0 if spent > 0 else 0.0)

        is_exceeded = limit > 0 and spent > limit
        is_warning = limit > 0 and (pct >= 80.0) and not is_exceeded

        alert_msg = None
        if is_exceeded:
            over = spent - limit
            alert_msg = f"⚠️ {cat} budget exceeded by ₹{over:,.2f}"
        elif is_warning:
            alert_msg = f"⚠️ You have used {pct:.1f}% of your {cat} budget."

        category_statuses.append({
            "category": cat,
            "monthly_limit": limit,
            "spent": spent,
            "remaining": remaining,
            "percentage": pct,
            "is_exceeded": is_exceeded,
            "is_warning": is_warning,
            "has_budget": limit > 0,
            "alert_message": alert_msg,
        })

    # Sort so categories with budget issues come first
    category_statuses.sort(key=lambda x: (not x["is_exceeded"], not x["is_warning"], -x["spent"]))

    overall_remaining = total_budgeted - total_spent if total_budgeted > 0 else 0.0
    overall_pct = (total_spent / total_budgeted * 100) if total_budgeted > 0 else 0.0

    return {
        "month": month,
        "year": year,
        "total_budgeted": total_budgeted,
        "total_spent": total_spent,
        "overall_remaining": overall_remaining,
        "overall_percentage": overall_pct,
        "categories": category_statuses,
        "exceeded_count": sum(1 for c in category_statuses if c["is_exceeded"]),
        "warning_count": sum(1 for c in category_statuses if c["is_warning"]),
    }

