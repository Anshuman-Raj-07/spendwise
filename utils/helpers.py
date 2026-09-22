import calendar
from datetime import date, datetime, timedelta
from typing import Tuple, List, Dict, Any, Optional
from sqlalchemy.orm import Session
from database.models import Expense, Budget, CATEGORIES


def format_currency(amount: float, symbol: str = "₹") -> str:
    """
    Formats a float or int as an Indian Rupee string, e.g., ₹4,250.00 or ₹500.
    """
    if amount is None:
        return f"{symbol}0"
    if amount == int(amount):
        return f"{symbol}{int(amount):,}"
    return f"{symbol}{amount:,.2f}"


def get_month_date_range(year: int, month: int) -> Tuple[date, date]:
    """
    Returns (start_date, end_date) for a specific year and month.
    """
    first_day = date(year, month, 1)
    _, last_day_num = calendar.monthrange(year, month)
    last_day = date(year, month, last_day_num)
    return first_day, last_day


def get_month_name(month_number: int) -> str:
    """
    Returns the full month name for a given month number (1-12).
    """
    if 1 <= month_number <= 12:
        return calendar.month_name[month_number]
    return f"Month {month_number}"


def validate_expense_input(
    amount: Any,
    category: str,
    description: str,
    expense_date: Any,
) -> Tuple[bool, Optional[str]]:
    """
    Validates manual expense inputs according to business rules:
    - Amount must be positive numeric.
    - Category must not be empty and should be in allowed CATEGORIES.
    - Description must not be empty.
    - Date must be a valid date object or convertible string.
    """
    # Validate amount
    try:
        val = float(amount)
        if val <= 0:
            return False, "Amount must be greater than zero."
        if val > 10_000_000:
            return False, "Amount exceeds realistic transaction limit (₹1 Crore)."
    except (ValueError, TypeError):
        return False, "Amount must be a valid number."

    # Validate category
    if not category or not isinstance(category, str) or not category.strip():
        return False, "Category is required."

    # Validate description
    if not description or not isinstance(description, str) or not description.strip():
        return False, "Description cannot be empty."
    if len(description.strip()) > 255:
        return False, "Description cannot exceed 255 characters."

    # Validate date
    if expense_date is None:
        return False, "Date is required."

    if isinstance(expense_date, str):
        try:
            expense_date = datetime.strptime(expense_date, "%Y-%m-%d").date()
        except ValueError:
            return False, "Date must be in YYYY-MM-DD format."

    if not isinstance(expense_date, (date, datetime)):
        return False, "Invalid date format."

    # Prevent unreasonable future dates (e.g. more than 1 year ahead)
    today = date.today()
    if isinstance(expense_date, datetime):
        expense_date = expense_date.date()
    if expense_date > today + timedelta(days=365):
        return False, "Expense date cannot be more than a year in the future."

    return True, None


