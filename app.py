"""TruthScript – AI & Plagiarism Content Detector
Flask backend entry point.
"""

import csv
import io
import os
import re
import sqlite3
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for

from utils.ai_detector import detect_ai_content
from utils.plagiarism_checker import check_plagiarism
from utils.report_generator import generate_pdf_report

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB upload limit

# ── Database setup ─────────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "submissions.db")


def get_db():
    """Return a connection to the SQLite database, creating it if necessary."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialise the database schema."""
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT,
            document_title TEXT,
            word_count  INTEGER,
            ai_score    REAL,
            plagiarism_score REAL,
            originality_score REAL,
            verdict     TEXT,
            submitted_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Render the home page."""
    return render_template("index.html")


@app.route("/results")
def results():
    """Render the results dashboard page."""
    return render_template("results.html")


@app.route("/history")
def history():
    """Return submission history as JSON."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM submissions ORDER BY submitted_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/export-csv")
def export_csv():
    """Export submission history as a CSV file."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM submissions ORDER BY submitted_at DESC"
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Student Name", "Document Title", "Word Count",
         "AI Score", "Plagiarism Score", "Originality Score", "Verdict", "Submitted At"]
    )
    for row in rows:
        writer.writerow([
            row["id"], row["student_name"], row["document_title"],
            row["word_count"], row["ai_score"], row["plagiarism_score"],
            row["originality_score"], row["verdict"], row["submitted_at"],
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="truthscript_history.csv",
    )


@app.route("/analyze", methods=["POST"])
def analyze():
    """Main analysis endpoint.

    Accepts JSON body:
        {
            "text": "<essay text>",
            "student_name": "Jane Doe",       // optional
            "document_title": "My Essay"       // optional
        }
    Or multipart/form-data with 'file' field and optional 'student_name' / 'document_title'.
    """
    student_name = ""
    document_title = ""
    text = ""

    # ── Parse input ────────────────────────────────────────────────────────────
    if request.content_type and "multipart/form-data" in request.content_type:
        student_name = request.form.get("student_name", "").strip()
        document_title = request.form.get("document_title", "").strip()
        uploaded_file = request.files.get("file")
        if uploaded_file:
            text = _extract_text_from_file(uploaded_file)
            if text is None:
                return jsonify({"error": "Unsupported file type. Please upload .txt, .pdf, or .docx"}), 400
        else:
            text = request.form.get("text", "").strip()
    else:
        data = request.get_json(force=True, silent=True) or {}
        text = data.get("text", "").strip()
        student_name = data.get("student_name", "").strip()
        document_title = data.get("document_title", "").strip()

    if not text:
        return jsonify({"error": "No text provided"}), 400

    # ── Minimum word count check ────────────────────────────────────────────────
    word_count = len(text.split())
    if word_count < 100:
        return jsonify(
            {"error": f"Text too short ({word_count} words). Please submit at least 100 words."}
        ), 400

    # ── AI detection ──────────────────────────────────────────────────────────
    ai_result = detect_ai_content(text)

    # ── Plagiarism check ──────────────────────────────────────────────────────
    plag_result = check_plagiarism(text)

    # ── Merge sentence data ──────────────────────────────────────────────────
    sentences = _merge_sentence_data(
        ai_result.get("sentences", []),
        plag_result.get("annotated_sentences", []),
        text,
    )

    # ── Scoring ───────────────────────────────────────────────────────────────
    ai_score = ai_result.get("ai_score", 0.0)
    plagiarism_score = plag_result.get("plagiarism_score", 0.0)
    raw_originality = 100.0 - (ai_score + plagiarism_score)
    originality_score = round(max(0.0, min(100.0, raw_originality)), 2)

    verdict = _build_verdict(ai_score, plagiarism_score, originality_score)

    # ── Writing style fingerprint ─────────────────────────────────────────────
    style = _analyse_style(text)

    # ── Persist to database ───────────────────────────────────────────────────
    submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = get_db()
        conn.execute(
            """
            INSERT INTO submissions
                (student_name, document_title, word_count,
                 ai_score, plagiarism_score, originality_score, verdict, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (student_name, document_title, word_count,
             ai_score, plagiarism_score, originality_score, verdict, submitted_at),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass  # Non-fatal – don't fail the whole request

    result = {
        "student_name": student_name,
        "document_title": document_title,
        "word_count": word_count,
        "ai_score": ai_score,
        "plagiarism_score": plagiarism_score,
        "originality_score": originality_score,
        "verdict": verdict,
        "sentences": sentences,
        "style": style,
        "date": submitted_at,
        "errors": {
            "ai_detector": ai_result.get("error"),
            "plagiarism_checker": plag_result.get("error"),
        },
    }

    return jsonify(result)


@app.route("/generate-report", methods=["POST"])
def generate_report():
    """Generate and return a PDF report for the provided analysis JSON."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "No analysis data provided"}), 400

    pdf_bytes = generate_pdf_report(data)
    if pdf_bytes is None:
        return jsonify({"error": "PDF generation unavailable (fpdf2 not installed)"}), 500

    student = re.sub(r"[^a-zA-Z0-9_-]", "_", data.get("student_name", "report"))
    filename = f"TruthScript_{student}_{datetime.now().strftime('%Y%m%d')}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_text_from_file(file_storage) -> str | None:
    """Extract plain text from an uploaded file object."""
    filename = file_storage.filename.lower()

    if filename.endswith(".txt"):
        return file_storage.read().decode("utf-8", errors="replace")

    if filename.endswith(".pdf"):
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(file_storage)
            return "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except Exception:
            return None

    if filename.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(file_storage)
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return None

    return None


def _merge_sentence_data(ai_sentences: list, plag_sentences: list, full_text: str) -> list:
    """Merge AI and plagiarism sentence annotations into a unified list."""
    # Build lookup by text
    plag_map = {s["text"]: s for s in plag_sentences}

    if ai_sentences:
        merged = []
        for s in ai_sentences:
            plag_info = plag_map.get(s["text"], {})
            merged.append(
                {
                    "text": s["text"],
                    "ai_generated": s.get("ai_generated", False),
                    "plagiarised": plag_info.get("plagiarised", False),
                    "score": s.get("score", 0.0),
                    "source_url": plag_info.get("source_url", ""),
                }
            )
        return merged

    # No AI sentence data – fall back to plagiarism sentences
    if plag_sentences:
        return [
            {
                "text": s["text"],
                "ai_generated": False,
                "plagiarised": s.get("plagiarised", False),
                "score": 0.0,
                "source_url": s.get("source_url", ""),
            }
            for s in plag_sentences
        ]

    # Last resort: split text ourselves
    parts = re.split(r"(?<=[.!?])\s+", full_text.strip())
    return [
        {
            "text": p.strip(),
            "ai_generated": False,
            "plagiarised": False,
            "score": 0.0,
            "source_url": "",
        }
        for p in parts
        if p.strip()
    ]


def _build_verdict(ai_score: float, plagiarism_score: float, originality_score: float) -> str:
    if originality_score >= 80:
        return "✅ High Originality – The submission appears to be largely original work."
    if ai_score > 50:
        return "🤖 High AI Content – The submission is likely generated by an AI writing tool."
    if plagiarism_score > 30:
        return "⚠️ High Plagiarism – Significant portions of the submission match online sources."
    if ai_score > 20 or plagiarism_score > 10:
        return "⚠️ Mixed Content – The submission contains some AI-generated or plagiarised sections."
    return "✅ Mostly Original – Minor concerns detected; review flagged sentences for context."


def _analyse_style(text: str) -> dict:
    """Compute basic writing-style fingerprint metrics."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s for s in sentences if s.strip()]
    words = text.split()

    if not sentences:
        return {}

    avg_sentence_length = round(len(words) / len(sentences), 2)

    unique_words = set(w.lower().strip(".,!?;:\"'()[]") for w in words)
    vocabulary_richness = round(len(unique_words) / max(len(words), 1) * 100, 2)

    # Average word length as a proxy for vocabulary complexity
    word_lengths = [len(w.strip(".,!?;:\"'()[]")) for w in words if w.strip(".,!?;:\"'()[]")]
    avg_word_length = round(sum(word_lengths) / max(len(word_lengths), 1), 2)

    # Flesch-Kincaid readability approximation
    syllable_count = sum(_count_syllables(w) for w in words)
    if len(sentences) > 0 and len(words) > 0:
        fk_grade = round(
            0.39 * (len(words) / len(sentences))
            + 11.8 * (syllable_count / len(words))
            - 15.59,
            1,
        )
    else:
        fk_grade = 0

    return {
        "avg_sentence_length": avg_sentence_length,
        "vocabulary_richness": vocabulary_richness,
        "avg_word_length": avg_word_length,
        "readability_grade": fk_grade,
        "total_sentences": len(sentences),
        "unique_words": len(unique_words),
    }


def _count_syllables(word: str) -> int:
    """Very rough English syllable counter."""
    word = word.lower().strip(".,!?;:\"'()[]")
    if not word:
        return 0
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    # Silent e
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
