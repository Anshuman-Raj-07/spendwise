from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Expense, Budget, CATEGORIES
from services.expense_service import (
    add_expense,
    get_expenses,
    update_expense,
    delete_expense,
    batch_delete_expenses,
)
from services.budget_service import (
    set_or_update_budget,
    get_budget_status,
    batch_delete_budgets,
)
from services.analytics_service import (
    get_monthly_summary,
    get_category_breakdown,
    compare_months,
    generate_insights,
)
from services.ai_service import classify_intent_rule_based
from utils.helpers import validate_expense_input


@pytest.fixture
def test_db():
    """
    Creates an isolated in-memory SQLite database for unit tests.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# --- Test 1: Expense CRUD and Validations ---

def test_add_valid_expense(test_db):
    exp = add_expense(
        test_db,
        amount=250.50,
        category="Food",
        description="Lunch at college canteen",
        expense_date=date(2026, 9, 22),
    )
    assert exp.id is not None
    assert exp.amount == 250.50
    assert exp.category == "Food"
    assert exp.description == "Lunch at college canteen"
    assert exp.date == date(2026, 9, 22)


def test_invalid_expense_values(test_db):
    # Negative amount
    with pytest.raises(ValueError, match="greater than zero"):
        add_expense(test_db, amount=-50.0, category="Food", description="Test", expense_date=date.today())

    # Zero amount
    with pytest.raises(ValueError, match="greater than zero"):
        add_expense(test_db, amount=0.0, category="Food", description="Test", expense_date=date.today())

    # Empty description
    with pytest.raises(ValueError, match="cannot be empty"):
        add_expense(test_db, amount=100.0, category="Food", description="   ", expense_date=date.today())

    # Invalid category fallback
    exp = add_expense(test_db, amount=100.0, category="SpaceTravel", description="Flight to Mars", expense_date=date.today())
    assert exp.category == "Other"


def test_update_and_delete_expense(test_db):
    exp = add_expense(test_db, 150.0, "Transport", "Bus ticket", date(2026, 9, 20))
    updated = update_expense(test_db, exp.id, amount=200.0, description="Bus and Metro ticket")
    assert updated.amount == 200.0
    assert updated.description == "Bus and Metro ticket"

    success = delete_expense(test_db, exp.id)
    assert success is True
    assert delete_expense(test_db, 9999) is False


# --- Test 2: Calculating Total Spending & Category Totals ---

def test_spending_and_category_breakdown(test_db):
    d1 = date(2026, 9, 5)
    d2 = date(2026, 9, 10)
    add_expense(test_db, 500.0, "Food", "Groceries", d1)
    add_expense(test_db, 300.0, "Food", "Dinner", d2)
    add_expense(test_db, 200.0, "Transport", "Auto ride", d2)

    summary = get_monthly_summary(test_db, 9, 2026)
    assert summary["total_spent"] == 1000.0
    assert summary["transaction_count"] == 3
    assert summary["average_transaction"] == pytest.approx(333.33, 0.01)

    breakdown = get_category_breakdown(test_db, date(2026, 9, 1), date(2026, 9, 30))
    assert len(breakdown) == 2
    # Food should be first (800 total, 80%)
    assert breakdown[0]["category"] == "Food"
    assert breakdown[0]["total_amount"] == 800.0
    assert breakdown[0]["percentage"] == 80.0
    # Transport should be second (200 total, 20%)
    assert breakdown[1]["category"] == "Transport"
    assert breakdown[1]["total_amount"] == 200.0
    assert breakdown[1]["percentage"] == 20.0


# --- Test 3: Budget Calculations & Warning Thresholds ---

def test_budget_status_thresholds(test_db):
    month, year = 9, 2026
    # Set Food budget = 1000
    set_or_update_budget(test_db, "Food", 1000.0, month, year)
    # Set Transport budget = 500
    set_or_update_budget(test_db, "Transport", 500.0, month, year)

    # 1. Food spent = 750 (75% -> normal)
    add_expense(test_db, 750.0, "Food", "Weekly groceries", date(2026, 9, 5))
    status1 = get_budget_status(test_db, month, year)
    food_st = next(c for c in status1["categories"] if c["category"] == "Food")
    assert food_st["spent"] == 750.0
    assert food_st["remaining"] == 250.0
    assert food_st["percentage"] == 75.0
    assert food_st["is_warning"] is False
    assert food_st["is_exceeded"] is False

    # 2. Add 100 to Food -> total 850 (85% -> warning threshold >= 80%)
    add_expense(test_db, 100.0, "Food", "Bakery", date(2026, 9, 10))
    status2 = get_budget_status(test_db, month, year)
    food_st2 = next(c for c in status2["categories"] if c["category"] == "Food")
    assert food_st2["spent"] == 850.0
    assert food_st2["percentage"] == 85.0
    assert food_st2["is_warning"] is True
    assert food_st2["is_exceeded"] is False
    assert "85.0%" in food_st2["alert_message"]

    # 3. Add 200 to Food -> total 1050 (105% -> exceeded threshold > 100%)
    add_expense(test_db, 200.0, "Food", "Dinner", date(2026, 9, 15))
    status3 = get_budget_status(test_db, month, year)
    food_st3 = next(c for c in status3["categories"] if c["category"] == "Food")
    assert food_st3["spent"] == 1050.0
    assert food_st3["is_exceeded"] is True
    assert "exceeded by ₹50.00" in food_st3["alert_message"]


# --- Test 4: Monthly Comparison Calculations ---

def test_monthly_comparison(test_db):
    # August expenses
    add_expense(test_db, 3400.0, "Food", "August food", date(2026, 8, 10))
    add_expense(test_db, 2100.0, "Transport", "August transport", date(2026, 8, 15))

    # September expenses
    add_expense(test_db, 4250.0, "Food", "September food", date(2026, 9, 10))
    add_expense(test_db, 1800.0, "Transport", "September transport", date(2026, 9, 15))

    comp = compare_months(test_db, 8, 2026, 9, 2026)
    assert comp["month1_total"] == 5500.0
    assert comp["month2_total"] == 6050.0
    assert comp["total_difference"] == 550.0
    assert comp["total_percentage_change"] == pytest.approx(10.0, 0.1)

    # Check food delta (+850)
    food_row = next(r for r in comp["categories"] if r["category"] == "Food")
    assert food_row["difference"] == 850.0

    # Check transport delta (-300)
    trans_row = next(r for r in comp["categories"] if r["category"] == "Transport")
    assert trans_row["difference"] == -300.0


# --- Test 5: Deterministic Intent Classification Fallback ---

def test_rule_based_intent_classification():
    today = date(2026, 9, 22)

    # Category query
    res1 = classify_intent_rule_based("How much did I spend on food this month?", today)
    assert res1["intent"] == "CATEGORY_SPENDING"
    assert res1["category"] == "Food"

    # Top expenses query
    res2 = classify_intent_rule_based("What were my biggest expenses?", today)
    assert res2["intent"] == "TOP_EXPENSES"

    # Month comparison query
    res3 = classify_intent_rule_based("Compare my spending with last month", today)
    assert res3["intent"] == "MONTH_COMPARISON"

    # Budget query
    res4 = classify_intent_rule_based("Am I exceeding my budget?", today)
    assert res4["intent"] == "BUDGET_STATUS"


# --- Test 6: AI JSON Parsing & Category Fallback Logic ---

def test_ai_response_sanitization():
    # Test that unknown categories map safely to 'Other'
    from services.ai_service import parse_expense_with_ai
    
    # Without API key, should gracefully return default with error message rather than crash
    res = parse_expense_with_ai("Spent 100 on books", api_key="")
    assert res["error"] is not None
    assert "Gemini API key not configured" in res["error"]


# --- Test 7: Batch Delete Operations ---

def test_batch_delete_expenses(test_db):
    e1 = add_expense(test_db, 100.0, "Food", "Snack 1", date.today())
    e2 = add_expense(test_db, 200.0, "Food", "Snack 2", date.today())
    e3 = add_expense(test_db, 300.0, "Food", "Snack 3", date.today())

    assert test_db.query(Expense).count() == 3
    deleted = batch_delete_expenses(test_db, [e1.id, e3.id])
    assert deleted == 2
    assert test_db.query(Expense).count() == 1
    assert test_db.query(Expense).first().id == e2.id


def test_batch_delete_budgets(test_db):
    b1 = set_or_update_budget(test_db, "Food", 1000.0, 9, 2026)
    b2 = set_or_update_budget(test_db, "Transport", 500.0, 9, 2026)
    b3 = set_or_update_budget(test_db, "Bills", 1500.0, 9, 2026)

    assert test_db.query(Budget).count() == 3
    deleted = batch_delete_budgets(test_db, [b1.id, b2.id])
    assert deleted == 2
    assert test_db.query(Budget).count() == 1
    assert test_db.query(Budget).first().id == b3.id


def test_gemini_fallback_endpoints_configured():
    from services.ai_service import GEMINI_FALLBACK_ENDPOINTS
    assert len(GEMINI_FALLBACK_ENDPOINTS) >= 5
    assert any("gemini-1.5-flash" in ep for ep in GEMINI_FALLBACK_ENDPOINTS)
    assert any("gemini-2.0-flash" in ep for ep in GEMINI_FALLBACK_ENDPOINTS)
    assert any("gemini-flash-latest" in ep for ep in GEMINI_FALLBACK_ENDPOINTS)


def test_rank_latest_model_prioritization():
    from services.ai_service import rank_latest_model
    # 'latest' models should rank highest
    score_latest = rank_latest_model("models/gemini-flash-latest")
    score_2_flash = rank_latest_model("models/gemini-2.0-flash")
    score_1_5_flash = rank_latest_model("models/gemini-1.5-flash")
    score_pro = rank_latest_model("models/gemini-pro")

    assert score_latest > score_2_flash > score_1_5_flash > score_pro
    
    # Check sorting a list of discovered models
    models = ["models/gemini-1.5-flash", "models/gemini-pro", "models/gemini-flash-latest", "models/gemini-2.0-flash"]
    sorted_models = sorted(models, key=rank_latest_model, reverse=True)
    assert sorted_models[0] == "models/gemini-flash-latest"
    assert sorted_models[1] == "models/gemini-2.0-flash"


