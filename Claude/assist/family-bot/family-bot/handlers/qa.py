from __future__ import annotations
"""
handlers/qa.py
Answers free-text questions about an event using OpenAI.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


SYSTEM_PROMPT = """
אתה עוזר משפחתי חכם. ענה בעברית בצורה קצרה וברורה.
אם חסר מידע, שאל שאלה אחת להבהרה במקום להמציא.
"""


def answer_event_question(question_text: str, event_context: dict | None = None) -> str:
    ctx = ""
    if event_context:
        title = event_context.get("title") or ""
        when = event_context.get("when") or ""
        where = event_context.get("location") or ""
        who = event_context.get("persona_name") or ""
        ctx = f"\nהקשר:\n- מי: {who}\n- פעילות: {title}\n- מתי: {when}\n- איפה: {where}\n"

    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_QA_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + ctx},
                {"role": "user", "content": question_text},
            ],
            temperature=0.2,
            max_tokens=250,
        )
        return (resp.choices[0].message.content or "").strip() or "לא הצלחתי לענות כרגע."
    except Exception as e:
        return "יש תקלה זמנית עם המענה. נסו שוב בעוד רגע."


def answer_event_question_multiturn(question_text: str, 
                                     event_context: dict | None = None,
                                     conversation_history: list | None = None) -> str:
    """
    Answers questions with full conversation history for context.
    conversation_history: list of {"role": "user"/"assistant", "content": "..."}
    """
    ctx = ""
    if event_context:
        title = event_context.get("title") or ""
        when = event_context.get("when") or ""
        where = event_context.get("location") or ""
        who = event_context.get("persona_name") or ""
        ctx = f"\nהקשר:\n- מי: {who}\n- פעילות: {title}\n- מתי: {when}\n- איפה: {where}\n"

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + ctx},
        ]
        
        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current question
        messages.append({"role": "user", "content": question_text})
        
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_QA_MODEL", "gpt-4o-mini"),
            messages=messages,
            temperature=0.2,
            max_tokens=250,
        )
        answer = (resp.choices[0].message.content or "").strip() or "לא הצלחתי לענות כרגע."
        return answer
    except Exception as e:
        return "יש תקלה זמנית עם המענה. נסו שוב בעוד רגע."

