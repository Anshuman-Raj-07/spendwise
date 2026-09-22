import os
import json
import re
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
import requests
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from database.models import Expense, Budget, CATEGORIES
from utils.helpers import get_month_date_range, get_month_name, format_currency
from services.expense_service import get_expenses
from services.budget_service import get_budget_status
from services.analytics_service import (
    get_monthly_summary,
    get_category_breakdown,
    get_top_expenses,
    compare_months,
)

# Cached working Gemini endpoint and model name to avoid repeated discovery requests
_CACHED_GEMINI_ENDPOINT: Optional[str] = None
_CACHED_GEMINI_MODEL: Optional[str] = None

# Fallback candidate model endpoints in order of preference using official 'latest' aliases first
GEMINI_FALLBACK_ENDPOINTS = [
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-latest:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro-latest:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent",
    "https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent",
]

# Allowed intents
INTENTS = [
    "TOTAL_SPENDING",
    "CATEGORY_SPENDING",
    "TOP_EXPENSES",
    "MONTH_COMPARISON",
    "CATEGORY_COMPARISON",
    "BUDGET_STATUS",
    "SPENDING_TRENDS",
    "GENERAL_ADVICE",
]


def get_gemini_api_key(api_key: Optional[str] = None) -> Optional[str]:
    """
    Returns the active Gemini API key from parameter or environment variables,
    sanitized of any leading/trailing quotes or whitespace.
    """
    raw = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not raw or not str(raw).strip():
        return None
    cleaned = str(raw).strip().strip("'\"").strip()
    if not cleaned or cleaned in ("your_gemini_api_key_here", "your_openai_api_key_here"):
        return None
    return cleaned


def rank_latest_model(name: str) -> float:
    """
    Ranks models dynamically so the most capable and newest 'latest' model is selected.
    Prefers flash variants for ultra-fast, responsive expense classification.
    """
    lower = name.lower()
    score = 0.0

    # 1. Prioritize explicit 'latest' models
    if "flash-latest" in lower or "latest-flash" in lower:
        score += 1000.0
    elif "pro-latest" in lower or "latest-pro" in lower:
        score += 800.0
    elif "latest" in lower:
        score += 700.0

    # 2. Extract numeric versions (e.g. 3.8, 3.0, 2.5, 2.0, 1.5)
    ver_match = re.search(r"gemini[^\d]*(\d+(?:\.\d+)?)", lower)
    if ver_match:
        try:
            score += float(ver_match.group(1)) * 100.0
        except ValueError:
            pass

    # 3. Prefer Flash over Pro for fast structured queries
    if "flash" in lower:
        score += 50.0

    # 4. Slight penalty for experimental / preview / tuning
    if "exp" in lower or "preview" in lower:
        score -= 20.0

    return score


