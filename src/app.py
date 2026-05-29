"""Flask web application for the translation tool."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Flask, jsonify, render_template, request

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


@app.route("/")
def index():
    return render_template("index.html", languages=SUPPORTED_LANGUAGES)


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

    import re
    import tempfile

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
    source_text: str = data.get("source_text", "").strip()      # Japanese
    translation_text: str = data.get("translation_text", "").strip()  # English
    notes_text: str = data.get("notes_text", "").strip()         # Translator notes (optional)

    if not source_text:
        return jsonify({"error": "원문(일본어) 텍스트가 필요합니다."}), 400
    if not translation_text:
        return jsonify({"error": "번역문(영어) 텍스트가 필요합니다."}), 400

    try:
        translator = _get_translator()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    notes_block = f"\n\n[번역자 메모]\n{notes_text[:2000]}" if notes_text else ""

    prompt = f"""You are a professional patent translation verifier specializing in PCT applications (Japanese → English).

Verify the following translation sentence-by-sentence, ensuring:
1. Strict literal fidelity to the original Japanese — do NOT smooth for fluency
2. Accurate rendering of technical/legal patent terminology
3. Patent-style conventions: articles (a/an/the) in claims, standard claim language
   ("comprising", "wherein", "configured to", "connected to", etc.)
4. Consistency of terminology throughout the entire document
5. Detection of rephrasing, omissions, additions, or paraphrasing
6. Grammar and syntactic correctness
7. Translator notes (if provided): accuracy, appropriateness, completeness

Skip sentences/paragraphs with NO issues entirely.
Results must be explained in Korean.

Return ONLY a JSON object with this exact structure (no other text):
{{
  "corrections": [
    {{
      "location": "단락·문장 위치 (예: 청구항1, 발명의 상세한 설명 3단락 등)",
      "original_jp": "원문 일본어",
      "existing_en": "기존 영어 번역",
      "corrected_en": "수정 영어 번역",
      "reason": "수정 이유 (한국어)",
      "severity": "심각"
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
  "summary": "전체 검증 요약 2-3문장 (한국어)"
}}

severity 값은 반드시 "심각", "보통", "경미" 중 하나.

[원문 (일본어)]
{source_text[:5000]}

[번역문 (영어)]
{translation_text[:5000]}{notes_block}"""

    import re as _re
    raw = translator._call_api(
        system=[{
            "type": "text",
            "text": (
                "You are a senior patent translation verifier with expertise in "
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


@app.route("/api/langs")
def api_langs():
    return jsonify(SUPPORTED_LANGUAGES)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
