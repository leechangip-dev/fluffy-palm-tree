"""Flask web application for the translation tool."""

import os
import sys
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

    for lang in target_langs:
        try:
            results[lang] = translator.translate(text, lang, source_lang, context)
        except Exception as e:
            errors[lang] = str(e)

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


@app.route("/api/langs")
def api_langs():
    return jsonify(SUPPORTED_LANGUAGES)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
