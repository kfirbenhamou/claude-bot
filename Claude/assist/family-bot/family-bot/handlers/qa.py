from __future__ import annotations
"""
handlers/qa.py
Answers free-text questions about an event using Anthropic.
"""

import os

from services.llm import complete, complete_messages, DEFAULT_HAIKU

SYSTEM_PROMPT = """
אתה עוזר משפחתי חכם. ענה בעברית בצורה קצרה וברורה.
אם חסר מידע, שאל שאלה אחת להבהרה במקום להמציא.
"""

QA_MODEL = os.getenv("ANTHROPIC_QA_MODEL", DEFAULT_HAIKU)


def _build_context(event_context: dict | None) -> str:
    if not event_context:
        return ""
    title = event_context.get("title") or ""
    when = event_context.get("when") or ""
    where = event_context.get("location") or ""
    who = event_context.get("persona_name") or ""
    return f"\nהקשר:\n- מי: {who}\n- פעילות: {title}\n- מתי: {when}\n- איפה: {where}\n"


def answer_event_question(question_text: str, event_context: dict | None = None) -> str:
    ctx = _build_context(event_context)

    try:
        answer = complete(
            SYSTEM_PROMPT + ctx,
            question_text,
            model=QA_MODEL,
            max_tokens=250,
            temperature=0.2,
        )
        return answer or "לא הצלחתי לענות כרגע."
    except Exception:
        return "יש תקלה זמנית עם המענה. נסו שוב בעוד רגע."


def answer_event_question_multiturn(
    question_text: str,
    event_context: dict | None = None,
    conversation_history: list | None = None,
) -> str:
    """
    Answers questions with full conversation history for context.
    conversation_history: list of {"role": "user"/"assistant", "content": "..."}
    """
    ctx = _build_context(event_context)

    try:
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": question_text})

        answer = complete_messages(
            SYSTEM_PROMPT + ctx,
            messages,
            model=QA_MODEL,
            max_tokens=250,
            temperature=0.2,
        )
        return answer or "לא הצלחתי לענות כרגע."
    except Exception:
        return "יש תקלה זמנית עם המענה. נסו שוב בעוד רגע."
