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
from translator import SUPPORTED_LANGUAGES, Translator, _validate_lang
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

def _detect_format(data: bytes) -> str:
    """Detect actual file format from magic bytes."""
    if data[:4] == b'%PDF':
        return 'pdf'
    if data[:4] in (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'):
        # ZIP-based: OOXML family — peek at [Content_Types].xml to distinguish
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            if any('slide' in n for n in names):
                return 'pptx'
            if any('word/' in n for n in names):
                return 'docx'
            if any('xl/' in n for n in names):
                return 'xlsx'
        except Exception:
            pass
        return 'zip'
    return 'unknown'


def _extract_docx(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for tbl in doc.tables:
        for row in tbl.rows:
            row_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
            if row_text:
                parts.append(row_text)
    return "\n".join(parts)


def _extract_pptx(data: bytes) -> str:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        slide_parts = [f"[Slide {i}]"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = para.text.strip()
                    if t:
                        slide_parts.append(t)
        if len(slide_parts) > 1:
            parts.extend(slide_parts)
    return "\n".join(parts)


def _extract_pdf(data: bytes) -> str:
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    pages = [page.get_text() for page in doc]
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
    """Extract plain text, using magic-byte detection to handle misnamed files."""
    ext = Path(filename).suffix.lower()

    # Always trust magic bytes over extension
    fmt = _detect_format(data)
    if fmt == 'pdf':
        return _extract_pdf(data)
    if fmt == 'pptx':
        return _extract_pptx(data)
    if fmt == 'docx':
        return _extract_docx(data)
    if fmt == 'xlsx':
        rows = _extract_xlsx_ser(data)
        return json.dumps(rows, ensure_ascii=False, indent=2)

    # Fall back to extension
    if ext in (".txt", ".md"):
        return data.decode("utf-8", errors="replace")
    if ext == ".docx":
        return _extract_docx(data)
    if ext == ".pptx":
        return _extract_pptx(data)
    if ext == ".pdf":
        return _extract_pdf(data)
    if ext in (".xlsx", ".xls"):
        rows = _extract_xlsx_ser(data)
        return json.dumps(rows, ensure_ascii=False, indent=2)
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
    instruction_text: str = data.get("instruction_text", "").strip()
    notes_text: str = data.get("notes_text", "").strip()
    drawing_src_text: str = data.get("drawing_src_text", "").strip()
    drawing_trl_text: str = data.get("drawing_trl_text", "").strip()
    ser_data: str = data.get("ser_data", "").strip()

    if not source_text:
        return jsonify({"error": "원문(일본어) 텍스트가 필요합니다."}), 400
    if not translation_text:
        return jsonify({"error": "번역문(영어) 텍스트가 필요합니다."}), 400

    try:
        translator = _get_translator()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    instruction_block = f"\n\n[번역지시서]\n{instruction_text[:3000]}" if instruction_text else ""
    notes_block       = f"\n\n[번역자 메모]\n{notes_text[:2000]}"       if notes_text       else ""
    drawing_src_block = f"\n\n[原文 図面テキスト (JP Drawing)]\n{drawing_src_text[:2000]}" if drawing_src_text else ""
    drawing_trl_block = f"\n\n[訳文 図面テキスト (EN Drawing)]\n{drawing_trl_text[:2000]}" if drawing_trl_text else ""
    ser_block         = f"\n\n[SER 데이터]\n{ser_data[:2000]}"           if ser_data         else ""
    instruction_instr = """
0. Translation instructions (번역지시서): strictly apply all terminology rules, style
   requirements, and client-specific conventions specified in the 번역지시서.""" if instruction_text else ""
    has_drawing = drawing_src_text or drawing_trl_text
    drawing_instr = """
8. Drawing callout check: cross-reference reference numerals between JP spec, EN translation,
   JP drawing (原文 図面), and EN drawing (訳文 図面). Verify that:
   a) All JP reference numerals appear correctly in the EN translation.
   b) JP drawing callouts match the JP spec numerals.
   c) EN drawing callouts match the EN translation numerals.
   d) JP and EN drawings use consistent numbering.
   Report every mismatch in "drawing_mismatches".""" if has_drawing else ""

    prompt = f"""You are a senior patent translation verifier (Japanese→English PCT).

Verify sentence-by-sentence, checking:{instruction_instr}
1. Strict literal fidelity — no fluency smoothing
2. Patent terminology accuracy and consistency
3. Claims conventions: a/an/the articles, "comprising"/"wherein"/"configured to"
4. Rephrasing, omissions, additions, paraphrasing
5. Grammar / syntax
6. Translator notes (if provided)
7. SER entries: confirm each is correctly handled{drawing_instr}

IMPORTANT OUTPUT FORMAT — return ONLY this JSON, no other text:
{{
  "issues": [
    {{
      "no": <integer segment number from the source, or sequential if unavailable>,
      "original_jp": "<exact source Japanese sentence>",
      "existing_en": "<exact current English translation>",
      "area": "<明細書|請求項|要約書|図面>",
      "issue": "<comprehensive issue description in Korean — include suggested correction inline>",
      "corrected_en": "<corrected English translation, or empty string if no change needed>",
      "severity": "<심각|보통|경미>"
    }}
  ],
  "source_errors": [
    {{
      "no": <integer>,
      "original_jp": "<source text with error>",
      "area": "<area>",
      "issue": "<error description in Korean>",
      "ser_required": <true|false>,
      "ser_note": "<SER entry text in Korean, or empty string>"
    }}
  ],
  "drawing_mismatches": [
    {{
      "location": "<figure/paragraph reference e.g. FIG.1, 【0023】>",
      "jp_ref": "<reference numeral in JP spec>",
      "en_ref": "<reference numeral in EN translation>",
      "jp_drawing_ref": "<reference numeral in JP drawing, or N/A>",
      "en_drawing_ref": "<reference numeral in EN drawing, or N/A>",
      "issue": "<mismatch description in Korean>"
    }}
  ],
  "ser_verification": [
    {{
      "ser_no": "<SER item number>",
      "location": "<location>",
      "status": "<OK|미반영|추가필요>",
      "note": "<review note in Korean>"
    }}
  ],
  "summary": "<2-3 sentence overall summary in Korean>"
}}

Omit sentences/paragraphs with no issues.

[原文 (日本語)]
{source_text[:6000]}

[訳文 (English)]
{translation_text[:6000]}{instruction_block}{notes_block}{drawing_src_block}{drawing_trl_block}{ser_block}"""

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
    """Generate reports (DOCX + XLSX) from patent-verify results."""
    data = request.get_json(force=True)
    fmt = data.get("format", "xlsx")   # "xlsx" or "docx"
    issues = data.get("issues", [])
    source_errors = data.get("source_errors", [])
    drawing_mismatches = data.get("drawing_mismatches", [])
    ser_verification = data.get("ser_verification", [])
    summary = data.get("summary", "")
    filenames = data.get("filenames", {})

    if fmt == "xlsx":
        return _make_xlsx_report(issues, source_errors, drawing_mismatches, ser_verification, summary, filenames)
    return _make_docx_report(issues, source_errors, drawing_mismatches, ser_verification, summary, filenames)


def _make_xlsx_report(issues, source_errors, drawing_mismatches, ser_verification, summary, filenames):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    # ── 検証結果 sheet ──
    ws = wb.active
    ws.title = "検証結果"

    HDR_FILL   = PatternFill("solid", fgColor="1A73E8")
    HDR_FONT   = Font(bold=True, color="FFFFFF", size=10)
    THIN       = Side(style="thin", color="DADCE0")
    BORDER     = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    WRAP       = Alignment(wrap_text=True, vertical="top")
    SEV_FILLS  = {
        "심각": PatternFill("solid", fgColor="FCE8E6"),
        "보통": PatternFill("solid", fgColor="FEF7E0"),
        "경미": PatternFill("solid", fgColor="E6F4EA"),
    }

    headers = ["No", "原文", "訳文", "エリア", "指摘事項", "修正訳文", "심각도", "確認済"]
    col_widths = [6, 40, 40, 10, 60, 40, 8, 8]

    for c, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(1, c, h)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = WRAP
        cell.border = BORDER
        ws.column_dimensions[get_column_letter(c)].width = w

    ws.row_dimensions[1].height = 20

    for i, item in enumerate(issues, 2):
        sev = item.get("severity", "경미")
        vals = [
            item.get("no", i - 1),
            item.get("original_jp", ""),
            item.get("existing_en", ""),
            item.get("area", ""),
            item.get("issue", ""),
            item.get("corrected_en", ""),
            sev,
            "",
        ]
        fill = SEV_FILLS.get(sev)
        for c, v in enumerate(vals, 1):
            cell = ws.cell(i, c, v)
            cell.alignment = WRAP
            cell.border = BORDER
            if fill and c in (1, 4, 7, 8):
                cell.fill = fill

    # ── 原文エラー sheet ──
    if source_errors:
        ws2 = wb.create_sheet("原文エラー")
        hdrs2 = ["No", "原文", "エリア", "エラー内容", "SER必要", "SER記載"]
        widths2 = [6, 40, 10, 60, 8, 50]
        for c, (h, w) in enumerate(zip(hdrs2, widths2), 1):
            cell = ws2.cell(1, c, h)
            cell.font = HDR_FONT
            cell.fill = PatternFill("solid", fgColor="EA4335")
            cell.alignment = WRAP; cell.border = BORDER
            ws2.column_dimensions[get_column_letter(c)].width = w
        for i, e in enumerate(source_errors, 2):
            for c, v in enumerate([
                e.get("no", i-1), e.get("original_jp",""), e.get("area",""),
                e.get("issue",""), "✓" if e.get("ser_required") else "", e.get("ser_note","")
            ], 1):
                cell = ws2.cell(i, c, v); cell.alignment = WRAP; cell.border = BORDER

    # ── SER検証 sheet ──
    if ser_verification:
        ws3 = wb.create_sheet("SER検証")
        hdrs3 = ["SER No.", "位置", "ステータス", "検討内容"]
        widths3 = [10, 20, 12, 70]
        for c, (h, w) in enumerate(zip(hdrs3, widths3), 1):
            cell = ws3.cell(1, c, h)
            cell.font = HDR_FONT
            cell.fill = PatternFill("solid", fgColor="34A853")
            cell.alignment = WRAP; cell.border = BORDER
            ws3.column_dimensions[get_column_letter(c)].width = w
        for i, s in enumerate(ser_verification, 2):
            for c, v in enumerate([s.get("ser_no",""), s.get("location",""), s.get("status",""), s.get("note","")], 1):
                cell = ws3.cell(i, c, v); cell.alignment = WRAP; cell.border = BORDER

    # ── 図面不一致 sheet ──
    if drawing_mismatches:
        ws4 = wb.create_sheet("図面不一致")
        hdrs4 = ["位置", "JP本文符号", "EN本文符号", "JP図面符号", "EN図面符号", "内容"]
        widths4 = [15, 12, 12, 12, 12, 55]
        for c, (h, w) in enumerate(zip(hdrs4, widths4), 1):
            cell = ws4.cell(1, c, h)
            cell.font = HDR_FONT
            cell.fill = PatternFill("solid", fgColor="F9AB00")
            cell.alignment = WRAP; cell.border = BORDER
            ws4.column_dimensions[get_column_letter(c)].width = w
        for i, m in enumerate(drawing_mismatches, 2):
            for c, v in enumerate([
                m.get("location",""), m.get("jp_ref",""), m.get("en_ref",""),
                m.get("jp_drawing_ref",""), m.get("en_drawing_ref",""), m.get("issue","")
            ], 1):
                cell = ws4.cell(i, c, v); cell.alignment = WRAP; cell.border = BORDER

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return send_file(buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name="번역검증보고서.xlsx")


def _make_docx_report(issues, source_errors, drawing_mismatches, ser_verification, summary, filenames):
    import docx
    from docx.shared import RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = docx.Document()
    doc.add_heading("特許翻訳検証報告書 / 특허 번역 검증 보고서", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    if filenames:
        for k, v in filenames.items():
            if v: doc.add_paragraph(f"{k}: {v}")
    doc.add_heading("検証要約 / 검증 요약", 1)
    doc.add_paragraph(summary or "—")

    def _hdr_cell(cell, text, rgb_hex):
        cell.text = text
        run = cell.paragraphs[0].runs[0]
        run.bold = True; run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        from docx.oxml.ns import qn; from docx.oxml import OxmlElement
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"),"clear"); shd.set(qn("w:color"),"auto"); shd.set(qn("w:fill"), rgb_hex)
        cell._tc.get_or_add_tcPr().append(shd)

    doc.add_heading(f"指摘事項一覧 / 지적사항 ({len(issues)}건)", 1)
    if issues:
        tbl = doc.add_table(rows=1, cols=7); tbl.style = "Table Grid"
        for i, h in enumerate(["No","原文","訳文","エリア","指摘事項","修正訳文","심각도"]):
            _hdr_cell(tbl.rows[0].cells[i], h, "1A73E8")
        for item in issues:
            r = tbl.add_row().cells
            r[0].text = str(item.get("no",""))
            r[1].text = item.get("original_jp","")
            r[2].text = item.get("existing_en","")
            r[3].text = item.get("area","")
            r[4].text = item.get("issue","")
            r[5].text = item.get("corrected_en","")
            r[6].text = item.get("severity","")
    else:
        doc.add_paragraph("지적사항 없음")

    doc.add_heading(f"原文エラー / 원문 오류 ({len(source_errors)}건)", 1)
    if source_errors:
        tbl = doc.add_table(rows=1, cols=5); tbl.style = "Table Grid"
        for i, h in enumerate(["No","原文","エリア","エラー内容","SER"]):
            _hdr_cell(tbl.rows[0].cells[i], h, "EA4335")
        for e in source_errors:
            r = tbl.add_row().cells
            r[0].text = str(e.get("no","")); r[1].text = e.get("original_jp","")
            r[2].text = e.get("area",""); r[3].text = e.get("issue","")
            r[4].text = "필요" if e.get("ser_required") else "참고"
    else:
        doc.add_paragraph("원문 오류 없음")

    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return send_file(buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True, download_name="번역검증보고서.docx")


@app.route("/api/patent-corrected-docx", methods=["POST"])
def api_patent_corrected_docx():
    """Return a corrected translation DOCX with OOXML track changes for 심각 issues."""
    data = request.get_json(force=True)
    translation_text: str = data.get("translation_text", "")
    issues: list = data.get("issues", [])
    corrections = [
        i for i in issues
        if i.get("severity") == "심각" and i.get("corrected_en", "").strip()
    ]
    return _make_corrected_translation_docx(translation_text, corrections)


def _make_corrected_translation_docx(translation_text: str, corrections: list[dict]):
    import difflib
    import datetime
    import docx
    from docx.shared import RGBColor, Pt
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    AUTHOR = "특허검증시스템"
    _rid = [1]

    def _next():
        v = _rid[0]; _rid[0] += 2; return v, v + 1

    def _sp(el):
        el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    def _run(text):
        r = OxmlElement("w:r")
        t = OxmlElement("w:t"); _sp(t); t.text = text; r.append(t); return r

    def _del_run(text):
        r = OxmlElement("w:r")
        t = OxmlElement("w:delText"); _sp(t); t.text = text; r.append(t); return r

    def _apply_track(para, before, old_text, new_text, after):
        p_el = para._p
        pPr = p_el.find(qn("w:pPr"))
        p_el.clear()
        if pPr is not None:
            p_el.append(pPr)
        did, iid = _next()
        if before:
            p_el.append(_run(before))
        del_el = OxmlElement("w:del")
        del_el.set(qn("w:id"), str(did))
        del_el.set(qn("w:author"), AUTHOR)
        del_el.set(qn("w:date"), now)
        del_el.append(_del_run(old_text))
        p_el.append(del_el)
        ins_el = OxmlElement("w:ins")
        ins_el.set(qn("w:id"), str(iid))
        ins_el.set(qn("w:author"), AUTHOR)
        ins_el.set(qn("w:date"), now)
        ins_el.append(_run(new_text))
        p_el.append(ins_el)
        if after:
            p_el.append(_run(after))

    paragraphs = [p.strip() for p in translation_text.split("\n") if p.strip()]

    # Match each correction to its best paragraph
    correction_map: dict[int, dict] = {}
    used_ids: set[int] = set()
    for corr in corrections:
        existing = corr.get("existing_en", "").strip()
        if not existing:
            continue
        probe = existing.lower()[:200]
        best_idx, best_ratio = -1, 0.0
        for i, para in enumerate(paragraphs):
            if i in correction_map:
                continue
            ratio = difflib.SequenceMatcher(None, probe, para.lower()[:200]).ratio()
            if ratio > best_ratio:
                best_ratio, best_idx = ratio, i
        if best_ratio >= 0.4 and best_idx >= 0:
            correction_map[best_idx] = corr
            used_ids.add(id(corr))

    doc = docx.Document()
    doc.styles["Normal"].font.size = Pt(10.5)

    doc.add_heading("수정본 번역문 / Corrected Translation", 0)
    matched = len(correction_map)
    note = doc.add_paragraph(
        f"심각(Critical) 지적사항 {len(corrections)}건 중 {matched}건 자동 반영.\n"
        "🔴 취소선: 기존 번역  |  🔵 밑줄: 수정 번역\n"
        "Word의 [검토] → [변경 내용 표시]에서 수정이력을 확인·승인할 수 있습니다."
    )
    note.runs[0].italic = True
    doc.add_paragraph()

    for i, para_text in enumerate(paragraphs):
        p = doc.add_paragraph()
        corr = correction_map.get(i)
        if corr:
            existing = corr.get("existing_en", "").strip()
            corrected = corr.get("corrected_en", "").strip()
            probe = existing.lower()[:80]
            pos = para_text.lower().find(probe)
            if pos >= 0:
                end = min(pos + len(existing), len(para_text))
                _apply_track(p, para_text[:pos], para_text[pos:end], corrected, para_text[end:])
            else:
                _apply_track(p, "", para_text, corrected, "")
        else:
            p.add_run(para_text)

    # Unmatched corrections appendix
    unmatched = [c for c in corrections if id(c) not in used_ids]
    if unmatched:
        doc.add_paragraph()
        doc.add_heading(f"자동 매칭 불가 ({len(unmatched)}건) — 수동 적용 필요", 1)
        doc.add_paragraph("아래 수정사항은 본문에서 위치를 자동으로 찾지 못했습니다.")
        for c in unmatched:
            p1 = doc.add_paragraph(style="List Bullet")
            p1.add_run("기존: ").bold = True
            p1.add_run(c.get("existing_en", ""))
            p2 = doc.add_paragraph(style="List Bullet")
            p2.add_run("수정: ").bold = True
            r = p2.add_run(c.get("corrected_en", ""))
            r.font.color.rgb = RGBColor(0x00, 0x00, 0xCC)
            r.bold = True

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return send_file(buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name="수정본_번역문.docx")


@app.route("/api/translate-drawing", methods=["POST"])
def api_translate_drawing():
    """Parse drawing reference numerals + translate captions to target languages."""
    data = request.get_json(force=True)
    drawing_texts: list = data.get("drawing_texts", [])   # [{name, text}]
    target_langs: list  = data.get("target_langs", ["en"])
    source_lang: str    = data.get("source_lang", "ja")

    if not drawing_texts:
        return jsonify({"error": "도면 텍스트가 필요합니다"}), 400

    try:
        translator = _get_translator()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    validated_langs = [_validate_lang(l) for l in target_langs if l]

    # ── Step 1: parse drawing text → (ref, jp) pairs ──────────────────────────
    combined = "\n\n".join(
        f"[{d['name']}]\n{d['text']}" if len(drawing_texts) > 1 else d["text"]
        for d in drawing_texts
    )

    parse_prompt = (
        "Analyze the patent drawing text below. Extract all reference numeral + Japanese label pairs.\n\n"
        "Reference numerals (図面符号) are: integers (1, 10, 100), alphanumeric codes (1a, 1b, 2A, S1), "
        "or uppercase letters (A, B). They typically appear beside or before Japanese descriptive text.\n\n"
        "Output ONLY lines in this exact format (tab-separated, no header, no blank lines):\n"
        "<numeral>\\t<Japanese text>\n\n"
        "Rules:\n"
        "- Omit any numeral with no clear Japanese text\n"
        "- Keep numerals exactly as they appear\n"
        "- Deduplicate: emit each numeral only once (first occurrence)\n\n"
        f"Drawing text:\n{combined[:5000]}"
    )

    raw_pairs = translator._call_api(
        system=[{"type": "text",
                 "text": "You extract reference numeral / Japanese label pairs from patent drawings. "
                         "Output tab-separated pairs only, nothing else.",
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": parse_prompt}],
    )

    pairs: list[dict] = []
    seen: set[str] = set()
    for line in raw_pairs.strip().splitlines():
        if "\t" in line:
            ref, jp = line.split("\t", 1)
            ref, jp = ref.strip(), jp.strip()
            if ref and jp and ref not in seen:
                pairs.append({"ref": ref, "jp": jp})
                seen.add(ref)

    if not pairs:
        return jsonify({"items": [], "target_langs": validated_langs,
                        "message": "도면에서 참조번호+텍스트 쌍을 찾지 못했습니다."})

    # ── Step 2: translate each JP label to every target lang (parallel) ────────
    items: list[dict] = [{"ref": p["ref"], "jp": p["jp"], "translations": {}} for p in pairs]

    def _translate_one(pair_idx: int, lang: str):
        text = translator.translate(pairs[pair_idx]["jp"], lang, source_lang)
        return pair_idx, lang, text

    tasks = [(i, lang) for i in range(len(pairs)) for lang in validated_langs]
    with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as pool:
        futures = {pool.submit(_translate_one, i, lang): (i, lang) for i, lang in tasks}
        for fut in as_completed(futures):
            try:
                i, lang, text = fut.result()
                items[i]["translations"][lang] = text
            except Exception as exc:
                i, lang = futures[fut]
                items[i]["translations"][lang] = f"[오류: {exc}]"

    return jsonify({"items": items, "target_langs": validated_langs})


@app.route("/api/drawing-translation-xlsx", methods=["POST"])
def api_drawing_translation_xlsx():
    """Generate xlsx from drawing translation items."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    data = request.get_json(force=True)
    items: list       = data.get("items", [])
    target_langs: list = data.get("target_langs", ["en"])

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "도면번역"

    HDR_FILL = PatternFill("solid", fgColor="1A73E8")
    HDR_FONT = Font(bold=True, color="FFFFFF", size=10)
    THIN     = Side(style="thin", color="DADCE0")
    BORDER   = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    WRAP     = Alignment(wrap_text=True, vertical="top")

    lang_names = {k: v for k, v in SUPPORTED_LANGUAGES.items()}
    headers = ["도면 부호", "日本語 原文"] + [lang_names.get(l, l.upper()) for l in target_langs]
    widths  = [12, 40] + [40] * len(target_langs)

    for c, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(1, c, h)
        cell.font = HDR_FONT; cell.fill = HDR_FILL
        cell.alignment = WRAP; cell.border = BORDER
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[1].height = 20

    for r, item in enumerate(items, 2):
        vals = ([item.get("ref", ""), item.get("jp", "")]
                + [item.get("translations", {}).get(l, "") for l in target_langs])
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.alignment = WRAP; cell.border = BORDER

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return send_file(buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name="도면번역.xlsx")


@app.route("/api/patent-verify-batch", methods=["POST"])
def api_patent_verify_batch():
    """Submit patent verification as a Batch API job (50% cheaper, async)."""
    data = request.get_json(force=True)
    source_text: str = data.get("source_text", "").strip()
    translation_text: str = data.get("translation_text", "").strip()
    instruction_text: str = data.get("instruction_text", "").strip()
    notes_text: str = data.get("notes_text", "").strip()
    drawing_src_text: str = data.get("drawing_src_text", "").strip()
    drawing_trl_text: str = data.get("drawing_trl_text", "").strip()
    ser_data: str = data.get("ser_data", "").strip()

    if not source_text:
        return jsonify({"error": "원문(일본어) 텍스트가 필요합니다."}), 400
    if not translation_text:
        return jsonify({"error": "번역문(영어) 텍스트가 필요합니다."}), 400

    try:
        translator = _get_translator()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    instruction_block = f"\n\n[번역지시서]\n{instruction_text[:3000]}" if instruction_text else ""
    notes_block       = f"\n\n[번역자 메모]\n{notes_text[:2000]}"       if notes_text       else ""
    drawing_src_block = f"\n\n[原文 図面テキスト (JP Drawing)]\n{drawing_src_text[:2000]}" if drawing_src_text else ""
    drawing_trl_block = f"\n\n[訳文 図面テキスト (EN Drawing)]\n{drawing_trl_text[:2000]}" if drawing_trl_text else ""
    ser_block         = f"\n\n[SER 데이터]\n{ser_data[:2000]}"           if ser_data         else ""
    instruction_instr = """
0. Translation instructions (번역지시서): strictly apply all terminology rules, style
   requirements, and client-specific conventions specified in the 번역지시서.""" if instruction_text else ""
    has_drawing = drawing_src_text or drawing_trl_text
    drawing_instr = """
8. Drawing callout check: cross-reference reference numerals between JP spec, EN translation,
   JP drawing (原文 図面), and EN drawing (訳文 図面). Verify that:
   a) All JP reference numerals appear correctly in the EN translation.
   b) JP drawing callouts match the JP spec numerals.
   c) EN drawing callouts match the EN translation numerals.
   d) JP and EN drawings use consistent numbering.
   Report every mismatch in "drawing_mismatches".""" if has_drawing else ""

    prompt = f"""You are a senior patent translation verifier (Japanese→English PCT).

Verify sentence-by-sentence, checking:{instruction_instr}
1. Strict literal fidelity — no fluency smoothing
2. Patent terminology accuracy and consistency
3. Claims conventions: a/an/the articles, "comprising"/"wherein"/"configured to"
4. Rephrasing, omissions, additions, paraphrasing
5. Grammar / syntax
6. Translator notes (if provided)
7. SER entries: confirm each is correctly handled{drawing_instr}

IMPORTANT OUTPUT FORMAT — return ONLY this JSON, no other text:
{{
  "issues": [
    {{
      "no": <integer segment number from the source, or sequential if unavailable>,
      "original_jp": "<exact source Japanese sentence>",
      "existing_en": "<exact current English translation>",
      "area": "<明細書|請求項|要約書|図面>",
      "issue": "<comprehensive issue description in Korean — include suggested correction inline>",
      "corrected_en": "<corrected English translation, or empty string if no change needed>",
      "severity": "<심각|보통|경미>"
    }}
  ],
  "source_errors": [
    {{
      "no": <integer>,
      "original_jp": "<source text with error>",
      "area": "<area>",
      "issue": "<error description in Korean>",
      "ser_required": <true|false>,
      "ser_note": "<SER entry text in Korean, or empty string>"
    }}
  ],
  "drawing_mismatches": [
    {{
      "location": "<figure/paragraph reference e.g. FIG.1, 【0023】>",
      "jp_ref": "<reference numeral in JP spec>",
      "en_ref": "<reference numeral in EN translation>",
      "jp_drawing_ref": "<reference numeral in JP drawing, or N/A>",
      "en_drawing_ref": "<reference numeral in EN drawing, or N/A>",
      "issue": "<mismatch description in Korean>"
    }}
  ],
  "ser_verification": [
    {{
      "ser_no": "<SER item number>",
      "location": "<location>",
      "status": "<OK|미반영|추가필요>",
      "note": "<review note in Korean>"
    }}
  ],
  "summary": "<2-3 sentence overall summary in Korean>"
}}

Omit sentences/paragraphs with no issues.

[原文 (日本語)]
{source_text[:6000]}

[訳文 (English)]
{translation_text[:6000]}{instruction_block}{notes_block}{drawing_src_block}{drawing_trl_block}{ser_block}"""

    try:
        batch = translator.client.messages.batches.create(
            requests=[{
                "custom_id": "patent-verify",
                "params": {
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 8096,
                    "system": [{
                        "type": "text",
                        "text": (
                            "You are a senior patent translation verifier with deep expertise in "
                            "Japanese PCT applications and US/EP patent drafting conventions. "
                            "Respond only with the requested JSON object."
                        ),
                        "cache_control": {"type": "ephemeral"},
                    }],
                    "messages": [{"role": "user", "content": prompt}],
                },
            }]
        )
    except Exception as e:
        return jsonify({"error": f"배치 제출 실패: {e}"}), 500

    return jsonify({"batch_id": batch.id, "status": batch.processing_status})


@app.route("/api/batch-status/<batch_id>", methods=["GET"])
def api_batch_status(batch_id):
    """Poll Batch API status. Returns parsed result when processing_status == 'ended'."""
    try:
        translator = _get_translator()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    try:
        batch = translator.client.messages.batches.retrieve(batch_id)
    except Exception as e:
        return jsonify({"error": f"배치 조회 실패: {e}"}), 500

    if batch.processing_status != "ended":
        counts = batch.request_counts
        return jsonify({
            "batch_id": batch_id,
            "status": batch.processing_status,
            "request_counts": {
                "processing": getattr(counts, "processing", 0),
                "succeeded": getattr(counts, "succeeded", 0),
                "errored": getattr(counts, "errored", 0),
            },
        })

    # Batch ended — retrieve results
    try:
        results = list(translator.client.messages.batches.results(batch_id))
    except Exception as e:
        return jsonify({"batch_id": batch_id, "status": "ended", "error": f"결과 조회 실패: {e}"}), 500

    if not results:
        return jsonify({"batch_id": batch_id, "status": "ended", "error": "결과 없음"})

    result = results[0]
    if result.result.type != "succeeded":
        return jsonify({
            "batch_id": batch_id, "status": "ended",
            "error": f"배치 처리 실패: {result.result.type}",
        })

    raw = next((b.text for b in result.result.message.content if hasattr(b, "text")), None)
    if not raw:
        return jsonify({"batch_id": batch_id, "status": "ended", "error": "응답 텍스트 없음"})

    try:
        match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        parsed = json.loads(match.group() if match else raw)
        return jsonify({"batch_id": batch_id, "status": "ended", "result": parsed})
    except Exception:
        return jsonify({
            "batch_id": batch_id, "status": "ended",
            "error": f"응답 파싱 오류: {raw[:300]}",
        })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
