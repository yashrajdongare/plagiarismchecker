"""AI detection module using ZeroGPT API with local heuristic fallback."""

import math
import os
import re
import time
import requests

ZEROGPT_API_URL = "https://api.zerogpt.com/api/detect/detectText"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Phrases that appear disproportionately in AI-generated text
_AI_PHRASES = [
    "in conclusion", "in summary", "to summarize", "it is important to note",
    "it is worth noting", "it should be noted", "it is crucial", "it is essential",
    "furthermore", "moreover", "additionally", "as a result", "therefore",
    "plays a crucial role", "in today's world", "in today's society",
    "in the realm of", "delve into", "groundbreaking", "leverage", "utilize",
    "facilitate", "it is clear that", "one can argue", "it can be seen",
    "it is evident", "pivotal", "paramount", "transformative", "revolutionary",
    "cutting-edge", "paradigm", "synergy", "navigate", "foster", "underscore",
    "it is noteworthy", "a testament to", "shed light on", "take into account",
    "on the other hand", "in this essay", "this essay will", "as mentioned above",
]

# Words/phrases that strongly suggest informal human writing
_INFORMAL_MARKERS = [
    "gonna", "wanna", "kinda", "sorta", "yeah", "yep", "nope", "dunno",
    "lemme", "gimme", "ain't", "y'all", "tbh", "imo", "lol", "omg",
    "btw", "idk", "smh", "bruh", "bro", "dude",
]


def detect_ai_content(text: str) -> dict:
    """Detect AI-generated content, using ZeroGPT API when available and
    falling back to a local heuristic otherwise.

    Args:
        text: The text to analyse.

    Returns:
        A dict with keys: ai_score, is_human, sentences, error (optional).
    """
    api_key = os.environ.get("ZEROGPT_API_KEY", "")

    if not api_key:
        return _local_heuristic_detection(
            text,
            error="ZeroGPT API key not configured – using local heuristic detection "
                  "(less accurate; set ZEROGPT_API_KEY for best results)",
        )

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
                return _local_heuristic_detection(
                    text,
                    error=f"ZeroGPT API returned status {response.status_code} – "
                          "using local heuristic detection",
                )

            data = response.json()
            result_data = data.get("data") if isinstance(data.get("data"), dict) else data

            # Support multiple field name variants used across ZeroGPT API versions
            ai_score = float(
                result_data.get("fakePercentage")
                or result_data.get("fake_percentage")
                or result_data.get("aiScore")
                or result_data.get("ai_score")
                or 0
            )

            # ZeroGPT returns isHuman as 0 (AI) or 1 (human); treat absent field
            # conservatively by inferring from the score.
            raw_is_human = result_data.get("isHuman")
            if raw_is_human is None:
                is_human = ai_score < 50
            else:
                is_human = bool(int(raw_is_human))

            raw_sentences = result_data.get("sentences") or []
            normalised_sentences = _normalise_sentences(raw_sentences, text, ai_score)

            # Blend the ZeroGPT score with the local heuristic to improve accuracy
            local = _local_heuristic_detection(text)
            blended_score = round(ai_score * 0.7 + local["ai_score"] * 0.3, 2)

            return {
                "ai_score": blended_score,
                "is_human": blended_score < 50,
                "sentences": normalised_sentences,
                "error": None,
            }

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return _local_heuristic_detection(
                text, error="ZeroGPT API request timed out – using local heuristic detection"
            )

        except requests.exceptions.RequestException as exc:
            return _local_heuristic_detection(
                text, error=f"Network error: {exc} – using local heuristic detection"
            )

        except (ValueError, KeyError) as exc:
            return _local_heuristic_detection(
                text,
                error=f"Unexpected API response format: {exc} – using local heuristic detection",
            )

    return _local_heuristic_detection(
        text,
        error="ZeroGPT API rate limit exceeded after retries – using local heuristic detection",
    )


