"""Core translation engine using the Claude API with prompt caching."""

import anthropic
import json
import time
from pathlib import Path
from typing import Optional

SUPPORTED_LANGUAGES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "vi": "Vietnamese",
}

SYSTEM_PROMPT = """You are a professional multilingual translator. Your task is to translate the given content accurately while:
1. Preserving all formatting, markdown syntax, code blocks, and special characters exactly as-is
2. Keeping proper nouns, brand names, and technical terms appropriate to context
3. Maintaining the original tone and style (formal, casual, technical, etc.)
4. Never translating content inside code blocks (``` or `)
5. Returning ONLY the translated text with no explanations or commentary"""


class Translator:
    def __init__(self, api_key: Optional[str] = None):
        self.client = anthropic.Anthropic(api_key=api_key)

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        context: Optional[str] = None,
    ) -> str:
        target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        source_hint = ""
        if source_lang and source_lang in SUPPORTED_LANGUAGES:
            source_hint = f" from {SUPPORTED_LANGUAGES[source_lang]}"

        context_block = f"\n\nAdditional context: {context}" if context else ""

        user_prompt = (
            f"Translate the following text{source_hint} to {target_name}."
            f"{context_block}\n\n"
            f"Text to translate:\n{text}"
        )

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )

        return response.content[0].text

    def translate_file(
        self,
        input_path: Path,
        target_lang: str,
        output_path: Optional[Path] = None,
        source_lang: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Path:
        text = input_path.read_text(encoding="utf-8")

        if input_path.suffix == ".json":
            return self._translate_json(
                input_path, target_lang, output_path, source_lang, context
            )

        translated = self.translate(text, target_lang, source_lang, context)

        if output_path is None:
            stem = input_path.stem
            suffix = input_path.suffix
            output_path = input_path.parent / f"{stem}.{target_lang}{suffix}"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(translated, encoding="utf-8")
        return output_path

    def _translate_json(
        self,
        input_path: Path,
        target_lang: str,
        output_path: Optional[Path],
        source_lang: Optional[str],
        context: Optional[str],
    ) -> Path:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        translated_data = self._translate_json_values(
            data, target_lang, source_lang, context
        )

        if output_path is None:
            stem = input_path.stem
            output_path = input_path.parent / f"{stem}.{target_lang}.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(translated_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def _translate_json_values(self, obj, target_lang, source_lang, context):
        if isinstance(obj, str):
            return self.translate(obj, target_lang, source_lang, context)
        if isinstance(obj, dict):
            return {
                k: self._translate_json_values(v, target_lang, source_lang, context)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [
                self._translate_json_values(item, target_lang, source_lang, context)
                for item in obj
            ]
        return obj

    def batch_translate(
        self,
        input_path: Path,
        target_langs: list[str],
        output_dir: Optional[Path] = None,
        source_lang: Optional[str] = None,
        context: Optional[str] = None,
        delay: float = 0.5,
    ) -> dict[str, Path]:
        results = {}
        base_dir = output_dir or input_path.parent

        for lang in target_langs:
            stem = input_path.stem
            suffix = input_path.suffix
            if suffix == ".json":
                out_path = base_dir / f"{stem}.{lang}.json"
            else:
                out_path = base_dir / f"{stem}.{lang}{suffix}"

            out_path = self.translate_file(
                input_path, lang, out_path, source_lang, context
            )
            results[lang] = out_path

            if delay > 0 and lang != target_langs[-1]:
                time.sleep(delay)

        return results
