from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Standard expense categories supported by SpendWise
CATEGORIES = [
    "Food",
    "Transport",
    "Shopping",
    "Education",
    "Entertainment",
    "Bills",
    "Healthcare",
    "Electronics",
    "Other",
]


class Expense(Base):
    """
    Represents an individual financial transaction.
    """
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    amount = Column(Float, nullable=False)
    category = Column(String(50), nullable=False, index=True)
    description = Column(String(255), nullable=False)
    date = Column(Date, nullable=False, index=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "amount": self.amount,
            "category": self.category,
            "description": self.description,
            "date": self.date.isoformat() if self.date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Expense(id={self.id}, amount={self.amount}, category='{self.category}', date='{self.date}')>"


class Budget(Base):
    """
    Represents a spending budget allocated to a specific category for a given month and year.
    """
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(50), nullable=False)
    monthly_limit = Column(Float, nullable=False)
    month = Column(Integer, nullable=False)  # 1 - 12
    year = Column(Integer, nullable=False)   # e.g. 2026

    __table_args__ = (
        UniqueConstraint("category", "month", "year", name="uq_category_month_year"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "monthly_limit": self.monthly_limit,
            "month": self.month,
            "year": self.year,
        }

    def __repr__(self):
        return (
            f"<Budget(id={self.id}, category='{self.category}', limit={self.monthly_limit}, "
            f"period={self.month}/{self.year})>"
        )

