"""Unit tests for the translation tool (no API calls)."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from translator import SUPPORTED_LANGUAGES, Translator


def make_translator_with_mock(return_text: str) -> tuple[Translator, MagicMock]:
    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=return_text)]
    t.client.messages.create = MagicMock(return_value=mock_response)
    return t, t.client.messages.create


def test_supported_languages_not_empty():
    assert len(SUPPORTED_LANGUAGES) > 0
    assert "ko" in SUPPORTED_LANGUAGES
    assert "en" in SUPPORTED_LANGUAGES
    assert "ja" in SUPPORTED_LANGUAGES


def test_translate_returns_text():
    t, mock_create = make_translator_with_mock("Hello")
    result = t.translate("안녕하세요", target_lang="en")
    assert result == "Hello"
    mock_create.assert_called_once()


def test_translate_passes_source_lang():
    t, mock_create = make_translator_with_mock("こんにちは")
    t.translate("Hello", target_lang="ja", source_lang="en")
    call_kwargs = mock_create.call_args
    messages = call_kwargs.kwargs["messages"]
    assert "from English" in messages[0]["content"]


def test_translate_passes_context():
    t, mock_create = make_translator_with_mock("Hola")
    t.translate("Hello", target_lang="es", context="Greeting in a mobile app")
    call_kwargs = mock_create.call_args
    messages = call_kwargs.kwargs["messages"]
    assert "Greeting in a mobile app" in messages[0]["content"]


def test_translate_file_markdown():
    t, _ = make_translator_with_mock("# Hello\n\nThis is a test.")
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "test.md"
        inp.write_text("# 안녕\n\n테스트입니다.", encoding="utf-8")
        out = t.translate_file(inp, target_lang="en")
        assert out.exists()
        assert out.read_text(encoding="utf-8") == "# Hello\n\nThis is a test."
        assert "en" in out.name


def test_translate_file_custom_output_path():
    t, _ = make_translator_with_mock("Translated")
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "doc.md"
        inp.write_text("문서", encoding="utf-8")
        out_path = Path(tmpdir) / "subdir" / "doc_en.md"
        out = t.translate_file(inp, target_lang="en", output_path=out_path)
        assert out == out_path
        assert out.exists()


def test_translate_json_file():
    call_count = 0

    def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=f"translated_{call_count}")]
        return mock_response

    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key")
    t.client.messages.create = fake_create

    data = {"greeting": "안녕", "farewell": "잘가"}
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "strings.json"
        inp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out = t.translate_file(inp, target_lang="en")
        assert out.exists()
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["greeting"] == "translated_1"
        assert result["farewell"] == "translated_2"


def test_batch_translate():
    translated = {"en": "Hello", "ja": "こんにちは", "zh": "你好"}
    call_count = 0
    langs = list(translated.values())

    def fake_create(**kwargs):
        nonlocal call_count
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=langs[call_count % len(langs)])]
        call_count += 1
        return mock_response

    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key")
    t.client.messages.create = fake_create

    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "source.txt"
        inp.write_text("안녕하세요", encoding="utf-8")
        results = t.batch_translate(
            inp,
            target_langs=["en", "ja", "zh"],
            delay=0,
        )
        assert set(results.keys()) == {"en", "ja", "zh"}
        for path in results.values():
            assert path.exists()


def test_json_nested_structure():
    values = iter(["Save", "Cancel", "Required"])

    def fake_create(**kwargs):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=next(values))]
        return mock_response

    with patch("anthropic.Anthropic"):
        t = Translator(api_key="test-key")
    t.client.messages.create = fake_create

    data = {"buttons": {"save": "저장", "cancel": "취소"}, "errors": {"required": "필수"}}
    with tempfile.TemporaryDirectory() as tmpdir:
        inp = Path(tmpdir) / "nested.json"
        inp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out = t.translate_file(inp, target_lang="en")
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["buttons"]["save"] == "Save"
        assert result["buttons"]["cancel"] == "Cancel"
        assert result["errors"]["required"] == "Required"


if __name__ == "__main__":
    tests = [
        test_supported_languages_not_empty,
        test_translate_returns_text,
        test_translate_passes_source_lang,
        test_translate_passes_context,
        test_translate_file_markdown,
        test_translate_file_custom_output_path,
        test_translate_json_file,
        test_batch_translate,
        test_json_nested_structure,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
