/* ============================================================
   TruthScript – Main JavaScript
   ============================================================ */

'use strict';

// ── Theme ────────────────────────────────────────────────────
const themeToggle = document.getElementById('theme-toggle');
const body        = document.body;

function applyTheme(theme) {
  if (theme === 'light') {
    body.classList.add('light');
  } else {
    body.classList.remove('light');
  }
  localStorage.setItem('ts-theme', theme);
}

// Init from localStorage
applyTheme(localStorage.getItem('ts-theme') || 'dark');

if (themeToggle) {
  themeToggle.addEventListener('click', () => {
    const isDark = !body.classList.contains('light');
    applyTheme(isDark ? 'light' : 'dark');
  });
}

// ── Drag & Drop ──────────────────────────────────────────────
const dropZone   = document.getElementById('drop-zone');
const fileInput  = document.getElementById('file-input');
const textArea   = document.getElementById('text-input');
const charCount  = document.getElementById('char-count');

if (dropZone) {
  dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });
}

if (fileInput) {
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) handleFile(fileInput.files[0]);
  });
}

function handleFile(file) {
  const MAX_SIZE = 5 * 1024 * 1024;
  if (file.size > MAX_SIZE) {
    showAlert('File too large. Maximum size is 5 MB.', 'error');
    return;
  }

  const allowed = ['.txt', '.pdf', '.docx'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!allowed.includes(ext)) {
    showAlert('Unsupported file type. Please upload .txt, .pdf, or .docx', 'error');
    return;
  }

  // For .txt files, read client-side; others are sent to server
  if (ext === '.txt') {
    const reader = new FileReader();
    reader.onload = e => {
      textArea.value = e.target.result;
      updateCharCount();
    };
    reader.readAsText(file);
  } else {
    showAlert(`File "${file.name}" ready for upload. Click Analyze to process.`, 'info');
    // Store for FormData submission
    window._pendingFile = file;
  }

  // Update drop zone label
  const dropText = document.querySelector('.drop-text');
  if (dropText) dropText.textContent = `📄 ${file.name}`;
}

// ── Char / Word Count ────────────────────────────────────────
function updateCharCount() {
  if (!textArea || !charCount) return;
  const words = textArea.value.trim().split(/\s+/).filter(Boolean).length;
  charCount.textContent = `${words} word${words !== 1 ? 's' : ''}`;
  charCount.style.color = words < 100 ? 'var(--ai-red)' : 'var(--text-muted)';
}

if (textArea) {
  textArea.addEventListener('input', updateCharCount);
  updateCharCount();
}

// ── Alert Helper ─────────────────────────────────────────────
function showAlert(message, type = 'error') {
  const el = document.getElementById('alert-box');
  if (!el) return;
  el.textContent = message;
  el.className = `alert alert-${type} show`;
  setTimeout(() => el.classList.remove('show'), 5000);
}

// ── Spinner ──────────────────────────────────────────────────
function setLoading(active, message = 'Analysing your text…') {
  const overlay = document.getElementById('spinner-overlay');
  const text    = document.getElementById('spinner-text');
  if (!overlay) return;
  if (text) text.textContent = message;
  overlay.classList.toggle('active', active);
}

// ── Analyze Form ─────────────────────────────────────────────
const analyzeForm = document.getElementById('analyze-form');

if (analyzeForm) {
  analyzeForm.addEventListener('submit', async e => {
    e.preventDefault();

    const text         = textArea ? textArea.value.trim() : '';
    const studentName  = document.getElementById('student-name')?.value.trim() || '';
    const docTitle     = document.getElementById('doc-title')?.value.trim() || '';

    // Validate
    if (!text && !window._pendingFile) {
      showAlert('Please enter or upload text to analyse.', 'error');
      return;
    }

    const wordCount = text.split(/\s+/).filter(Boolean).length;
    if (wordCount < 100 && !window._pendingFile) {
      showAlert(`Text too short (${wordCount} words). Please submit at least 100 words.`, 'error');
      return;
    }

    setLoading(true, 'Analysing your text…');

    try {
      let response;

      if (window._pendingFile) {
        const formData = new FormData();
        formData.append('file', window._pendingFile);
        formData.append('student_name', studentName);
        formData.append('document_title', docTitle);
        if (text) formData.append('text', text);

        response = await fetch('/analyze', { method: 'POST', body: formData });
      } else {
        response = await fetch('/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, student_name: studentName, document_title: docTitle }),
        });
      }

      const data = await response.json();
      setLoading(false);

      if (!response.ok || data.error) {
        showAlert(data.error || 'An error occurred during analysis.', 'error');
        return;
      }

      // Store result for results page
      sessionStorage.setItem('ts-result', JSON.stringify(data));
      window.location.href = '/results';

    } catch (err) {
      setLoading(false);
      showAlert('Network error. Please check your connection and try again.', 'error');
      console.error(err);
    }
  });
}