def _normalise_sentences(raw_sentences: list, full_text: str, overall_ai_score: float = 0.0) -> list:
    """Convert raw ZeroGPT sentence data into a consistent list of dicts.

    When ZeroGPT does not provide a per-sentence AI score, AI-flagged sentences
    inherit the overall document AI score so the UI displays a meaningful value.
    """
    if not raw_sentences:
        # Build basic sentence list from the text
        parts = re.split(r"(?<=[.!?])\s+", full_text.strip())
        return [
            {"text": s.strip(), "ai_generated": False, "score": 0.0}
            for s in parts
            if s.strip()
        ]

    result = []
    for item in raw_sentences:
        if isinstance(item, dict):
            ai_flag = bool(item.get("generated_by_ai") or item.get("ai_generated"))

            # ZeroGPT returns perplexity (lower = more AI-like) and burstiness.
            # Derive a 0-100 score: invert a normalised perplexity value, capped at 100.
            perplexity = item.get("perplexity")
            raw_score = item.get("score") or item.get("ai_score")
            if raw_score is not None:
                sentence_score = float(raw_score)
            elif perplexity is not None:
                # Lower perplexity → higher AI probability (cap at 100)
                sentence_score = min(max(100 - float(perplexity) * 2, 0), 100)
            elif ai_flag:
                sentence_score = overall_ai_score
            else:
                sentence_score = 0.0

            result.append(
                {
                    "text": item.get("sentence") or item.get("text", ""),
                    "ai_generated": ai_flag,
                    "score": round(sentence_score, 2),
                }
            )
        elif isinstance(item, str):
            result.append({"text": item, "ai_generated": False, "score": 0.0})
    return result


def _local_heuristic_detection(text: str, error: str | None = None) -> dict:
    """Statistical heuristic AI detection used when ZeroGPT is unavailable.

    Combines four signals:
    1. Density of known AI-favoured phrases.
    2. Sentence-length uniformity (AI text is more uniform than human text).
    3. Absence of informal language (AI rarely uses slang).
    4. Low personal-pronoun usage (AI is typically impersonal).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    words = text.lower().split()

    if not sentences or not words:
        return {"ai_score": 0.0, "is_human": True, "sentences": [], "error": error}

    text_lower = text.lower()

    # ── Signal 1: AI phrase density (primary – 0–60 pts) ──────────────────
    # Specific phrases are the strongest indicator of AI authorship.
    phrase_hits = sum(1 for p in _AI_PHRASES if p in text_lower)
    phrase_score = min(phrase_hits * 6, 60)

    # ── Signal 2: Sentence-length uniformity (secondary – 0–25 pts) ────────
    # AI text tends to have more uniform sentence lengths than human text.
    sent_lengths = [len(s.split()) for s in sentences if len(s.split()) > 2]
    if len(sent_lengths) > 2:
        mean = sum(sent_lengths) / len(sent_lengths)
        std = math.sqrt(sum((x - mean) ** 2 for x in sent_lengths) / len(sent_lengths))
        cv = std / max(mean, 1)  # coefficient of variation
        # Low CV (≤ 0.35) suggests AI-style uniformity
        uniformity_score = max(0.0, (0.5 - cv) / 0.5) * 25
    else:
        uniformity_score = 5.0  # short text – uncertain

    # ── Signal 3: Absence of informal language (secondary – 0–10 pts) ──────
    informal_hits = sum(1 for m in _INFORMAL_MARKERS if m in text_lower)
    formality_score = max(0, 10 - informal_hits * 5)

    # ── Signal 4: Low personal-pronoun usage (secondary – 0–5 pts) ─────────
    personal = ["i ", "i'm", "i've", "i'd", "i'll", "my ", "mine "]
    pronoun_count = sum(text_lower.count(p) for p in personal)
    pronoun_ratio = pronoun_count / max(len(sentences), 1)
    pronoun_score = max(0.0, 5.0 - pronoun_ratio * 5)

    # Signals 2–4 only contribute meaningfully when there are also phrase hits;
    # without phrase hits they act as a mild uncertainty signal (max 15 pts),
    # keeping genuinely neutral human text below the 40% AI threshold.
    secondary_cap = 40 if phrase_hits > 0 else 15
    secondary_score = min(uniformity_score + formality_score + pronoun_score, secondary_cap)

    total_score = min(phrase_score + secondary_score, 100.0)

    # ── Per-sentence annotation ─────────────────────────────────────────────
    sentence_results = []
    for s in sentences:
        s_lower = s.lower()
        s_phrase_hits = sum(1 for p in _AI_PHRASES if p in s_lower)
        s_score = min(s_phrase_hits * 30 + (15 if len(s.split()) > 25 else 0), 100)
        sentence_results.append(
            {
                "text": s,
                "ai_generated": bool(s_phrase_hits > 0 or s_score >= 30),
                "score": round(float(s_score), 2),
            }
        )

    return {
        "ai_score": round(float(total_score), 2),
        "is_human": total_score < 40,
        "sentences": sentence_results,
        "error": error,
    }
