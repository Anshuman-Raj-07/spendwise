from datetime import date
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database.models import Expense, CATEGORIES
from utils.helpers import validate_expense_input


def get_all_categories() -> List[str]:
    """
    Returns the fixed list of supported expense categories.
    """
    return list(CATEGORIES)


def add_expense(
    db: Session,
    amount: float,
    category: str,
    description: str,
    expense_date: date,
) -> Expense:
    """
    Validates and persists a new expense record into the database.
    """
    # Normalize category
    category = category.strip()
    if category not in CATEGORIES:
        category = "Other"

    # Validate inputs
    is_valid, err_msg = validate_expense_input(amount, category, description, expense_date)
    if not is_valid:
        raise ValueError(err_msg)

    expense = Expense(
        amount=round(float(amount), 2),
        category=category,
        description=description.strip(),
        date=expense_date,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def get_expenses(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Expense]:
    """
    Queries expenses with optional filtering by date range, category, and keyword search.
    Ordered by date descending, then id descending.
    """
    query = db.query(Expense)

    if start_date:
        query = query.filter(Expense.date >= start_date)
    if end_date:
        query = query.filter(Expense.date <= end_date)
    if category and category != "All":
        query = query.filter(Expense.category == category)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(Expense.description.ilike(term))

    query = query.order_by(desc(Expense.date), desc(Expense.id))

    if limit:
        query = query.limit(limit)

    return query.all()


def get_expense_by_id(db: Session, expense_id: int) -> Optional[Expense]:
    """
    Fetches a single expense record by ID.
    """
    return db.query(Expense).filter(Expense.id == expense_id).first()


def update_expense(
    db: Session,
    expense_id: int,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    expense_date: Optional[date] = None,
) -> Optional[Expense]:
    """
    Updates an existing expense record with validation.
    """
    expense = get_expense_by_id(db, expense_id)
    if not expense:
        return None

    new_amount = amount if amount is not None else expense.amount
    new_cat = category if category is not None else expense.category
    new_desc = description if description is not None else expense.description
    new_date = expense_date if expense_date is not None else expense.date

    if new_cat not in CATEGORIES:
        new_cat = "Other"

    is_valid, err_msg = validate_expense_input(new_amount, new_cat, new_desc, new_date)
    if not is_valid:
        raise ValueError(err_msg)

    expense.amount = round(float(new_amount), 2)
    expense.category = new_cat
    expense.description = new_desc.strip()
    expense.date = new_date

    db.commit()
    db.refresh(expense)
    return expense


def delete_expense(db: Session, expense_id: int) -> bool:
    """
    Deletes an expense record by ID. Returns True if deleted, False if not found.
    """
    expense = get_expense_by_id(db, expense_id)
    if not expense:
        return False

    db.delete(expense)
    db.commit()
    return True


def batch_delete_expenses(db: Session, expense_ids: List[int]) -> int:
    """
    Deletes multiple expenses by their IDs in a single atomic database transaction.
    Returns the number of records successfully deleted.
    """
    if not expense_ids:
        return 0

    deleted_count = (
        db.query(Expense)
        .filter(Expense.id.in_(expense_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted_count

