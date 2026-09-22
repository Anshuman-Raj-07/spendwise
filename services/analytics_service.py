import calendar
from datetime import date
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from database.models import Expense, Budget
from utils.helpers import get_month_date_range, get_month_name
from services.budget_service import get_budget_status


def get_monthly_summary(db: Session, month: int, year: int) -> Dict[str, Any]:
    """
    Computes top-level monthly statistics:
    - Total spending
    - Transaction count
    - Average transaction size
    - Days elapsed & linear spending projection
    """
    start_date, end_date = get_month_date_range(year, month)
    today = date.today()

    expenses = (
        db.query(Expense)
        .filter(Expense.date >= start_date, Expense.date <= end_date)
        .all()
    )

    total_spent = sum(e.amount for e in expenses)
    count = len(expenses)
    avg_txn = (total_spent / count) if count > 0 else 0.0

    _, days_in_month = calendar.monthrange(year, month)

    # Calculate days elapsed for projection
    if year == today.year and month == today.month:
        days_elapsed = max(1, min(today.day, days_in_month))
        is_current_month = True
    elif date(year, month, days_in_month) < today:
        days_elapsed = days_in_month
        is_current_month = False
    else:
        # Future month
        days_elapsed = 0
        is_current_month = False

    if is_current_month and days_elapsed > 0:
        daily_rate = total_spent / days_elapsed
        projected_total = daily_rate * days_in_month
    else:
        daily_rate = (total_spent / days_in_month) if days_in_month > 0 else 0.0
        projected_total = total_spent

    # Budget summary for this month
    budget_info = get_budget_status(db, month, year)
    total_budget = budget_info["total_budgeted"]
    remaining_budget = budget_info["overall_remaining"]

    return {
        "month": month,
        "year": year,
        "month_name": get_month_name(month),
        "total_spent": round(total_spent, 2),
        "transaction_count": count,
        "average_transaction": round(avg_txn, 2),
        "total_budget": round(total_budget, 2),
        "remaining_budget": round(remaining_budget, 2),
        "days_in_month": days_in_month,
        "days_elapsed": days_elapsed,
        "daily_rate": round(daily_rate, 2),
        "projected_total": round(projected_total, 2),
        "is_current_month": is_current_month,
    }