def test_gemini_connection(api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Tests the provided Gemini API key against Google's ModelService
    and returns a structured diagnostic report detailing the latest detected model.
    """
    key = get_gemini_api_key(api_key)
    if not key:
        return {
            "success": False,
            "status_code": 0,
            "error_summary": "No Gemini API key provided. Please enter a key.",
            "help": "Get a free Gemini API key from Google AI Studio: https://aistudio.google.com/app/apikey",
        }

    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    params = {"key": key}

    last_error_text = ""
    last_status = 0

    for ver in ["v1beta", "v1"]:
        url = f"https://generativelanguage.googleapis.com/{ver}/models"
        try:
            r = requests.get(url, headers=headers, params=params, timeout=12)
            last_status = r.status_code
            last_error_text = r.text
            if r.status_code == 200:
                data = r.json()
                models = [
                    m["name"].replace("models/", "")
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                models.sort(key=rank_latest_model, reverse=True)
                latest_m = models[0] if models else "gemini-flash-latest"
                return {
                    "success": True,
                    "status_code": 200,
                    "version": ver,
                    "models": models,
                    "latest_model": latest_m,
                    "total_models": len(models),
                    "error_summary": None,
                }
            elif r.status_code in (400, 403):
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "error_summary": r.text,
                    "help": "API key was rejected by Google. Ensure you copied the exact key without spaces.",
                }
        except Exception as e:
            return {
                "success": False,
                "status_code": -1,
                "error_summary": str(e),
                "help": "Network error reaching Google APIs.",
            }

    return {
        "success": False,
        "status_code": last_status or 404,
        "error_summary": last_error_text or "Models endpoint returned 404.",
        "help": (
            "If using Google Cloud Console, enable 'Generative Language API'. "
            "Recommended: create a free direct key in 10s at https://aistudio.google.com/app/apikey"
        ),
    }


def discover_gemini_endpoint(api_key: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Queries Google's ModelService (ListModels) to dynamically discover which models
    are active for this specific key, automatically picking the newest/latest model.
    Returns (endpoint_url, model_name).
    """
    global _CACHED_GEMINI_ENDPOINT, _CACHED_GEMINI_MODEL
    if _CACHED_GEMINI_ENDPOINT and _CACHED_GEMINI_MODEL:
        return _CACHED_GEMINI_ENDPOINT, _CACHED_GEMINI_MODEL

    list_urls = [
        "https://generativelanguage.googleapis.com/v1beta/models",
        "https://generativelanguage.googleapis.com/v1/models",
    ]
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    params = {"key": api_key}

    for list_url in list_urls:
        try:
            resp = requests.get(list_url, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                supported = [
                    m["name"] for m in models
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                if supported:
                    supported.sort(key=rank_latest_model, reverse=True)
                    selected_full = supported[0]
                    model_clean = selected_full.replace("models/", "")
                    base = list_url.rstrip("/models")
                    if not selected_full.startswith("models/"):
                        selected_full = f"models/{selected_full}"
                    endpoint = f"{base}/{selected_full}:generateContent"
                    _CACHED_GEMINI_ENDPOINT = endpoint
                    _CACHED_GEMINI_MODEL = model_clean
                    return endpoint, model_clean
        except Exception:
            continue

    return None, None


def safe_json_loads(text: str) -> Dict[str, Any]:
    """
    Safely parses JSON even if wrapped in markdown code blocks.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
    return json.loads(cleaned)


def call_gemini_openai_compat(
    prompt: str,
    system_instruction: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Calls Google Gemini via the official OpenAI-compatible endpoint using latest models.
    """
    key = get_gemini_api_key(api_key)
    if not key:
        return None

    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    candidate_models = [
        "gemini-flash-latest",
        "gemini-2.0-flash",
        "gemini-pro-latest",
        "gemini-2.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash",
    ]

    for model in candidate_models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
        except Exception:
            continue
    return None


def call_gemini(
    prompt: str,
    system_instruction: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    api_key: Optional[str] = None,
    preferred_model: Optional[str] = None,
) -> str:
    """
    Executes a prompt against Google Gemini API using the latest model dynamically.
    Prioritizes dynamic discovery and official latest aliases.
    """
    global _CACHED_GEMINI_ENDPOINT, _CACHED_GEMINI_MODEL
    key = get_gemini_api_key(api_key)
    if not key:
        raise ValueError("Google Gemini API key not configured.")

    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    params = {"key": key}

    payload: Dict[str, Any] = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
        },
    }

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    endpoints_to_try = []

    # 1. If preferred model given, try that first
    if preferred_model:
        clean_pref = preferred_model.replace("models/", "")
        endpoints_to_try.append(f"https://generativelanguage.googleapis.com/v1beta/models/{clean_pref}:generateContent")

    # 2. Dynamic discovery of latest model
    discovered_ep, discovered_m = discover_gemini_endpoint(key)
    if discovered_ep and discovered_ep not in endpoints_to_try:
        endpoints_to_try.append(discovered_ep)

    # 3. Fallback to latest aliases and versions
    for ep in GEMINI_FALLBACK_ENDPOINTS:
        if ep not in endpoints_to_try:
            endpoints_to_try.append(ep)

    last_error = None
    for endpoint in endpoints_to_try:
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                params=params,
                json=payload,
                timeout=25,
            )

            # If responseMimeType is not supported on this endpoint, retry without it
            if response.status_code == 400 and "responseMimeType" in response.text and json_mode:
                fallback_payload = dict(payload)
                fallback_payload["generationConfig"] = {"temperature": temperature}
                response = requests.post(
                    endpoint,
                    headers=headers,
                    params=params,
                    json=fallback_payload,
                    timeout=25,
                )

            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        _CACHED_GEMINI_ENDPOINT = endpoint
                        return parts[0].get("text", "").strip()

            last_error = f"Status {response.status_code}: {response.text}"
            if response.status_code in (404, 400):
                continue
            else:
                raise RuntimeError(f"Gemini API Error ({response.status_code}): {response.text}")

        except requests.RequestException as re_err:
            last_error = str(re_err)
            continue

    # Try official OpenAI-compatible endpoint as final fallback
    compat_res = call_gemini_openai_compat(
        prompt=prompt,
        system_instruction=system_instruction,
        json_mode=json_mode,
        temperature=temperature,
        api_key=key,
    )
    if compat_res:
        return compat_res

    raise RuntimeError(
        f"All Gemini model endpoints failed.\nLast Error: {last_error}\n\n"
        f"Tip: If using Google Cloud, ensure the 'Generative Language API' is enabled. "
        f"Recommended: Get a free direct API key from Google AI Studio: https://aistudio.google.com/app/apikey"
    )


