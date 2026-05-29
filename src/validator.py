"""Translation validation engine: completeness and quality checks."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from translator import SUPPORTED_LANGUAGES, Translator


@dataclass
class ValidationResult:
    source_file: Path
    translated_file: Path
    lang: str
    completeness_issues: list[str] = field(default_factory=list)
    quality_score: Optional[float] = None
    quality_feedback: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        return len(self.completeness_issues) == 0

    @property
    def passed(self) -> bool:
        if not self.is_complete:
            return False
        if self.quality_score is not None and self.quality_score < 7.0:
            return False
        return True

    def summary(self) -> str:
        lines = [f"[{self.lang}] {self.translated_file.name}"]
        if self.is_complete:
            lines.append("  완전성: ✅ 이상 없음")
        else:
            lines.append(f"  완전성: ❌ {len(self.completeness_issues)}개 문제")
            for issue in self.completeness_issues:
                lines.append(f"    - {issue}")
        if self.quality_score is not None:
            icon = "✅" if self.quality_score >= 7.0 else "⚠️"
            lines.append(f"  품질 점수: {icon} {self.quality_score:.1f}/10")
            if self.quality_feedback:
                lines.append(f"  피드백: {self.quality_feedback}")
        return "\n".join(lines)


class TranslationValidator:
    def __init__(self, translator: Optional[Translator] = None):
        self._translator = translator

    # ------------------------------------------------------------------
    # Completeness checks
    # ------------------------------------------------------------------

    def check_completeness(self, source: Path, translated: Path) -> list[str]:
        suffix = source.suffix.lower()
        if suffix == ".json":
            return self._check_json(source, translated)
        if suffix in (".yaml", ".yml"):
            return self._check_yaml(source, translated)
        return self._check_markdown(source, translated)

    def _check_markdown(self, source: Path, translated: Path) -> list[str]:
        issues = []
        src_text = source.read_text(encoding="utf-8")
        if not translated.exists():
            return [f"번역 파일 없음: {translated.name}"]
        trl_text = translated.read_text(encoding="utf-8")

        src_headings = re.findall(r"^(#{1,6})\s+.+", src_text, re.MULTILINE)
        trl_headings = re.findall(r"^(#{1,6})\s+.+", trl_text, re.MULTILINE)

        if len(src_headings) != len(trl_headings):
            issues.append(
                f"헤딩 개수 불일치: 소스 {len(src_headings)}개 vs 번역 {len(trl_headings)}개"
            )

        src_codes = re.findall(r"```[\w]*", src_text)
        trl_codes = re.findall(r"```[\w]*", trl_text)
        if len(src_codes) != len(trl_codes):
            issues.append(
                f"코드 블록 개수 불일치: 소스 {len(src_codes) // 2}개 vs 번역 {len(trl_codes) // 2}개"
            )

        src_lines = [l for l in src_text.splitlines() if l.strip()]
        trl_lines = [l for l in trl_text.splitlines() if l.strip()]
        if len(trl_lines) < len(src_lines) * 0.5:
            issues.append("번역 내용이 소스 대비 50% 미만 — 번역 누락 의심")

        return issues

    def _check_json(self, source: Path, translated: Path) -> list[str]:
        if not translated.exists():
            return [f"번역 파일 없음: {translated.name}"]
        try:
            src = json.loads(source.read_text(encoding="utf-8"))
            trl = json.loads(translated.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return [f"JSON 파싱 오류: {e}"]
        return self._compare_keys(src, trl, "")

    def _check_yaml(self, source: Path, translated: Path) -> list[str]:
        if not YAML_AVAILABLE:
            return ["pyyaml 미설치로 YAML 검증 불가"]
        if not translated.exists():
            return [f"번역 파일 없음: {translated.name}"]
        try:
            src = yaml.safe_load(source.read_text(encoding="utf-8"))
            trl = yaml.safe_load(translated.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            return [f"YAML 파싱 오류: {e}"]
        return self._compare_keys(src, trl, "")

    def _compare_keys(self, src, trl, prefix: str) -> list[str]:
        issues = []
        if not isinstance(src, dict):
            return issues
        for key in src:
            full_key = f"{prefix}.{key}" if prefix else key
            if key not in trl:
                issues.append(f"누락된 키: {full_key}")
            elif isinstance(src[key], dict):
                issues.extend(self._compare_keys(src[key], trl.get(key, {}), full_key))
        return issues

    # ------------------------------------------------------------------
    # Quality check via Claude API
    # ------------------------------------------------------------------

    def check_quality(
        self,
        source_text: str,
        translated_text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
    ) -> tuple[float, str]:
        if self._translator is None:
            raise RuntimeError("Translator instance required for quality check")

        target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        source_hint = f"({SUPPORTED_LANGUAGES.get(source_lang, source_lang)} → {target_name})" if source_lang else f"(→ {target_name})"

        prompt = (
            f"Evaluate the translation quality {source_hint}.\n\n"
            f"[Source]\n{source_text[:2000]}\n\n"
            f"[Translation]\n{translated_text[:2000]}\n\n"
            "Rate on a scale of 1-10 and give one-line feedback in Korean.\n"
            'Respond ONLY with valid JSON: {"score": <number>, "feedback": "<string>"}'
        )

        raw = self._translator._call_api(
            system=[{
                "type": "text",
                "text": "You are a professional translation quality evaluator. Respond only with the requested JSON.",
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
            data = json.loads(match.group() if match else raw)
            score = float(data["score"])
            feedback = str(data["feedback"])
            return round(min(max(score, 0), 10), 1), feedback
        except Exception:
            return 0.0, f"품질 평가 파싱 실패: {raw[:100]}"

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def validate_file(
        self,
        source: Path,
        target_lang: str,
        translated_path: Optional[Path] = None,
        check_quality: bool = False,
        source_lang: Optional[str] = None,
    ) -> ValidationResult:
        if translated_path is None:
            suffix = source.suffix.lower()
            if suffix == ".json":
                translated_path = source.parent / f"{source.stem}.{target_lang}.json"
            else:
                translated_path = source.parent / f"{source.stem}.{target_lang}{suffix}"

        result = ValidationResult(
            source_file=source,
            translated_file=translated_path,
            lang=target_lang,
            completeness_issues=self.check_completeness(source, translated_path),
        )

        if check_quality and translated_path.exists():
            src_text = source.read_text(encoding="utf-8")
            trl_text = translated_path.read_text(encoding="utf-8")
            result.quality_score, result.quality_feedback = self.check_quality(
                src_text, trl_text, target_lang, source_lang
            )

        return result

    def validate_batch(
        self,
        source: Path,
        target_langs: list[str],
        check_quality: bool = False,
        source_lang: Optional[str] = None,
    ) -> list[ValidationResult]:
        return [
            self.validate_file(source, lang, check_quality=check_quality, source_lang=source_lang)
            for lang in target_langs
        ]