def get_category_breakdown(
    db: Session,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """
    Calculates spending aggregated by category within the given date range.
    """
    results = (
        db.query(
            Expense.category,
            func.sum(Expense.amount).label("total_amount"),
            func.count(Expense.id).label("transaction_count"),
        )
        .filter(Expense.date >= start_date, Expense.date <= end_date)
        .group_by(Expense.category)
        .order_by(desc("total_amount"))
        .all()
    )

    total_spent = sum(float(r[1]) for r in results)

    breakdown = []
    for cat, amount, count in results:
        amount_float = float(amount)
        pct = (amount_float / total_spent * 100) if total_spent > 0 else 0.0
        breakdown.append({
            "category": cat,
            "total_amount": round(amount_float, 2),
            "transaction_count": count,
            "percentage": round(pct, 1),
        })

    return breakdown


def get_daily_spending(
    db: Session,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """
    Returns daily total spending within a date range for trend charting.
    """
    results = (
        db.query(
            Expense.date,
            func.sum(Expense.amount).label("daily_total"),
            func.count(Expense.id).label("transaction_count"),
        )
        .filter(Expense.date >= start_date, Expense.date <= end_date)
        .group_by(Expense.date)
        .order_by(Expense.date)
        .all()
    )

    return [
        {
            "date": r[0].isoformat(),
            "daily_total": round(float(r[1]), 2),
            "count": r[2],
        }
        for r in results
    ]


def get_monthly_trend(db: Session, num_months: int = 6) -> List[Dict[str, Any]]:
    """
    Fetches the total spending across the last `num_months` months.
    """
    today = date.today()
    trend_data = []

    # Iterate backwards from current month
    curr_y, curr_m = today.year, today.month
    months_to_check = []
    for _ in range(num_months):
        months_to_check.append((curr_y, curr_m))
        if curr_m == 1:
            curr_y -= 1
            curr_m = 12
        else:
            curr_m -= 1

    months_to_check.reverse()

    for y, m in months_to_check:
        s_date, e_date = get_month_date_range(y, m)
        spent = (
            db.query(func.coalesce(func.sum(Expense.amount), 0.0))
            .filter(Expense.date >= s_date, Expense.date <= e_date)
            .scalar()
        )
        trend_data.append({
            "label": f"{calendar.month_abbr[m]} {y}",
            "year": y,
            "month": m,
            "total_spent": round(float(spent), 2),
        })

    return trend_data


def get_top_expenses(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Returns the largest individual expense records for the period.
    """
    query = db.query(Expense)
    if start_date:
        query = query.filter(Expense.date >= start_date)
    if end_date:
        query = query.filter(Expense.date <= end_date)

    top_items = query.order_by(desc(Expense.amount)).limit(limit).all()
    return [e.to_dict() for e in top_items]


def compare_months(
    db: Session,
    m1: int,
    y1: int,
    m2: int,
    y2: int,
) -> Dict[str, Any]:
    """
    Compares two calendar months category-by-category.
    m1/y1: Base month (e.g. August 2026)
    m2/y2: Comparison month (e.g. September 2026)
    """
    s1, e1 = get_month_date_range(y1, m1)
    s2, e2 = get_month_date_range(y2, m2)

    cat_m1 = dict(
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(Expense.date >= s1, Expense.date <= e1)
        .group_by(Expense.category)
        .all()
    )
    cat_m2 = dict(
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(Expense.date >= s2, Expense.date <= e2)
        .group_by(Expense.category)
        .all()
    )

    all_cats = sorted(list(set(list(cat_m1.keys()) + list(cat_m2.keys()))))
    comparison_rows = []

    total_m1 = sum(cat_m1.values())
    total_m2 = sum(cat_m2.values())

    for cat in all_cats:
        spent1 = float(cat_m1.get(cat, 0.0))
        spent2 = float(cat_m2.get(cat, 0.0))
        delta = spent2 - spent1
        pct_change = ((delta / spent1) * 100) if spent1 > 0 else (100.0 if spent2 > 0 else 0.0)

        comparison_rows.append({
            "category": cat,
            "month1_spent": round(spent1, 2),
            "month2_spent": round(spent2, 2),
            "difference": round(delta, 2),
            "percentage_change": round(pct_change, 1),
        })

    # Sort by absolute difference descending
    comparison_rows.sort(key=lambda x: abs(x["difference"]), reverse=True)

    total_delta = total_m2 - total_m1
    total_pct_change = ((total_delta / total_m1) * 100) if total_m1 > 0 else 0.0

    return {
        "month1_label": f"{get_month_name(m1)} {y1}",
        "month2_label": f"{get_month_name(m2)} {y2}",
        "month1_total": round(total_m1, 2),
        "month2_total": round(total_m2, 2),
        "total_difference": round(total_delta, 2),
        "total_percentage_change": round(total_pct_change, 1),
        "categories": comparison_rows,
    }


def generate_insights(db: Session, month: int, year: int) -> List[Dict[str, str]]:
    """
    Generates deterministic data-driven financial insights for a given month:
    - Month-over-month category growth/drops
    - Largest spending category
    - Top transactions concentration
    - Budget utilization alerts
    """
    insights = []
    start_date, end_date = get_month_date_range(year, month)

    # 1. Category breakdown
    breakdown = get_category_breakdown(db, start_date, end_date)
    summary = get_monthly_summary(db, month, year)
    total_spent = summary["total_spent"]

    if total_spent == 0:
        return [{"icon": "ℹ️", "text": f"No spending recorded yet for {get_month_name(month)} {year}."}]

    # Top category insight
    if breakdown:
        top_cat = breakdown[0]
        insights.append({
            "icon": "💰",
            "type": "top_category",
            "text": f"{top_cat['category']} is your largest expense category at ₹{top_cat['total_amount']:,.2f} ({top_cat['percentage']}% of total).",
        })

    # 2. Month-over-month comparison
    prev_m = 12 if month == 1 else month - 1
    prev_y = year - 1 if month == 1 else year
    comp = compare_months(db, prev_m, prev_y, month, year)

    if comp["month1_total"] > 0:
        tot_diff = comp["total_difference"]
        tot_pct = comp["total_percentage_change"]
        if tot_diff > 0:
            insights.append({
                "icon": "📈",
                "type": "overall_increase",
                "text": f"Overall spending increased by ₹{abs(tot_diff):,.2f} (+{abs(tot_pct):.1f}%) compared to {comp['month1_label']}.",
            })
        elif tot_diff < 0:
            insights.append({
                "icon": "📉",
                "type": "overall_decrease",
                "text": f"Overall spending decreased by ₹{abs(tot_diff):,.2f} (-{abs(tot_pct):.1f}%) compared to {comp['month1_label']}.",
            })

        # Notable category changes
        for cat_row in comp["categories"]:
            if cat_row["month1_spent"] > 0 and abs(cat_row["difference"]) >= 300:
                diff = cat_row["difference"]
                pct = cat_row["percentage_change"]
                if diff > 0:
                    insights.append({
                        "icon": "📈",
                        "type": "category_increase",
                        "text": f"Your {cat_row['category']} spending increased by {pct:.1f}% (+₹{diff:,.2f}) vs last month.",
                    })
                else:
                    insights.append({
                        "icon": "📉",
                        "type": "category_decrease",
                        "text": f"Your {cat_row['category']} spending decreased by {abs(pct):.1f}% (-₹{abs(diff):,.2f}) vs last month.",
                    })
                break  # Pick top notable category change

    # 3. Budget alerts
    budget_status = get_budget_status(db, month, year)
    for cat_status in budget_status["categories"]:
        if cat_status["is_exceeded"]:
            insights.append({
                "icon": "🚨",
                "type": "budget_exceeded",
                "text": cat_status["alert_message"],
            })
        elif cat_status["is_warning"]:
            insights.append({
                "icon": "⚠️",
                "type": "budget_warning",
                "text": cat_status["alert_message"],
            })

    # 4. Transaction concentration
    top_txns = get_top_expenses(db, start_date, end_date, limit=3)
    if top_txns and total_spent > 0:
        top_3_sum = sum(t["amount"] for t in top_txns)
        top_3_pct = (top_3_sum / total_spent) * 100
        if len(top_txns) >= 3 and top_3_pct > 25:
            insights.append({
                "icon": "🛒",
                "type": "concentration",
                "text": f"Your 3 largest transactions account for {top_3_pct:.1f}% of your total spending.",
            })

    # 5. Projection insight (for current month)
    if summary["is_current_month"] and summary["days_elapsed"] < summary["days_in_month"]:
        proj = summary["projected_total"]
        insights.append({
            "icon": "🔮",
            "type": "projection",
            "text": f"Based on your current spending rate of ₹{summary['daily_rate']:,.2f}/day, your projected monthly total is ₹{proj:,.2f}.",
        })

    return insights

