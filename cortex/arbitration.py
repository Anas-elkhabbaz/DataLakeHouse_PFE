"""
Constrained LLM arbitration for low-confidence predictions.

When the confidence gate routes a prediction to LLM_REQUIRED, this module
sends the ticket + top-5 neighbors to the LLM and normalizes the response
to the nearest valid label via edit distance.

Returns None if no LLM backend is available (caller falls back to DIRECT).
"""
from typing import Optional

from rapidfuzz.distance import Levenshtein

from cortex.llm_client import LLMUnavailableError, complete

ISSUETYPE_LABELS = [
    "Bug", "Improvement", "Sub-task", "New Feature",
    "Task", "Test", "Documentation", "Question", "Other",
]
RESOLUTION_LABELS = [
    "Fixed", "Won't Fix", "Duplicate", "Invalid",
    "Cannot Reproduce", "Incomplete", "Not A Problem",
]

_PROMPT_TEMPLATE = """\
You are classifying an Apache Spark JIRA issue. \
Return ONLY the single most likely {target} label from this exact list:

{labels}

Ticket:
{ticket_text}

Top {n} most similar past tickets (label → excerpt):
{neighbors}

Return ONLY the label name. No explanation, no quotes, no punctuation."""


def normalize_to_label(response: str, labels: list[str]) -> str:
    """Map any LLM output to the nearest valid label via edit distance."""
    cleaned = response.strip().strip('"').strip("'")
    # Exact match first (case-insensitive)
    for lbl in labels:
        if lbl.lower() == cleaned.lower():
            return lbl
    # Nearest by edit distance
    return min(labels, key=lambda L: Levenshtein.distance(cleaned.lower(), L.lower()))


def arbitrate(
    ticket_text: str,
    neighbors: list[dict],
    target: str = "issuetype",
    prefer: str = "anthropic",
) -> Optional[str]:
    """
    Ask the LLM to pick the best label for a low-confidence prediction.

    Parameters
    ----------
    ticket_text : str
        The text_noco of the query ticket (truncated at 1500 chars internally).
    neighbors : list of dict
        Each dict should have keys 'label' and 'text' (the neighbor's text_noco).
    target : "issuetype" or "resolution"
    prefer : "anthropic" | "ollama"

    Returns
    -------
    str | None
        Normalized label string, or None if LLM is unavailable.
    """
    labels = ISSUETYPE_LABELS if target == "issuetype" else RESOLUTION_LABELS
    neighbors_str = "\n".join(
        f"[{n.get('label', '?')}] {str(n.get('text', ''))[:250]}"
        for n in neighbors[:5]
    )
    prompt = _PROMPT_TEMPLATE.format(
        target=target,
        labels=", ".join(labels),
        ticket_text=ticket_text[:1500],
        n=min(5, len(neighbors)),
        neighbors=neighbors_str,
    )
    try:
        raw = complete(prompt, max_tokens=20, prefer=prefer)
        return normalize_to_label(raw, labels)
    except LLMUnavailableError:
        return None
