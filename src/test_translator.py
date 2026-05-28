"""Unit tests for the translation tool (no real API calls)."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent))

import anthropic
from translator import (
    DEFAULT_CACHE_PATH,
    SUPPORTED_LANGUAGES,
    TranslationCache,
    TranslationError,
    Translator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


def _make_translator(return_text: str = "translated") -> tuple[Translator, MagicMock]:
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = MagicMock(return_value=_mock_response(return_text))
    return t, t.client.messages.create


# ---------------------------------------------------------------------------
# Language support
# ---------------------------------------------------------------------------

def test_supported_languages_not_empty():
    assert len(SUPPORTED_LANGUAGES) > 0
    for code in ("ko", "en", "ja", "zh", "es"):
        assert code in SUPPORTED_LANGUAGES


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_invalid_target_lang_raises():
    t, _ = _make_translator()
    try:
        t.translate("hello", target_lang="xx")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "xx" in str(e)


def test_invalid_source_lang_raises():
    t, _ = _make_translator()
    try:
        t.translate("hello", target_lang="en", source_lang="zz")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "zz" in str(e)


def test_lang_code_case_insensitive():
    t, mock_create = _make_translator("Hello")
    result = t.translate("안녕", target_lang="EN")
    assert result == "Hello"


# ---------------------------------------------------------------------------
# Empty / whitespace input
# ---------------------------------------------------------------------------

def test_empty_string_returns_empty():
    t, mock_create = _make_translator()
    result = t.translate("", target_lang="en")
    assert result == ""
    mock_create.assert_not_called()


def test_whitespace_only_returns_as_is():
    t, mock_create = _make_translator()
    result = t.translate("   \n", target_lang="en")
    assert result == "   \n"
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Basic translate
# ---------------------------------------------------------------------------

def test_translate_returns_text():
    t, mock_create = _make_translator("Hello")
    assert t.translate("안녕하세요", target_lang="en") == "Hello"
    mock_create.assert_called_once()


def test_translate_passes_source_lang():
    t, mock_create = _make_translator("こんにちは")
    t.translate("Hello", target_lang="ja", source_lang="en")
    content = mock_create.call_args.kwargs["messages"][0]["content"]
    assert "from English" in content


def test_translate_passes_context():
    t, mock_create = _make_translator("Hola")
    t.translate("Hello", target_lang="es", context="greeting in a mobile app")
    content = mock_create.call_args.kwargs["messages"][0]["content"]
    assert "greeting in a mobile app" in content


def test_translate_uses_prompt_caching():
    t, mock_create = _make_translator("Hello")
    t.translate("안녕", target_lang="en")
    system = mock_create.call_args.kwargs["system"]
    assert any(
        isinstance(block, dict) and block.get("cache_control") == {"type": "ephemeral"}
        for block in system
    )


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

def test_retry_on_rate_limit():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)

    call_count = 0

    def flaky(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            mock_resp = MagicMock()
            mock_resp.status_code = 429
            mock_resp.headers = {}
            raise anthropic.RateLimitError("rate limit", response=mock_resp, body={})
        return _mock_response("Hello")

    t.client.messages.create = flaky

    with patch("time.sleep"):
        result = t.translate("안녕", target_lang="en")

    assert result == "Hello"
    assert call_count == 3


def test_retry_exhausted_raises_translation_error():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)

    def always_fail(**kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}
        raise anthropic.RateLimitError("rate limit", response=mock_resp, body={})

    t.client.messages.create = always_fail

    try:
        with patch("time.sleep"):
            t.translate("안녕", target_lang="en")
        assert False, "Should have raised TranslationError"
    except TranslationError:
        pass


def test_4xx_error_no_retry():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)

    call_count = 0

    def bad_request(**kwargs):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.headers = {}
        raise anthropic.BadRequestError("bad request", response=mock_resp, body={})

    t.client.messages.create = bad_request

    try:
        with patch("time.sleep"):
            t.translate("hello", target_lang="en")
        assert False, "Should have raised"
    except Exception:
        pass

    assert call_count == 1


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_cache_hit_skips_api():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "cache.json"
        with patch("anthropic.Anthropic"):
            t = Translator(api_key="test-key", use_cache=True, cache_path=cache_path)
        mock_create = MagicMock(return_value=_mock_response("Hello"))
        t.client.messages.create = mock_create

        t.translate("안녕", target_lang="en")
        t.translate("안녕", target_lang="en")

        assert mock_create.call_count == 1


def test_cache_persists_to_disk():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "cache.json"
        with patch("anthropic.Anthropic"):
            t1 = Translator(api_key="test-key", use_cache=True, cache_path=cache_path)
        t1.client.messages.create = MagicMock(return_value=_mock_response("Hello"))
        t1.translate("안녕", target_lang="en")

        with patch("anthropic.Anthropic"):
            t2 = Translator(api_key="test-key", use_cache=True, cache_path=cache_path)
        t2.client.messages.create = MagicMock(return_value=_mock_response("SHOULD NOT BE CALLED"))
        result = t2.translate("안녕", target_lang="en")

        assert result == "Hello"
        t2.client.messages.create.assert_not_called()


def test_no_cache_always_calls_api():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    mock_create = MagicMock(return_value=_mock_response("Hello"))
    t.client.messages.create = mock_create

    t.translate("안녕", target_lang="en")
    t.translate("안녕", target_lang="en")

    assert mock_create.call_count == 2


# ---------------------------------------------------------------------------
# File translation — Markdown / text
# ---------------------------------------------------------------------------

def test_translate_file_markdown():
    t, _ = _make_translator("# Hello\n\nThis is a test.")
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "test.md"
        inp.write_text("# 안녕\n\n테스트입니다.", encoding="utf-8")
        out = t.translate_file(inp, target_lang="en")
        assert out.exists()
        assert out.read_text(encoding="utf-8") == "# Hello\n\nThis is a test."
        assert "en" in out.name


def test_translate_file_custom_output_path():
    t, _ = _make_translator("Translated")
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "doc.md"
        inp.write_text("문서", encoding="utf-8")
        out_path = Path(tmpdir) / "subdir" / "doc_en.md"
        out = t.translate_file(inp, target_lang="en", output_path=out_path)
        assert out == out_path
        assert out.exists()


# ---------------------------------------------------------------------------
# File translation — JSON
# ---------------------------------------------------------------------------

def test_translate_json_file():
    counter = iter(["Save", "Cancel"])

    def fake_create(**kwargs):
        return _mock_response(next(counter))

    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = fake_create

    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "strings.json"
        inp.write_text(json.dumps({"save": "저장", "cancel": "취소"}, ensure_ascii=False))
        out = t.translate_file(inp, target_lang="en")
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["save"] == "Save"
        assert result["cancel"] == "Cancel"


def test_translate_json_nested():
    values = iter(["Save", "Cancel", "Required"])

    def fake_create(**kwargs):
        return _mock_response(next(values))

    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = fake_create

    data = {"buttons": {"save": "저장", "cancel": "취소"}, "errors": {"required": "필수"}}
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "nested.json"
        inp.write_text(json.dumps(data, ensure_ascii=False))
        out = t.translate_file(inp, target_lang="en")
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["buttons"]["save"] == "Save"
        assert result["buttons"]["cancel"] == "Cancel"
        assert result["errors"]["required"] == "Required"


def test_malformed_json_raises_value_error():
    t, _ = _make_translator()
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "bad.json"
        inp.write_text("{not valid json", encoding="utf-8")
        try:
            t.translate_file(inp, target_lang="en")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "JSON" in str(e) or "bad.json" in str(e)


# ---------------------------------------------------------------------------
# File translation — YAML
# ---------------------------------------------------------------------------

def test_translate_yaml_file():
    try:
        import yaml
    except ImportError:
        print("  SKIP  test_translate_yaml_file (pyyaml not installed)")
        return

    counter = iter(["Login", "Logout"])

    def fake_create(**kwargs):
        return _mock_response(next(counter))

    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = fake_create

    data = {"auth": {"login": "로그인", "logout": "로그아웃"}}
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "strings.yaml"
        inp.write_text(yaml.dump(data, allow_unicode=True))
        out = t.translate_file(inp, target_lang="en")
        result = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert result["auth"]["login"] == "Login"
        assert result["auth"]["logout"] == "Logout"


def test_malformed_yaml_raises_value_error():
    try:
        import yaml
    except ImportError:
        print("  SKIP  test_malformed_yaml_raises_value_error (pyyaml not installed)")
        return

    t, _ = _make_translator()
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "bad.yaml"
        inp.write_text("key: [unclosed", encoding="utf-8")
        try:
            t.translate_file(inp, target_lang="en")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "YAML" in str(e) or "bad.yaml" in str(e)


# ---------------------------------------------------------------------------
# Batch translate
# ---------------------------------------------------------------------------

def test_batch_translate():
    langs_out = {"en": "Hello", "ja": "こんにちは", "zh": "你好"}
    it = iter(langs_out.values())

    def fake_create(**kwargs):
        return _mock_response(next(it))

    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = fake_create

    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "source.txt"
        inp.write_text("안녕하세요", encoding="utf-8")
        results = t.batch_translate(inp, target_langs=["en", "ja", "zh"], delay=0)
        assert set(results.keys()) == {"en", "ja", "zh"}
        for path in results.values():
            assert path.exists()


def test_batch_translate_progress_callback():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = MagicMock(return_value=_mock_response("x"))

    progress_calls = []

    def on_progress(current, total, lang):
        progress_calls.append((current, total, lang))

    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "source.txt"
        inp.write_text("hello", encoding="utf-8")
        t.batch_translate(inp, target_langs=["en", "ja"], delay=0, progress_callback=on_progress)

    assert progress_calls == [(1, 2, "en"), (2, 2, "ja")]


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def test_detect_language_returns_known_code():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = MagicMock(return_value=_mock_response("ko"))
    result = t.detect_language("안녕하세요")
    assert result == "ko"


def test_detect_language_fuzzy_match():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = MagicMock(return_value=_mock_response("the language is en"))
    result = t.detect_language("Hello world")
    assert result == "en"


def test_detect_language_fallback():
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key", use_cache=False)
    t.client.messages.create = MagicMock(return_value=_mock_response("xyz"))
    result = t.detect_language("some text")
    assert result == "en"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_supported_languages_not_empty,
        test_invalid_target_lang_raises,
        test_invalid_source_lang_raises,
        test_lang_code_case_insensitive,
        test_empty_string_returns_empty,
        test_whitespace_only_returns_as_is,
        test_translate_returns_text,
        test_translate_passes_source_lang,
        test_translate_passes_context,
        test_translate_uses_prompt_caching,
        test_retry_on_rate_limit,
        test_retry_exhausted_raises_translation_error,
        test_4xx_error_no_retry,
        test_cache_hit_skips_api,
        test_cache_persists_to_disk,
        test_no_cache_always_calls_api,
        test_translate_file_markdown,
        test_translate_file_custom_output_path,
        test_translate_json_file,
        test_translate_json_nested,
        test_malformed_json_raises_value_error,
        test_translate_yaml_file,
        test_malformed_yaml_raises_value_error,
        test_batch_translate,
        test_batch_translate_progress_callback,
        test_detect_language_returns_known_code,
        test_detect_language_fuzzy_match,
        test_detect_language_fallback,
    ]

    passed = failed = skipped = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except SystemExit:
            raise
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(0 if failed == 0 else 1)
