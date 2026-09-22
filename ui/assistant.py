from datetime import date
import streamlit as st
from sqlalchemy.orm import Session

from services.ai_service import (
    classify_user_intent,
    execute_intent_query,
    synthesize_ai_response,
    get_gemini_api_key,
)
from utils.helpers import format_currency


def render_assistant(db: Session, api_key: str = None):
    """
    Renders the Ask SpendWise conversational assistant.
    Features:
    - Interactive chat history
    - Quick-question sample prompt buttons
    - Architecture transparency drawer (showing intent, SQL parameters, and deterministic numbers)
    - Full offline capability (rule-based fallback when no API key is provided)
    """
    st.title("💬 Ask SpendWise — AI Financial Assistant")
    st.markdown(
        "Ask questions about your finances in plain English. SpendWise analyzes your actual stored "
        "expense records and uses deterministic calculations to give you accurate insights."
    )

    gemini_key = get_gemini_api_key(api_key)
    if not gemini_key:
        st.info(
            "💡 **Running in Deterministic Mode:** No active Google Gemini API key detected. "
            "SpendWise is answering your queries using its deterministic rule-based query engine. "
            "To enable conversational Gemini synthesis, add `GEMINI_API_KEY` in the sidebar or `.env`."
        )

    # Initialize chat history in session state
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {
                "role": "assistant",
                "content": (
                    "Hello! I am your SpendWise Assistant. You can ask me questions like:\n\n"
                    "- *'How much did I spend on food this month?'*\n"
                    "- *'What was my biggest expense?'*\n"
                    "- *'Compare my spending with last month.'*\n"
                    "- *'Am I close to exceeding any budget?'*\n"
                    "- *'Give me advice to reduce unnecessary spending.'*"
                ),
                "details": None,
            }
        ]

    # Quick prompt buttons
    st.markdown("##### 💡 Try asking:")
    q_cols = st.columns(4)
    quick_query = None
    if q_cols[0].button("🍔 Food spending this month"):
        quick_query = "How much did I spend on food this month?"
    if q_cols[1].button("🏆 Biggest expenses"):
        quick_query = "What were my biggest expenses?"
    if q_cols[2].button("📊 Compare with last month"):
        quick_query = "Compare my spending with last month."
    if q_cols[3].button("🎯 Budget status & alerts"):
        quick_query = "Am I close to exceeding any budget?"

    # Render previous conversation
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("details"):
                with st.expander("🔍 Inspection: Intent & Deterministic Calculation"):
                    st.json(msg["details"])

    # Handle user input from chat input or quick prompt button
    user_input = st.chat_input("Ask a question about your spending...") or quick_query

    if user_input:
        # Display user message
        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Assistant response generation
        with st.chat_message("assistant"):
            with st.spinner("Analyzing financial data..."):
                today = date.today()

                # Step 1: Intent Classification
                intent_data = classify_user_intent(user_input, current_date=today, api_key=api_key)

                # Step 2: Deterministic Database & Python Calculation
                financial_result = execute_intent_query(db, intent_data)

                # Step 3: Response Synthesis
                response_text = synthesize_ai_response(
                    user_query=user_input,
                    intent_data=intent_data,
                    financial_result=financial_result,
                    api_key=api_key,
                )

                st.markdown(response_text)

                # Architecture transparency drawer
                details_payload = {
                    "classified_intent": intent_data,
                    "deterministic_financial_facts": financial_result,
                }
                with st.expander("🔍 Inspection: Intent & Deterministic Calculation"):
                    st.json(details_payload)

                st.session_state["chat_history"].append({
                    "role": "assistant",
                    "content": response_text,
                    "details": details_payload,
                })

