"""
Lazy fix_summary generation for retrieved training tickets.

Strategy: generate summaries only for tickets that actually appear as
top-5 neighbors during a pipeline pass. This caps LLM calls to ~5000–10000
instead of all 38k training tickets.

Cache: results/fix_summaries.json (persisted between runs).
"""
import json
from pathlib import Path
from typing import Optional

from cortex.llm_client import LLMUnavailableError, complete

CACHE_PATH = Path(__file__).parent.parent / "results" / "fix_summaries.json"

_PROMPT = """\
Summarize the root cause and resolution of this Apache Spark JIRA issue \
in 1–2 sentences (max 250 characters). Be factual, concise, and technical. \
Do not start with "This ticket" or "The issue".

TICKET: {summary}
DESCRIPTION: {description}
COMMENTS: {comments}
RESOLUTION: {resolution}

Summary:"""


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def get_fix_summary(
    ticket_key: str,
    ticket_data: dict,
    cache: dict,
    prefer: str = "ollama",
) -> Optional[str]:
    """
    Return a cached or freshly generated fix summary.

    Parameters
    ----------
    ticket_key : str  — e.g. "SPARK-12345"
    ticket_data : dict — must have keys: summary_clean, description_clean,
                         comments_concat (or all_comments), resolution
    cache : dict  — mutable cache dict; updated in place on new generation
    prefer : "ollama" (default for batch) | "anthropic" (for interactive use)

    Returns None if LLM is unavailable.
    """
    if ticket_key in cache:
        return cache[ticket_key]

    summary     = str(ticket_data.get("summary_clean", "") or
                      ticket_data.get("summary", ""))[:300]
    description = str(ticket_data.get("description_clean", "") or
                      ticket_data.get("description", ""))[:1000]
    comments    = str(ticket_data.get("comments_concat", "") or
                      ticket_data.get("all_comments", ""))[:1500]
    resolution  = str(ticket_data.get("resolution", "Unknown"))

    prompt = _PROMPT.format(
        summary=summary,
        description=description,
        comments=comments,
        resolution=resolution,
    )
    try:
        text = complete(prompt, max_tokens=100, prefer=prefer)
        summary_out = text[:250]
        cache[ticket_key] = summary_out
        return summary_out
    except LLMUnavailableError:
        return None