def seed_sample_data(db: Session, force_clean: bool = False) -> Dict[str, int]:
    """
    Seeds the database with realistic sample expense and budget records spanning 3 months.
    Useful for quick demonstration and testing.
    """
    if force_clean:
        db.query(Expense).delete()
        db.query(Budget).delete()
        db.commit()

    existing_expenses_count = db.query(Expense).count()
    if existing_expenses_count > 0 and not force_clean:
        return {"expenses_added": 0, "budgets_added": 0, "already_seeded": True}

    today = date.today()
    # Month 1: Current month
    m1_year, m1_month = today.year, today.month

    # Month 2: Previous month
    if m1_month == 1:
        m2_year, m2_month = m1_year - 1, 12
    else:
        m2_year, m2_month = m1_year, m1_month - 1

    # Month 3: Two months ago
    if m2_month == 1:
        m3_year, m3_month = m2_year - 1, 12
    else:
        m3_year, m3_month = m2_year, m2_month - 1

    # Define standard budgets for the current month
    default_budgets = [
        {"category": "Food", "monthly_limit": 5000.0, "month": m1_month, "year": m1_year},
        {"category": "Transport", "monthly_limit": 2500.0, "month": m1_month, "year": m1_year},
        {"category": "Shopping", "monthly_limit": 3000.0, "month": m1_month, "year": m1_year},
        {"category": "Bills", "monthly_limit": 2000.0, "month": m1_month, "year": m1_year},
        {"category": "Entertainment", "monthly_limit": 1500.0, "month": m1_month, "year": m1_year},
        {"category": "Education", "monthly_limit": 1500.0, "month": m1_month, "year": m1_year},
        # Also set for previous month
        {"category": "Food", "monthly_limit": 5000.0, "month": m2_month, "year": m2_year},
        {"category": "Transport", "monthly_limit": 2500.0, "month": m2_month, "year": m2_year},
        {"category": "Shopping", "monthly_limit": 3000.0, "month": m2_month, "year": m2_year},
        {"category": "Bills", "monthly_limit": 2000.0, "month": m2_month, "year": m2_year},
    ]

    for b in default_budgets:
        existing = db.query(Budget).filter_by(
            category=b["category"], month=b["month"], year=b["year"]
        ).first()
        if not existing:
            db.add(Budget(**b))

    # Realistic sample transactions
    # Day offsets relative to today
    def safe_date(y: int, m: int, d: int) -> date:
        _, max_days = calendar.monthrange(y, m)
        return date(y, m, min(d, max_days))

    sample_expenses = [
        # Current month expenses
        (450.0, "Food", "Grocery shopping at Reliance Fresh", safe_date(m1_year, m1_month, 2)),
        (120.0, "Transport", "Metro smart card recharge", safe_date(m1_year, m1_month, 3)),
        (280.0, "Food", "Lunch at college canteen with friends", safe_date(m1_year, m1_month, 5)),
        (1499.0, "Bills", "Airtel fiber broadband bill", safe_date(m1_year, m1_month, 6)),
        (750.0, "Entertainment", "Movie ticket & popcorn for Inception screening", safe_date(m1_year, m1_month, 8)),
        (180.0, "Transport", "Auto ride to railway station", safe_date(m1_year, m1_month, 10)),
        (1200.0, "Shopping", "New formal shirt for college presentations", safe_date(m1_year, m1_month, 12)),
        (350.0, "Food", "Dominos Pizza delivery", safe_date(m1_year, m1_month, 13)),
        (499.0, "Education", "Udemy Python Full Stack Course", safe_date(m1_year, m1_month, 15)),
        (2500.0, "Electronics", "Logitech Mechanical Keyboard for coding", safe_date(m1_year, m1_month, 16)),
        (150.0, "Food", "Cafe coffee & cookies", safe_date(m1_year, m1_month, 18)),
        (220.0, "Transport", "Uber cab from coaching center", safe_date(m1_year, m1_month, 19)),
        (380.0, "Healthcare", "Vitamins and medicine from Apollo Pharmacy", safe_date(m1_year, m1_month, 20)),
        (650.0, "Food", "Weekend dinner at Biryani Blues", safe_date(m1_year, m1_month, 21)),

        # Previous month expenses (for comparison)
        (520.0, "Food", "Weekly supermarket groceries", safe_date(m2_year, m2_month, 3)),
        (1499.0, "Bills", "Airtel fiber broadband bill", safe_date(m2_year, m2_month, 5)),
        (850.0, "Transport", "Monthly local train season pass", safe_date(m2_year, m2_month, 6)),
        (120.0, "Transport", "Bus fare to tech conference", safe_date(m2_year, m2_month, 8)),
        (1850.0, "Shopping", "Sports shoes from Decathlon", safe_date(m2_year, m2_month, 11)),
        (420.0, "Food", "Dinner with classmates", safe_date(m2_year, m2_month, 14)),
        (499.0, "Entertainment", "Netflix standard subscription", safe_date(m2_year, m2_month, 15)),
        (750.0, "Education", "Data Structures & Algorithms reference textbook", safe_date(m2_year, m2_month, 18)),
        (1500.0, "Shopping", "Noise cancelling wireless earbuds", safe_date(m2_year, m2_month, 22)),
        (600.0, "Food", "Zomato dinner order", safe_date(m2_year, m2_month, 25)),
        (310.0, "Transport", "Rapido bike taxi rides across week", safe_date(m2_year, m2_month, 27)),

        # Two months ago expenses
        (1499.0, "Bills", "Broadband internet recharge", safe_date(m3_year, m3_month, 4)),
        (3200.0, "Food", "Monthly hostel mess and groceries", safe_date(m3_year, m3_month, 10)),
        (1200.0, "Transport", "Cab rides and metro travel", safe_date(m3_year, m3_month, 15)),
        (800.0, "Shopping", "Stationery, notebooks and pens", safe_date(m3_year, m3_month, 20)),
    ]

    for amount, category, desc, exp_date in sample_expenses:
        db.add(Expense(
            amount=amount,
            category=category,
            description=desc,
            date=exp_date,
        ))

    db.commit()
    return {
        "expenses_added": len(sample_expenses),
        "budgets_added": len(default_budgets),
        "already_seeded": False,
    }

