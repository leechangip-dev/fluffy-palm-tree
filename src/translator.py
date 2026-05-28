"""Core translation engine using the Claude API with prompt caching."""

import anthropic
import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

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

DEFAULT_CACHE_PATH = Path.home() / ".cache" / "translation_tool" / "cache.json"

MAX_RETRIES = 3


class TranslationError(Exception):
    """Raised when translation fails after all retries."""


class TranslationCache:
    def __init__(self, path: Path = DEFAULT_CACHE_PATH):
        self.path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _key(text: str, target_lang: str, source_lang: Optional[str]) -> str:
        raw = f"{target_lang}\x00{source_lang or ''}\x00{text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, text: str, target_lang: str, source_lang: Optional[str] = None) -> Optional[str]:
        return self._data.get(self._key(text, target_lang, source_lang))

    def put(self, text: str, target_lang: str, source_lang: Optional[str], translated: str) -> None:
        self._data[self._key(text, target_lang, source_lang)] = translated
        self._save()


def _validate_lang(code: str, label: str = "language") -> str:
    code = code.lower()
    if code not in SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGES.keys()))
        raise ValueError(
            f"Unsupported {label} code: {code!r}. Supported: {supported}"
        )
    return code


class Translator:
    def __init__(
        self,
        api_key: Optional[str] = None,
        use_cache: bool = True,
        cache_path: Optional[Path] = None,
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self._cache = TranslationCache(cache_path or DEFAULT_CACHE_PATH) if use_cache else None

    def _call_api(self, system: list, messages: list) -> str:
        delay = 2.0
        last_exc: Exception = RuntimeError("unknown error")
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=8096,
                    system=system,
                    messages=messages,
                )
                if not response.content or not hasattr(response.content[0], "text"):
                    raise TranslationError("Unexpected API response structure")
                return response.content[0].text
            except anthropic.RateLimitError as exc:
                last_exc = exc
            except anthropic.APIStatusError as exc:
                if exc.status_code < 500:
                    raise TranslationError(f"API error {exc.status_code}: {exc.message}") from exc
                last_exc = exc
            except anthropic.APIConnectionError as exc:
                last_exc = exc

            if attempt < MAX_RETRIES:
                time.sleep(delay)
                delay *= 2

        raise TranslationError(
            f"Translation failed after {MAX_RETRIES} retries: {last_exc}"
        ) from last_exc

    def detect_language(self, text: str) -> str:
        """Detect the language of the given text; returns a SUPPORTED_LANGUAGES code."""
        codes = ", ".join(sorted(SUPPORTED_LANGUAGES.keys()))
        result = self._call_api(
            system=[{
                "type": "text",
                "text": "You are a language detection tool. Respond with only the language code, nothing else.",
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": (
                    f"Detect the language of the text below. "
                    f"Respond with exactly one code from: {codes}.\n\n{text[:500]}"
                ),
            }],
        )
        detected = result.strip().lower()
        if detected in SUPPORTED_LANGUAGES:
            return detected
        for code in SUPPORTED_LANGUAGES:
            if code in detected:
                return code
        return "en"

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        context: Optional[str] = None,
    ) -> str:
        if not text or not text.strip():
            return text

        target_lang = _validate_lang(target_lang, "target language")
        if source_lang:
            source_lang = _validate_lang(source_lang, "source language")

        if self._cache:
            cached = self._cache.get(text, target_lang, source_lang)
            if cached is not None:
                return cached

        target_name = SUPPORTED_LANGUAGES[target_lang]
        source_hint = f" from {SUPPORTED_LANGUAGES[source_lang]}" if source_lang else ""
        context_block = f"\n\nAdditional context: {context}" if context else ""
        user_prompt = (
            f"Translate the following text{source_hint} to {target_name}."
            f"{context_block}\n\nText to translate:\n{text}"
        )

        result = self._call_api(
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )

        if self._cache:
            self._cache.put(text, target_lang, source_lang, result)

        return result

    def translate_file(
        self,
        input_path: Path,
        target_lang: str,
        output_path: Optional[Path] = None,
        source_lang: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Path:
        suffix = input_path.suffix.lower()

        if suffix == ".json":
            return self._translate_json_file(input_path, target_lang, output_path, source_lang, context)
        if suffix in (".yaml", ".yml"):
            return self._translate_yaml_file(input_path, target_lang, output_path, source_lang, context)

        try:
            text = input_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = input_path.read_text(encoding="latin-1")

        translated = self.translate(text, target_lang, source_lang, context)
        out = output_path or (input_path.parent / f"{input_path.stem}.{target_lang}{input_path.suffix}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(translated, encoding="utf-8")
        return out

    def _translate_json_file(
        self, input_path: Path, target_lang: str, output_path: Optional[Path],
        source_lang: Optional[str], context: Optional[str],
    ) -> Path:
        try:
            data = json.loads(input_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {input_path.name}: {exc}") from exc

        translated = self._translate_obj(data, target_lang, source_lang, context)
        out = output_path or (input_path.parent / f"{input_path.stem}.{target_lang}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(translated, ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    def _translate_yaml_file(
        self, input_path: Path, target_lang: str, output_path: Optional[Path],
        source_lang: Optional[str], context: Optional[str],
    ) -> Path:
        if not YAML_AVAILABLE:
            raise RuntimeError("pyyaml is required for YAML support: pip install pyyaml")
        try:
            data = yaml.safe_load(input_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {input_path.name}: {exc}") from exc

        translated = self._translate_obj(data, target_lang, source_lang, context)
        out = output_path or (input_path.parent / f"{input_path.stem}.{target_lang}{input_path.suffix}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            yaml.dump(translated, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        return out

    def _translate_obj(self, obj, target_lang: str, source_lang: Optional[str], context: Optional[str]):
        if isinstance(obj, str):
            return self.translate(obj, target_lang, source_lang, context)
        if isinstance(obj, dict):
            return {k: self._translate_obj(v, target_lang, source_lang, context) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._translate_obj(item, target_lang, source_lang, context) for item in obj]
        return obj

    def batch_translate(
        self,
        input_path: Path,
        target_langs: list[str],
        output_dir: Optional[Path] = None,
        source_lang: Optional[str] = None,
        context: Optional[str] = None,
        delay: float = 0.5,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict[str, Path]:
        base_dir = output_dir or input_path.parent
        suffix = input_path.suffix.lower()
        total = len(target_langs)
        results: dict[str, Path] = {}

        for i, lang in enumerate(target_langs, 1):
            if progress_callback:
                progress_callback(i, total, lang)

            stem = input_path.stem
            if suffix == ".json":
                out_path = base_dir / f"{stem}.{lang}.json"
            else:
                out_path = base_dir / f"{stem}.{lang}{suffix}"

            results[lang] = self.translate_file(input_path, lang, out_path, source_lang, context)

            if delay > 0 and i < total:
                time.sleep(delay)

        return results
