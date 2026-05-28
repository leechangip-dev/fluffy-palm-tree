"""CLI entry point for the translation tool."""

import argparse
import os
import sys
from pathlib import Path

from translator import SUPPORTED_LANGUAGES, Translator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="translate",
        description="Automated multilingual translation powered by Claude API",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- translate text inline ---
    text_parser = subparsers.add_parser("text", help="Translate a text string")
    text_parser.add_argument("text", help="Text to translate")
    text_parser.add_argument("-t", "--to", required=True, help="Target language code")
    text_parser.add_argument("-f", "--from", dest="from_lang", help="Source language code")
    text_parser.add_argument("-c", "--context", help="Additional context for translation")

    # --- translate a file ---
    file_parser = subparsers.add_parser("file", help="Translate a file")
    file_parser.add_argument("input", help="Input file path")
    file_parser.add_argument("-t", "--to", required=True, help="Target language code (comma-separated for batch)")
    file_parser.add_argument("-f", "--from", dest="from_lang", help="Source language code")
    file_parser.add_argument("-o", "--output", help="Output file or directory path")
    file_parser.add_argument("-c", "--context", help="Additional context for translation")
    file_parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay (seconds) between API calls in batch mode (default: 0.5)",
    )

    # --- list supported languages ---
    subparsers.add_parser("langs", help="List supported language codes")

    return parser


def cmd_text(args, translator: Translator) -> None:
    result = translator.translate(
        args.text,
        target_lang=args.to,
        source_lang=args.from_lang,
        context=args.context,
    )
    print(result)


def cmd_file(args, translator: Translator) -> None:
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    target_langs = [lang.strip() for lang in args.to.split(",")]

    output_arg = Path(args.output) if args.output else None

    if len(target_langs) == 1:
        out = translator.translate_file(
            input_path,
            target_langs[0],
            output_path=output_arg,
            source_lang=args.from_lang,
            context=args.context,
        )
        print(f"Saved: {out}")
    else:
        out_dir = output_arg if output_arg else input_path.parent
        results = translator.batch_translate(
            input_path,
            target_langs,
            output_dir=out_dir,
            source_lang=args.from_lang,
            context=args.context,
            delay=args.delay,
        )
        for lang, path in results.items():
            print(f"[{lang}] Saved: {path}")


def cmd_langs() -> None:
    print("Supported language codes:")
    for code, name in sorted(SUPPORTED_LANGUAGES.items()):
        print(f"  {code:<8} {name}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "langs":
        cmd_langs()
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    translator = Translator(api_key=api_key)

    if args.command == "text":
        cmd_text(args, translator)
    elif args.command == "file":
        cmd_file(args, translator)


if __name__ == "__main__":
    main()