// ── Results Page Logic ───────────────────────────────────────
function initResultsPage() {
  const resultRaw = sessionStorage.getItem('ts-result');
  if (!resultRaw) {
    // No data – redirect home
    window.location.href = '/';
    return;
  }

  const data = JSON.parse(resultRaw);
  renderResults(data);
}

function renderResults(data) {
  // Meta
  setText('res-student',  data.student_name  || 'N/A');
  setText('res-date',     data.date          || new Date().toLocaleString());
  setText('res-words',    `${data.word_count || 0} words`);
  setText('res-title',    data.document_title || 'Student Submission');

  // Verdict banner
  const banner = document.getElementById('verdict-banner');
  if (banner) {
    banner.textContent = data.verdict || '';
    banner.className = 'verdict-banner ' + getVerdictClass(data.verdict);
  }

  // Animate scores
  animateScore('orig-score-num',  data.originality_score, 'circle-fill', data.originality_score, '%');
  animateProgressBar('bar-orig',  data.originality_score);
  animateProgressBar('bar-ai',    data.ai_score);
  animateProgressBar('bar-plag',  data.plagiarism_score);
  setText('ai-score-val',   `${(data.ai_score  || 0).toFixed(1)}%`);
  setText('plag-score-val', `${(data.plagiarism_score || 0).toFixed(1)}%`);
  setText('orig-score-val', `${(data.originality_score || 0).toFixed(1)}%`);

  // Highlighted text
  renderHighlightedText(data.sentences || []);

  // Sentence table
  renderSentenceTable(data.sentences || []);

  // Style fingerprint
  renderStyle(data.style || {});

  // API error notices
  renderApiErrors(data.errors || {});

  // Attach download PDF handler
  const pdfBtn = document.getElementById('btn-pdf');
  if (pdfBtn) {
    pdfBtn.addEventListener('click', () => downloadPDF(data));
  }

  // Attach download CSV history handler
  const csvBtn = document.getElementById('btn-csv');
  if (csvBtn) {
    csvBtn.addEventListener('click', () => {
      window.location.href = '/export-csv';
    });
  }
}

// ── Circular Progress Animation ───────────────────────────────
function animateScore(numId, targetValue, circleId, circleValue) {
  const numEl    = document.getElementById(numId);
  const circleEl = document.getElementById(circleId);
  const duration = 1200;
  const start    = performance.now();

  function step(now) {
    const elapsed  = now - start;
    const progress = Math.min(elapsed / duration, 1);
    const eased    = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    const current  = Math.round(eased * targetValue);

    if (numEl) numEl.textContent = current + '%';

    if (circleEl) {
      const circumference = 440;
      const offset = circumference - (eased * circleValue / 100) * circumference;
      circleEl.style.strokeDashoffset = offset;

      // Colour based on score
      if (circleValue >= 70) circleEl.style.stroke = 'var(--orig-green)';
      else if (circleValue >= 40) circleEl.style.stroke = 'var(--plag-yellow)';
      else circleEl.style.stroke = 'var(--ai-red)';
    }

    if (progress < 1) requestAnimationFrame(step);
  }

  requestAnimationFrame(step);
}

function animateProgressBar(barId, targetValue) {
  const el = document.getElementById(barId);
  if (!el) return;
  setTimeout(() => { el.style.width = Math.min(targetValue, 100) + '%'; }, 100);
}