def parse_expense_rule_based(text: str, reference_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Intelligent regex & keyword expense parser that runs locally without an LLM.
    Guarantees 'Add with AI' works even if the Gemini API has network/key restrictions.
    """
    ref_date = reference_date or date.today()
    t = text.strip()

    # 1. Extract Amount
    amount = 0.0
    patterns = [
        r"[₹$€£]\s*([\d,]+(?:\.\d{1,2})?)",
        r"(?:rs\.?|inr|rupees)\s*([\d,]+(?:\.\d{1,2})?)",
        r"([\d,]+(?:\.\d{1,2})?)\s*(?:rs\.?|inr|rupees)",
        r"(?:spent|for|paid|cost)\s*([\d,]+(?:\.\d{1,2})?)",
        r"\b(\d+(?:\.\d{1,2})?)\b",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            val_str = m.group(1).replace(",", "")
            try:
                val = float(val_str)
                if val > 0:
                    amount = val
                    break
            except ValueError:
                continue

    # 2. Extract Category by keyword matching
    t_lower = t.lower()
    matched_cat = "Other"
    category_keywords = {
        "Food": ["lunch", "dinner", "breakfast", "canteen", "restaurant", "cafe", "coffee", "pizza", "burger", "biryani", "snack", "grocery", "groceries", "supermarket", "tea", "zomato", "swiggy", "food"],
        "Transport": ["auto", "cab", "uber", "ola", "metro", "bus", "train", "taxi", "rapido", "petrol", "fuel", "diesel", "fare", "flight", "ride"],
        "Shopping": ["shirt", "shoes", "clothes", "dress", "pant", "amazon", "flipkart", "myntra", "mall", "decathlon", "t-shirt"],
        "Bills": ["broadband", "wifi", "airtel", "jio", "electricity", "water", "rent", "recharge", "phone bill", "utility", "gas bill"],
        "Entertainment": ["movie", "cinema", "theatre", "netflix", "prime", "hotstar", "spotify", "concert", "game", "gaming"],
        "Education": ["course", "udemy", "coursera", "book", "textbook", "tuition", "coaching", "exam", "college fee", "fee"],
        "Healthcare": ["medicine", "pharmacy", "doctor", "hospital", "clinic", "apollo", "vitamins", "dental", "tablet"],
        "Electronics": ["keyboard", "mouse", "monitor", "laptop", "phone", "gadget", "headphones", "earbuds", "charger", "cable"],
    }
    for cat, kws in category_keywords.items():
        if any(kw in t_lower for kw in kws):
            matched_cat = cat
            break

    # 3. Extract Date
    parsed_date = ref_date
    if "yesterday" in t_lower:
        parsed_date = ref_date - timedelta(days=1)
    elif "day before yesterday" in t_lower:
        parsed_date = ref_date - timedelta(days=2)

    # 4. Clean Description
    clean_desc = t.strip()
    for prefix in ["i spent", "spent", "bought a", "bought an", "bought", "paid for", "paid"]:
        if clean_desc.lower().startswith(prefix):
            clean_desc = clean_desc[len(prefix):].strip()
            break
    clean_desc = clean_desc.capitalize()

    return {
        "amount": round(amount, 2),
        "category": matched_cat,
        "description": clean_desc or text.strip(),
        "date": parsed_date.isoformat(),
        "error": None,
    }


def parse_expense_with_ai(
    text: str,
    reference_date: Optional[date] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extracts structured expense fields from natural language text using Google Gemini.
    Returns:
    {
        "amount": float,
        "category": str,
        "description": str,
        "date": "YYYY-MM-DD",
        "error": Optional[str]
    }
    """
    ref_date = reference_date or date.today()
    key = get_gemini_api_key(api_key)

    if not key:
        fallback = parse_expense_rule_based(text, ref_date)
        fallback["error"] = "Gemini API key not configured. Extracted using built-in offline NLP engine. Review and save below."
        return fallback

    categories_str = ", ".join(CATEGORIES)
    system_instruction = f"""You are a personal expense assistant.
Extract structured expense data from the user's natural language input.
Today's reference date is: {ref_date.isoformat()} ({ref_date.strftime('%A')}).

ALLOWED CATEGORIES ONLY:
[{categories_str}]
If the expense does not clearly fit into one of these, use 'Other'.

Respond ONLY with a valid JSON object matching this schema:
{{
  "amount": <number, e.g. 250.0>,
  "category": <string, MUST be one of the allowed categories>,
  "description": <string, concise description of the expense>,
  "date": <string, ISO date YYYY-MM-DD. Resolve relative words like 'today', 'yesterday', 'this morning' using reference date>
}}"""

    try:
        raw_text = call_gemini(
            prompt=text,
            system_instruction=system_instruction,
            json_mode=True,
            temperature=0.0,
            api_key=key,
        )

        data = safe_json_loads(raw_text)

        # Validate and sanitize amount
        amount = 0.0
        try:
            amount = abs(float(data.get("amount", 0.0)))
        except (ValueError, TypeError):
            amount = 0.0

        # Validate category against strict whitelist
        raw_cat = str(data.get("category", "")).strip()
        matched_cat = "Other"
        for c in CATEGORIES:
            if c.lower() == raw_cat.lower():
                matched_cat = c
                break

        # Validate date
        raw_date_str = str(data.get("date", "")).strip()
        parsed_date = ref_date
        if raw_date_str:
            try:
                parsed_date = datetime.strptime(raw_date_str, "%Y-%m-%d").date()
            except ValueError:
                parsed_date = ref_date

        description = str(data.get("description", "")).strip() or text.strip()

        return {
            "amount": round(amount, 2),
            "category": matched_cat,
            "description": description,
            "date": parsed_date.isoformat(),
            "error": None,
        }

    except Exception as e:
        fallback = parse_expense_rule_based(text, ref_date)
        fallback["warning"] = (
            f"Gemini API Notice: {str(e)[:150]}...\n\n"
            f"💡 Extracted using SpendWise built-in offline NLP engine. You can review and edit all fields below before saving."
        )
        fallback["error"] = None
        return fallback


def classify_intent_rule_based(query: str, current_date: date) -> Dict[str, Any]:
    """
    Deterministic rule-based intent fallback when LLM is offline or not configured.
    Ensures the assistant answers queries seamlessly even without an API key.
    """
    q = query.lower()
    curr_month = current_date.month
    curr_year = current_date.year

    # Check for category mentions
    found_category = None
    for cat in CATEGORIES:
        if cat.lower() in q:
            found_category = cat
            break

    # Check for month mentions
    target_month = curr_month
    target_year = curr_year
    if "last month" in q or "previous month" in q:
        if curr_month == 1:
            target_month = 12
            target_year = curr_year - 1
        else:
            target_month = curr_month - 1

    if any(k in q for k in ["compare", "comparison", "difference between months"]):
        return {
            "intent": "MONTH_COMPARISON",
            "month1": 12 if target_month == 1 else target_month - 1,
            "year1": target_year - 1 if target_month == 1 else target_year,
            "month2": target_month,
            "year2": target_year,
        }

    if any(k in q for k in ["budget", "exceeded", "limit"]):
        return {
            "intent": "BUDGET_STATUS",
            "month": target_month,
            "year": target_year,
        }

    if any(k in q for k in ["biggest", "largest", "highest", "most expensive", "top expense"]):
        return {
            "intent": "TOP_EXPENSES",
            "month": target_month,
            "year": target_year,
            "limit": 5,
        }

    if found_category:
        return {
            "intent": "CATEGORY_SPENDING",
            "category": found_category,
            "month": target_month,
            "year": target_year,
        }

    if any(k in q for k in ["reduce", "save money", "advice", "tip", "cut down"]):
        return {
            "intent": "GENERAL_ADVICE",
            "month": target_month,
            "year": target_year,
        }

    # Default to total spending
    return {
        "intent": "TOTAL_SPENDING",
        "month": target_month,
        "year": target_year,
    }


def classify_user_intent(
    query: str,
    current_date: Optional[date] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classifies a natural language query into a structured query intent using Google Gemini.
    """
    ref_date = current_date or date.today()
    key = get_gemini_api_key(api_key)

    if not key:
        return classify_intent_rule_based(query, ref_date)

    categories_str = ", ".join(CATEGORIES)
    intents_str = ", ".join(INTENTS)

    system_instruction = f"""You are a financial query intent classifier.
Current date: {ref_date.isoformat()} (Month: {ref_date.month}, Year: {ref_date.year}).

Allowed Categories: [{categories_str}]
Allowed Intents: [{intents_str}]

Intent Descriptions:
- TOTAL_SPENDING: questions about overall spending in a month or period
- CATEGORY_SPENDING: questions about spending in a specific category
- TOP_EXPENSES: biggest, highest, or largest transactions
- MONTH_COMPARISON: comparing spending between two months
- CATEGORY_COMPARISON: comparing category amounts or asking which category costs the most
- BUDGET_STATUS: questions about budget limits, remaining budget, or overspending
- SPENDING_TRENDS: trends over time or weekly/daily spending
- GENERAL_ADVICE: requests for saving tips, reducing spending, or financial recommendations

Respond ONLY with valid JSON:
{{
  "intent": <one of allowed intents>,
  "category": <category string if applicable, else null>,
  "month": <integer 1-12, default to {ref_date.month}>,
  "year": <integer, default to {ref_date.year}>,
  "limit": <integer if top expenses, e.g. 5, else null>
}}"""

    try:
        raw_text = call_gemini(
            prompt=query,
            system_instruction=system_instruction,
            json_mode=True,
            temperature=0.0,
            api_key=key,
        )
        data = safe_json_loads(raw_text)

        intent = data.get("intent", "TOTAL_SPENDING")
        if intent not in INTENTS:
            intent = "TOTAL_SPENDING"

        cat = data.get("category")
        if cat:
            matched = None
            for c in CATEGORIES:
                if c.lower() == str(cat).lower():
                    matched = c
                    break
            cat = matched

        month = int(data.get("month") or ref_date.month)
        year = int(data.get("year") or ref_date.year)
        limit = int(data.get("limit") or 5)

        return {
            "intent": intent,
            "category": cat,
            "month": max(1, min(12, month)),
            "year": year,
            "limit": limit,
        }

    except Exception:
        return classify_intent_rule_based(query, ref_date)


def execute_intent_query(db: Session, intent_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes deterministic SQLite / Python calculations for the classified intent.
    NO arithmetic is delegated to the LLM.
    """
    intent = intent_data.get("intent", "TOTAL_SPENDING")
    month = intent_data.get("month", date.today().month)
    year = intent_data.get("year", date.today().year)
    cat = intent_data.get("category")

    start_date, end_date = get_month_date_range(year, month)

    if intent == "TOTAL_SPENDING":
        summary = get_monthly_summary(db, month, year)
        return {
            "intent": intent,
            "month_name": get_month_name(month),
            "year": year,
            "total_spent": summary["total_spent"],
            "transaction_count": summary["transaction_count"],
            "average_transaction": summary["average_transaction"],
            "total_budget": summary["total_budget"],
            "remaining_budget": summary["remaining_budget"],
            "projected_total": summary["projected_total"],
        }

    elif intent == "CATEGORY_SPENDING":
        target_cat = cat or "Food"
        breakdown = get_category_breakdown(db, start_date, end_date)
        cat_data = next((b for b in breakdown if b["category"].lower() == target_cat.lower()), None)
        total_for_cat = cat_data["total_amount"] if cat_data else 0.0
        count_for_cat = cat_data["transaction_count"] if cat_data else 0

        # Check budget for this category
        b_status = get_budget_status(db, month, year)
        b_cat = next((b for b in b_status["categories"] if b["category"].lower() == target_cat.lower()), None)

        recent_expenses = (
            db.query(Expense)
            .filter(
                Expense.date >= start_date,
                Expense.date <= end_date,
                Expense.category == target_cat,
            )
            .order_by(Expense.date.desc())
            .limit(5)
            .all()
        )

        return {
            "intent": intent,
            "category": target_cat,
            "month_name": get_month_name(month),
            "year": year,
            "total_spent": total_for_cat,
            "transaction_count": count_for_cat,
            "budget_limit": b_cat["monthly_limit"] if b_cat else 0.0,
            "budget_remaining": b_cat["remaining"] if b_cat else 0.0,
            "is_exceeded": b_cat["is_exceeded"] if b_cat else False,
            "recent_items": [f"{e.description} (₹{e.amount:,.2f} on {e.date})" for e in recent_expenses],
        }

    elif intent == "TOP_EXPENSES":
        limit = intent_data.get("limit", 5)
        top_items = get_top_expenses(db, start_date, end_date, limit=limit)
        return {
            "intent": intent,
            "month_name": get_month_name(month),
            "year": year,
            "items": top_items,
        }

    elif intent in ("MONTH_COMPARISON", "CATEGORY_COMPARISON"):
        prev_m = 12 if month == 1 else month - 1
        prev_y = year - 1 if month == 1 else year
        comp = compare_months(db, prev_m, prev_y, month, year)
        return {
            "intent": intent,
            "comparison": comp,
        }

    elif intent == "BUDGET_STATUS":
        b_status = get_budget_status(db, month, year)
        return {
            "intent": intent,
            "month_name": get_month_name(month),
            "year": year,
            "status": b_status,
        }

    elif intent in ("SPENDING_TRENDS", "GENERAL_ADVICE"):
        summary = get_monthly_summary(db, month, year)
        breakdown = get_category_breakdown(db, start_date, end_date)
        b_status = get_budget_status(db, month, year)
        top_txns = get_top_expenses(db, start_date, end_date, limit=3)
        return {
            "intent": intent,
            "month_name": get_month_name(month),
            "year": year,
            "total_spent": summary["total_spent"],
            "breakdown": breakdown[:3],  # top 3 categories
            "exceeded_budgets": [c for c in b_status["categories"] if c["is_exceeded"]],
            "top_txns": top_txns,
        }

    return {"intent": "UNKNOWN", "message": "Could not determine data requirement."}


def synthesize_ai_response(
    user_query: str,
    intent_data: Dict[str, Any],
    financial_result: Dict[str, Any],
    api_key: Optional[str] = None,
) -> str:
    """
    Feeds calculated numbers into Google Gemini (or deterministic fallback) to generate a friendly,
    clear response. Guarantees accuracy because arithmetic is already performed.
    """
    key = get_gemini_api_key(api_key)

    if not key:
        # Fallback offline deterministic template
        intent = financial_result.get("intent")
        if intent == "TOTAL_SPENDING":
            spent = format_currency(financial_result["total_spent"])
            cnt = financial_result["transaction_count"]
            m_name = financial_result["month_name"]
            y = financial_result["year"]
            return f"In **{m_name} {y}**, your total spending is **{spent}** across **{cnt} transactions**."

        elif intent == "CATEGORY_SPENDING":
            cat = financial_result["category"]
            spent = format_currency(financial_result["total_spent"])
            m_name = financial_result["month_name"]
            extra = ""
            if financial_result.get("budget_limit", 0) > 0:
                limit = format_currency(financial_result["budget_limit"])
                extra = f" (Budget: {limit})"
            return f"You have spent **{spent}** on **{cat}** in **{m_name}**{extra}."

        elif intent == "TOP_EXPENSES":
            items = financial_result.get("items", [])
            if not items:
                return "You have no recorded expenses for this period."
            lines = [f"- **{i['description']}**: {format_currency(i['amount'])} ({i['category']} on {i['date']})" for i in items]
            return "Here are your largest expenses:\n" + "\n".join(lines)

        elif intent in ("MONTH_COMPARISON", "CATEGORY_COMPARISON"):
            comp = financial_result.get("comparison", {})
            diff = format_currency(abs(comp.get("total_difference", 0)))
            pct = comp.get("total_percentage_change", 0)
            sign = "increased" if comp.get("total_difference", 0) >= 0 else "decreased"
            return f"Comparing **{comp.get('month1_label')}** to **{comp.get('month2_label')}**:\n\nTotal spending **{sign} by {diff}** ({pct:+.1f}%)."

        elif intent == "BUDGET_STATUS":
            st = financial_result.get("status", {})
            exceeded = st.get("exceeded_count", 0)
            spent = format_currency(st.get("total_spent", 0))
            budget = format_currency(st.get("total_budgeted", 0))
            return f"Total Budget: **{budget}** | Total Spent: **{spent}**.\nExceeded categories: **{exceeded}**."

        else:
            return "I analyzed your expense data. All calculations are performed accurately directly from your database."

    # When Gemini API key is available:
    system_instruction = """You are SpendWise, an intelligent and polite personal expense assistant.
You will be provided with:
1. The user's original question.
2. The classified intent.
3. PRE-CALCULATED, DETERMINISTIC financial facts from SQLite/Python.

CRITICAL RULES:
1. Rely EXCLUSIVELY on the pre-calculated numbers provided. DO NOT calculate or fabricate new numbers.
2. Format all money with the Indian Rupee symbol (₹).
3. Be concise, direct, helpful, and encouraging.
4. If asked for advice to reduce spending, provide 2-3 specific, actionable tips referencing the actual categories where they spend the most."""

    prompt = f"""User Question: "{user_query}"
Classified Intent: {json.dumps(intent_data)}
Deterministic Financial Data: {json.dumps(financial_result, default=str)}"""

    try:
        response_text = call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            json_mode=False,
            temperature=0.3,
            api_key=key,
        )
        return response_text
    except Exception as e:
        det_response = synthesize_ai_response(
            user_query=user_query,
            intent_data=intent_data,
            financial_result=financial_result,
            api_key=None,
        )
        return (
            f"{det_response}\n\n"
            f"> *Note: Gemini API notice ({str(e)[:90]}...). "
            f"Response synthesized directly from SpendWise deterministic analytics engine.*"
        )
