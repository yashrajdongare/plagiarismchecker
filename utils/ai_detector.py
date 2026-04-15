"""AI detection module using ZeroGPT API."""

import os
import time
import requests

ZEROGPT_API_URL = "https://api.zerogpt.com/api/detect/detectText"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def detect_ai_content(text: str) -> dict:
    """Send text to ZeroGPT API and return analysis results.

    Args:
        text: The text to analyse.

    Returns:
        A dict with keys: ai_score, is_human, sentences, error (optional).
    """
    api_key = os.environ.get("ZEROGPT_API_KEY", "")

    if not api_key:
        return _fallback_result("ZeroGPT API key not configured (set ZEROGPT_API_KEY)")

    headers = {
        "Content-Type": "application/json",
        "ApiKey": api_key,
    }
    payload = {"input_text": text}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                ZEROGPT_API_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )

            if response.status_code == 429:
                # Rate limited – wait and retry
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue

            if response.status_code != 200:
                return _fallback_result(
                    f"ZeroGPT API returned status {response.status_code}"
                )

            data = response.json()
            result_data = data.get("data") or data

            ai_score = float(result_data.get("aiScore", result_data.get("fakePercentage", 0)))
            is_human = bool(result_data.get("isHuman", ai_score < 50))
            sentences = result_data.get("sentences", [])

            # Normalise sentence list
            normalised_sentences = _normalise_sentences(sentences, text)

            return {
                "ai_score": round(ai_score, 2),
                "is_human": is_human,
                "sentences": normalised_sentences,
                "error": None,
            }

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return _fallback_result("ZeroGPT API request timed out")

        except requests.exceptions.RequestException as exc:
            return _fallback_result(f"Network error: {exc}")

        except (ValueError, KeyError) as exc:
            return _fallback_result(f"Unexpected API response format: {exc}")

    return _fallback_result("ZeroGPT API rate limit exceeded after retries")


def _normalise_sentences(raw_sentences: list, full_text: str) -> list:
    """Convert raw ZeroGPT sentence data into a consistent list of dicts."""
    if not raw_sentences:
        # Build basic sentence list from the text
        import re
        parts = re.split(r"(?<=[.!?])\s+", full_text.strip())
        return [
            {"text": s.strip(), "ai_generated": False, "score": 0.0}
            for s in parts
            if s.strip()
        ]

    result = []
    for item in raw_sentences:
        if isinstance(item, dict):
            result.append(
                {
                    "text": item.get("sentence", item.get("text", "")),
                    "ai_generated": item.get("generated_by_ai", item.get("ai_generated", False)),
                    "score": float(item.get("score", item.get("ai_score", 0.0))),
                }
            )
        elif isinstance(item, str):
            result.append({"text": item, "ai_generated": False, "score": 0.0})
    return result


def _fallback_result(error_message: str) -> dict:
    """Return a safe fallback result when the API is unavailable."""
    return {
        "ai_score": 0.0,
        "is_human": True,
        "sentences": [],
        "error": error_message,
    }