// ── Highlighted Text ──────────────────────────────────────────
function renderHighlightedText(sentences) {
  const container = document.getElementById('highlight-view');
  if (!container) return;

  if (!sentences.length) {
    container.innerHTML = '<span class="text-muted">No sentence data available.</span>';
    return;
  }

  const fragments = sentences.map(s => {
    const safe = escapeHtml(s.text);
    let cls = 'hl-orig';
    let title = 'Original content';
    if (s.ai_generated) {
      cls = 'hl-ai';
      title = `AI Generated (score: ${(s.score || 0).toFixed(0)}%)`;
    } else if (s.plagiarised) {
      cls = 'hl-plag';
      title = s.source_url ? `Plagiarised – source: ${s.source_url}` : 'Plagiarised';
    }
    return `<span class="${cls}" title="${escapeHtml(title)}">${safe}</span> `;
  });

  container.innerHTML = fragments.join('');
}

// ── Sentence Table ────────────────────────────────────────────
function renderSentenceTable(sentences) {
  const tbody = document.getElementById('sentence-tbody');
  if (!tbody) return;

  if (!sentences.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No data</td></tr>';
    return;
  }

  tbody.innerHTML = sentences.map((s, i) => {
    let tag, tagClass;
    if (s.ai_generated) {
      tag = 'AI'; tagClass = 'tag-ai';
    } else if (s.plagiarised) {
      tag = 'Plagiarised'; tagClass = 'tag-plag';
    } else {
      tag = 'Original'; tagClass = 'tag-orig';
    }

    const score = s.score != null ? `${(s.score).toFixed(0)}%` : '-';
    const source = s.source_url
      ? `<a href="${escapeHtml(s.source_url)}" target="_blank" rel="noopener">Source ↗</a>`
      : '-';

    return `<tr>
      <td>${i + 1}</td>
      <td>${escapeHtml(s.text || '')}</td>
      <td><span class="tag ${tagClass}">${tag}</span></td>
      <td>${score}</td>
      <td>${source}</td>
    </tr>`;
  }).join('');
}

// ── Style Fingerprint ─────────────────────────────────────────
function renderStyle(style) {
  setText('style-avg-sent',   style.avg_sentence_length   != null ? style.avg_sentence_length + ' words'  : 'N/A');
  setText('style-vocab',      style.vocabulary_richness   != null ? style.vocabulary_richness  + '%'      : 'N/A');
  setText('style-avg-word',   style.avg_word_length       != null ? style.avg_word_length      + ' chars' : 'N/A');
  setText('style-grade',      style.readability_grade     != null ? 'Grade ' + style.readability_grade    : 'N/A');
  setText('style-sentences',  style.total_sentences       != null ? style.total_sentences                 : 'N/A');
  setText('style-unique',     style.unique_words          != null ? style.unique_words                    : 'N/A');
}

// ── API Errors ────────────────────────────────────────────────
function renderApiErrors(errors) {
  const container = document.getElementById('api-errors');
  if (!container) return;
  const msgs = Object.values(errors).filter(Boolean);
  if (!msgs.length) { container.classList.add('hidden'); return; }
  container.innerHTML = msgs.map(m => `<div>⚠️ ${escapeHtml(m)}</div>`).join('');
  container.classList.remove('hidden');
}

// ── PDF Download ──────────────────────────────────────────────
async function downloadPDF(data) {
  const btn = document.getElementById('btn-pdf');
  if (btn) btn.disabled = true;

  setLoading(true, 'Generating PDF report…');
  try {
    const res = await fetch('/generate-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      const err = await res.json();
      showAlert(err.error || 'PDF generation failed.', 'error');
      return;
    }

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `TruthScript_${(data.student_name || 'report').replace(/\s+/g, '_')}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    showAlert('Failed to download PDF.', 'error');
  } finally {
    setLoading(false);
    if (btn) btn.disabled = false;
  }
}

// ── Tab Switcher ──────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    const panel = document.getElementById('tab-' + target);
    if (panel) panel.classList.add('active');
  });
});

// ── Helpers ───────────────────────────────────────────────────
function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '';
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function getVerdictClass(verdict) {
  if (!verdict) return 'verdict-mixed';
  if (verdict.includes('High Originality'))    return 'verdict-high-orig';
  if (verdict.includes('High AI'))             return 'verdict-high-ai';
  if (verdict.includes('High Plagiarism'))     return 'verdict-high-plag';
  return 'verdict-mixed';
}

// ── Init ──────────────────────────────────────────────────────
if (document.getElementById('results-root')) {
  initResultsPage();
}
