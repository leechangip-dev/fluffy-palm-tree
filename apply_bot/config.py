"""YAML 설정 파일을 읽고 ${VAR} 형태의 환경변수를 치환한다."""
from __future__ import annotations

import os
import re

import yaml

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env(value):
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            var = match.group(1)
            if var not in os.environ:
                raise KeyError(
                    f"환경변수 {var} 가 설정되어 있지 않습니다. "
                    ".env 또는 셸 환경에 값을 지정한 뒤 다시 실행하세요."
                )
            return os.environ[var]

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: 설정 파일 최상위는 매핑(dict)이어야 합니다.")
    return _substitute_env(raw)
