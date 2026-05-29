"""Flask web application for the translation tool."""

import io
import json
import os
import re as _re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

sys.path.insert(0, str(Path(__file__).parent))
from translator import SUPPORTED_LANGUAGES, Translator
from validator import TranslationValidator

app = Flask(__name__)

_translator: Translator | None = None
_validator: TranslationValidator | None = None


def _get_translator() -> Translator:
    global _translator
    if _translator is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
        _translator = Translator(api_key=api_key)
    return _translator


def _get_validator(with_translator: bool = False) -> TranslationValidator:
    global _validator
    if with_translator:
        return TranslationValidator(_get_translator())
    if _validator is None:
        _validator = TranslationValidator()
    return _validator


# ── File text extraction ──────────────────────────────────────────────────────

def _extract_docx(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    parts = []
    for para in doc.paragraphs:
        t = para.text.strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _extract_pdf(data: bytes) -> str:
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _extract_xlsx_ser(data: bytes) -> list[dict]:
    """Extract SER entries from an Excel file."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets:
        headers = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c) if c is not None else "" for c in row]
                continue
            if all(c is None for c in row):
                continue
            entry = {headers[j]: (row[j] if j < len(row) else None)
                     for j in range(len(headers))}
            rows.append(entry)
    wb.close()
    return rows


def _extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        return data.decode("utf-8", errors="replace")
    if ext == ".docx":
        return _extract_docx(data)
    if ext == ".pdf":
        return _extract_pdf(data)
    return data.decode("utf-8", errors="replace")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", languages=SUPPORTED_LANGUAGES)


@app.route("/api/extract-text", methods=["POST"])
def api_extract_text():
    """Accept a binary file upload and return extracted plain text."""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file required"}), 400
    ext = Path(f.filename).suffix.lower()
    data = f.read()
    try:
        if ext == ".xlsx":
            rows = _extract_xlsx_ser(data)
            text = json.dumps(rows, ensure_ascii=False, indent=2)
        else:
            text = _extract_text(f.filename, data)
        return jsonify({"text": text, "filename": f.filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(force=True)
    text: str = data.get("text", "").strip()
    target_langs: list[str] = data.get("target_langs", ["en"])
    source_lang: str | None = data.get("source_lang") or None
    context: str | None = data.get("context") or None

    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        translator = _get_translator()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    results: dict[str, str] = {}
    errors: dict[str, str] = {}

    def _translate_one(lang: str):
        return lang, translator.translate(text, lang, source_lang, context)

    with ThreadPoolExecutor(max_workers=len(target_langs)) as pool:
        futures = {pool.submit(_translate_one, lang): lang for lang in target_langs}
        for future in as_completed(futures):
            try:
                lang, translated = future.result()
                results[lang] = translated
            except Exception as e:
                errors[futures[future]] = str(e)

    return jsonify({"results": results, "errors": errors})


@app.route("/api/validate", methods=["POST"])
def api_validate():
    data = request.get_json(force=True)
    source_text: str = data.get("source_text", "").strip()
    translated_texts: dict[str, str] = data.get("translated_texts", {})
    check_quality: bool = bool(data.get("check_quality", False))

    if not source_text:
        return jsonify({"error": "source_text is required"}), 400
    if not translated_texts:
        return jsonify({"error": "translated_texts is required"}), 400

    try:
        validator = _get_validator(with_translator=check_quality)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    results: dict[str, dict] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_file = tmp / "source.md"
        src_file.write_text(source_text, encoding="utf-8")

        for lang, translated in translated_texts.items():
            trl_file = tmp / f"source.{lang}.md"
            trl_file.write_text(translated, encoding="utf-8")

            vr = validator.validate_file(
                src_file, lang,
                translated_path=trl_file,
                check_quality=check_quality,
            )

            results[lang] = {
                "complete": vr.is_complete,
                "passed": vr.passed,
                "issues": vr.completeness_issues,
                "quality_score": vr.quality_score,
                "quality_feedback": vr.quality_feedback,
            }

    return jsonify({"results": results})


@app.route("/api/detect", methods=["POST"])
def api_detect():
    data = request.get_json(force=True)
    text: str = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        translator = _get_translator()
        lang = translator.detect_language(text)
        return jsonify({"lang": lang, "name": SUPPORTED_LANGUAGES.get(lang, lang)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/patent-verify", methods=["POST"])
def api_patent_verify():
    data = request.get_json(force=True)
    source_text: str = data.get("source_text", "").strip()
    translation_text: str = data.get("translation_text", "").strip()
    notes_text: str = data.get("notes_text", "").strip()
    drawing_text: str = data.get("drawing_text", "").strip()
    ser_data: str = data.get("ser_data", "").strip()

    if not source_text:
        return jsonify({"error": "원문(일본어) 텍스트가 필요합니다."}), 400
    if not translation_text:
        return jsonify({"error": "번역문(영어) 텍스트가 필요합니다."}), 400

    try:
        translator = _get_translator()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    notes_block = f"\n\n[번역자 메모]\n{notes_text[:2000]}" if notes_text else ""
    drawing_block = f"\n\n[도면 텍스트 (PDF 추출)]\n{drawing_text[:2000]}" if drawing_text else ""
    ser_block = f"\n\n[SER 데이터]\n{ser_data[:2000]}" if ser_data else ""

    drawing_instruction = ""
    if drawing_text:
        drawing_instruction = """
8. 도면 Callout 검증: 명세서의 부호(符号) 번호와 도면 PDF에서 추출된 텍스트의 번호가 일치하는지 확인.
   불일치 항목은 "drawing_mismatches" 배열에 별도 기재."""

    prompt = f"""You are a senior patent translation verifier specializing in Japanese→English PCT applications.

Verify the translation sentence-by-sentence, checking:
1. Strict literal fidelity to Japanese (no fluency smoothing)
2. Patent terminology accuracy and consistency throughout
3. Claims: articles (a/an/the), "comprising"/"wherein"/"configured to" conventions
4. Detection of rephrasing, omissions, additions, paraphrasing
5. Grammar and syntax
6. Translator notes accuracy (if provided)
7. SER entries: verify each reported error is correctly handled in translation{drawing_instruction}

Skip sentences/paragraphs with NO issues. All explanations must be in Korean.

Return ONLY this JSON (no other text):
{{
  "corrections": [
    {{
      "location": "위치 (예: 청구항1, [0017]단락)",
      "original_jp": "원문 일본어",
      "existing_en": "기존 번역",
      "corrected_en": "수정 번역",
      "reason": "수정 이유 (한국어)",
      "severity": "심각|보통|경미"
    }}
  ],
  "source_errors": [
    {{
      "location": "위치",
      "text": "오류 원문",
      "issue": "오류 내용 (한국어)",
      "ser_required": true,
      "ser_note": "SER 기재 내용 (한국어)"
    }}
  ],
  "drawing_mismatches": [
    {{
      "location": "도면/단락",
      "jp_ref": "원문 부호 번호",
      "en_ref": "번역문 부호 번호",
      "drawing_ref": "도면 부호 번호",
      "issue": "불일치 내용 (한국어)"
    }}
  ],
  "ser_verification": [
    {{
      "ser_no": "SER 번호",
      "location": "위치",
      "status": "OK|미반영|추가필요",
      "note": "검토 내용 (한국어)"
    }}
  ],
  "summary": "전체 검증 요약 2-3문장 (한국어)"
}}

[원문 (일본어)]
{source_text[:6000]}

[번역문 (영어)]
{translation_text[:6000]}{notes_block}{drawing_block}{ser_block}"""

    raw = translator._call_api(
        system=[{
            "type": "text",
            "text": (
                "You are a senior patent translation verifier with deep expertise in "
                "Japanese PCT applications and US/EP patent drafting conventions. "
                "Respond only with the requested JSON object."
            ),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        result = json.loads(match.group() if match else raw)
        return jsonify(result)
    except Exception:
        return jsonify({"error": f"응답 파싱 오류: {raw[:300]}"}), 500


@app.route("/api/patent-report", methods=["POST"])
def api_patent_report():
    """Generate a DOCX verification report from patent-verify results."""
    data = request.get_json(force=True)
    corrections = data.get("corrections", [])
    source_errors = data.get("source_errors", [])
    drawing_mismatches = data.get("drawing_mismatches", [])
    ser_verification = data.get("ser_verification", [])
    summary = data.get("summary", "")
    filenames = data.get("filenames", {})

    try:
        import docx
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor
    except ImportError:
        return jsonify({"error": "python-docx not installed"}), 500

    doc = docx.Document()

    # Title
    title = doc.add_heading("특허 번역 검증 보고서", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # File info
    if filenames:
        doc.add_paragraph(f"원문: {filenames.get('source', '-')}")
        doc.add_paragraph(f"번역문: {filenames.get('translation', '-')}")
        if filenames.get('notes'):
            doc.add_paragraph(f"번역자 메모: {filenames['notes']}")
        if filenames.get('drawing'):
            doc.add_paragraph(f"도면: {filenames['drawing']}")
        if filenames.get('ser'):
            doc.add_paragraph(f"SER: {filenames['ser']}")

    # Summary
    doc.add_heading("검증 요약", 1)
    doc.add_paragraph(summary or "—")

    SEV_KO = {"심각": "Critical", "보통": "Major", "경미": "Minor"}

    def _add_table_header(table, headers, bg="1a73e8"):
        row = table.rows[0]
        for i, h in enumerate(headers):
            cell = row.cells[i]
            cell.text = h
            run = cell.paragraphs[0].runs[0]
            run.bold = True
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            tc_pr = cell._tc.get_or_add_tcPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), bg)
            tc_pr.append(shd)

    # Corrections
    doc.add_heading(f"수정 제안 ({len(corrections)}건)", 1)
    if corrections:
        tbl = doc.add_table(rows=1, cols=6)
        tbl.style = "Table Grid"
        _add_table_header(tbl, ["위치", "원문(JP)", "기존 번역", "수정 번역", "수정 이유", "심각도"])
        for c in corrections:
            r = tbl.add_row().cells
            r[0].text = c.get("location", "")
            r[1].text = c.get("original_jp", "")
            r[2].text = c.get("existing_en", "")
            r[3].text = c.get("corrected_en", "")
            r[4].text = c.get("reason", "")
            sev = c.get("severity", "경미")
            r[5].text = sev
            color = {"심각": RGBColor(0xC5, 0x22, 0x1F),
                     "보통": RGBColor(0xB0, 0x60, 0x00),
                     "경미": RGBColor(0x1E, 0x7E, 0x34)}.get(sev)
            if color:
                for para in r[5].paragraphs:
                    for run in para.runs:
                        run.font.color.rgb = color
    else:
        doc.add_paragraph("수정 제안 없음")

    # Source errors
    doc.add_heading(f"원문 오류 / SER ({len(source_errors)}건)", 1)
    if source_errors:
        tbl = doc.add_table(rows=1, cols=5)
        tbl.style = "Table Grid"
        _add_table_header(tbl, ["위치", "오류 원문", "오류 내용", "SER 필요", "SER 기재 내용"], "ea4335")
        for e in source_errors:
            r = tbl.add_row().cells
            r[0].text = e.get("location", "")
            r[1].text = e.get("text", "")
            r[2].text = e.get("issue", "")
            r[3].text = "필요" if e.get("ser_required") else "참고"
            r[4].text = e.get("ser_note", "")
    else:
        doc.add_paragraph("원문 오류 없음")

    # Drawing mismatches
    if drawing_mismatches:
        doc.add_heading(f"도면 Callout 불일치 ({len(drawing_mismatches)}건)", 1)
        tbl = doc.add_table(rows=1, cols=5)
        tbl.style = "Table Grid"
        _add_table_header(tbl, ["위치", "JP 부호", "EN 부호", "도면 부호", "내용"], "f9ab00")
        for m in drawing_mismatches:
            r = tbl.add_row().cells
            r[0].text = m.get("location", "")
            r[1].text = m.get("jp_ref", "")
            r[2].text = m.get("en_ref", "")
            r[3].text = m.get("drawing_ref", "")
            r[4].text = m.get("issue", "")

    # SER verification
    if ser_verification:
        doc.add_heading(f"SER 검증 ({len(ser_verification)}건)", 1)
        tbl = doc.add_table(rows=1, cols=4)
        tbl.style = "Table Grid"
        _add_table_header(tbl, ["SER No.", "위치", "상태", "검토 내용"], "34a853")
        for s in ser_verification:
            r = tbl.add_row().cells
            r[0].text = str(s.get("ser_no", ""))
            r[1].text = s.get("location", "")
            r[2].text = s.get("status", "")
            r[3].text = s.get("note", "")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name="번역검증보고서.docx",
    )


@app.route("/api/langs")
def api_langs():
    return jsonify(SUPPORTED_LANGUAGES)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
