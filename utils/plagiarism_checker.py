"""Plagiarism checker using Google Custom Search API."""

import os
import re
import time
import requests

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def check_plagiarism(text: str) -> dict:
    """Split text into sentences and check each against Google Search.

    Args:
        text: The text to check for plagiarism.

    Returns:
        A dict with keys: plagiarism_score, plagiarised_sentences, error (optional).
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    search_engine_id = os.environ.get("GOOGLE_SEARCH_ENGINE_ID", "")

    sentences = _split_sentences(text)
    if not sentences:
        return _fallback_result("No sentences found in the submitted text")

    # Only check a representative sample to stay within API quotas
    sample = _select_sample(sentences)

    plagiarised = []
    total_checked = 0

    for sentence in sample:
        if len(sentence.split()) < 8:
            # Too short to be meaningful for plagiarism detection
            continue

        result = _search_sentence(sentence, api_key, search_engine_id)
        if result is None:
            continue

        total_checked += 1
        if result["is_match"]:
            plagiarised.append(
                {
                    "text": sentence,
                    "source_url": result.get("url", ""),
                    "source_title": result.get("title", ""),
                    "match_score": result.get("match_score", 0.0),
                }
            )

    if total_checked == 0:
        plagiarism_score = 0.0
    else:
        plagiarism_score = round((len(plagiarised) / total_checked) * 100, 2)

    # Annotate ALL sentences with plagiarism status
    plagiarised_texts = {p["text"] for p in plagiarised}
    annotated = []
    for s in sentences:
        annotated.append(
            {
                "text": s,
                "plagiarised": s in plagiarised_texts,
                "source_url": next(
                    (p["source_url"] for p in plagiarised if p["text"] == s), ""
                ),
            }
        )

    return {
        "plagiarism_score": plagiarism_score,
        "plagiarised_sentences": plagiarised,
        "annotated_sentences": annotated,
        "error": None,
    }


def _split_sentences(text: str) -> list:
    """Split text into individual sentences."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def _select_sample(sentences: list, max_sentences: int = 10) -> list:
    """Select a representative sample to limit API calls."""
    if len(sentences) <= max_sentences:
        return sentences
    step = len(sentences) // max_sentences
    return sentences[::step][:max_sentences]


def _search_sentence(sentence: str, api_key: str, cx: str) -> dict | None:
    """Query Google Custom Search for an exact sentence match."""
    if not api_key or not cx:
        return None

    query = f'"{sentence[:120]}"'
    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": 1,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                GOOGLE_SEARCH_URL,
                params=params,
                timeout=15,
            )

            if response.status_code == 429:
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue

            if response.status_code != 200:
                return None

            data = response.json()
            items = data.get("items", [])

            if not items:
                return {"is_match": False}

            top_item = items[0]
            snippet = top_item.get("snippet", "").lower()
            sentence_lower = sentence.lower()

            # Compute a simple overlap score
            words_in_sentence = set(sentence_lower.split())
            words_in_snippet = set(snippet.split())
            overlap = words_in_sentence & words_in_snippet
            match_score = round(
                len(overlap) / max(len(words_in_sentence), 1) * 100, 2
            )

            is_match = match_score >= 60

            return {
                "is_match": is_match,
                "match_score": match_score,
                "url": top_item.get("link", ""),
                "title": top_item.get("title", ""),
            }

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return None
        except requests.exceptions.RequestException:
            return None

    return None


def _fallback_result(error_message: str) -> dict:
    """Return a safe fallback when the service is unavailable."""
    return {
        "plagiarism_score": 0.0,
        "plagiarised_sentences": [],
        "annotated_sentences": [],
        "error": error_message,
    }
