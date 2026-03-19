# -*- coding: utf-8 -*-
"""
Codex CLI backend adapter.

This module provides a minimal, structured way for the repository to delegate
LLM work to the local Codex runtime via ``codex exec``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import Config


logger = logging.getLogger(__name__)


class CodexBackendError(RuntimeError):
    """Raised when the Codex CLI backend is unavailable or returns invalid data."""


def _snippet(text: str, limit: int = 400) -> str:
    """Return a compact single-line snippet for logs and error messages."""
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


@dataclass
class CodexRunResult:
    """Structured result from one Codex CLI invocation."""

    payload: Dict[str, Any]
    stdout: str = ""
    stderr: str = ""
    model_used: str = "codex"


class CodexBackend:
    """Thin wrapper around ``codex exec`` for structured JSON responses."""

    def __init__(self, config: Config, *, cwd: Optional[Path] = None):
        self._config = config
        self._cwd = Path(cwd or Path(__file__).parent.parent).resolve()

    def _temp_root(self) -> Path:
        """Return a writable non-/tmp root for per-call Codex state."""
        env_codex_home = os.environ.get("CODEX_HOME", "").strip()
        if env_codex_home:
            base = Path(env_codex_home).resolve().parent / ".codex-runtime-tmp"
        else:
            base = self._cwd / ".codex-runtime-tmp"
        base.mkdir(parents=True, exist_ok=True)
        return base

    @staticmethod
    def command_path() -> Optional[str]:
        """Return the resolved Codex binary path, if available."""
        return shutil.which("codex")

    @classmethod
    def is_available(cls) -> bool:
        """True when the Codex CLI is available on PATH."""
        return bool(cls.command_path())

    def run_structured(
        self,
        prompt: str,
        schema: Dict[str, Any],
        *,
        image_paths: Optional[List[Path]] = None,
    ) -> CodexRunResult:
        """Execute a Codex prompt and parse the final structured JSON response."""
        codex_bin = self.command_path()
        if not codex_bin:
            raise CodexBackendError("Codex CLI 未安装或不在 PATH 中")

        with tempfile.TemporaryDirectory(
            prefix="codex-backend-",
            dir=str(self._temp_root()),
        ) as temp_dir:
            temp_path = Path(temp_dir)
            schema_path = temp_path / "schema.json"
            output_path = temp_path / "response.json"
            codex_home = temp_path / "codex-home"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            codex_home.mkdir(parents=True, exist_ok=True)
            self._prepare_codex_home(codex_home)

            command = [
                codex_bin,
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
                "-o",
                str(output_path),
            ]
            if self._config.codex_model:
                command.extend(["--model", self._config.codex_model])
            for image_path in image_paths or []:
                command.extend(["--image", str(image_path)])
            command.extend(["-C", str(self._cwd), prompt])

            logger.debug("Running Codex backend command: %s", command)

            try:
                env = os.environ.copy()
                env["CODEX_HOME"] = str(codex_home)
                completed = subprocess.run(
                    command,
                    cwd=str(self._cwd),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self._config.codex_timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexBackendError(
                    f"Codex 调用超时（>{self._config.codex_timeout_seconds} 秒）"
                ) from exc
            except OSError as exc:
                raise CodexBackendError(f"启动 Codex CLI 失败: {exc}") from exc

            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()

            if completed.returncode != 0 and not output_path.exists():
                message = stderr or stdout or f"exit code {completed.returncode}"
                raise CodexBackendError(f"Codex 调用失败: {message}")

            if not output_path.exists():
                raise CodexBackendError("Codex 调用未生成结构化输出文件")

            raw_output = output_path.read_text(encoding="utf-8").strip()
            if not raw_output and stdout:
                logger.warning(
                    "Codex output file is empty; falling back to stdout. stdout=%s stderr=%s",
                    _snippet(stdout),
                    _snippet(stderr),
                )
                raw_output = stdout

            if not raw_output:
                detail_parts: List[str] = []
                if stderr:
                    detail_parts.append(f"stderr={_snippet(stderr)}")
                if stdout:
                    detail_parts.append(f"stdout={_snippet(stdout)}")
                detail = f"（{'；'.join(detail_parts)}）" if detail_parts else ""
                raise CodexBackendError(f"Codex 返回了空响应{detail}")

            try:
                payload = json.loads(raw_output)
            except json.JSONDecodeError as exc:
                raise CodexBackendError(f"Codex 返回的内容不是合法 JSON: {raw_output[:200]}") from exc

            if completed.returncode != 0:
                logger.warning(
                    "Codex CLI exited with code %s, but a valid structured payload was returned. stderr=%s",
                    completed.returncode,
                    stderr[:400],
                )

            return CodexRunResult(
                payload=payload,
                stdout=stdout,
                stderr=stderr,
                model_used=f"codex:{self._config.codex_model or 'default'}",
            )

    @staticmethod
    def _prepare_codex_home(target_dir: Path) -> None:
        """Seed a writable CODEX_HOME from an existing mounted/login-ready home."""
        source_dirs: List[Path] = []

        # Prefer an explicit CODEX_HOME mount (used by Docker/NAS deployments),
        # then fall back to the conventional home directory config.
        env_codex_home = os.environ.get("CODEX_HOME", "").strip()
        if env_codex_home:
            source_dirs.append(Path(env_codex_home))
        source_dirs.append(Path.home() / ".codex")

        for source_dir in source_dirs:
            if not source_dir.exists() or not source_dir.is_dir():
                continue

            copied_any = False
            for child in source_dir.iterdir():
                target_path = target_dir / child.name
                if child.is_dir():
                    shutil.copytree(child, target_path, dirs_exist_ok=True)
                    copied_any = True
                elif child.is_file():
                    shutil.copy2(child, target_path)
                    copied_any = True

            if copied_any:
                return


def build_smoke_test_schema() -> Dict[str, Any]:
    """Schema used by the CLI smoke test to verify Codex integration."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status",
            "backend",
            "analysis_summary",
            "confidence_level",
        ],
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ok"],
            },
            "backend": {
                "type": "string",
                "enum": ["codex"],
            },
            "analysis_summary": {
                "type": "string",
                "minLength": 1,
            },
            "confidence_level": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
        },
    }


def build_smoke_test_prompt() -> str:
    """Prompt used by the CLI smoke test."""
    return (
        "You are validating a repository integration with Codex. "
        "Return a JSON object that matches the provided schema exactly. "
        "Use status='ok', backend='codex', confidence_level='high', and "
        "write a short Chinese summary proving you understood this is a Codex "
        "smoke test for a stock-analysis repository. Do not include any extra fields."
    )


def build_text_response_schema() -> Dict[str, Any]:
    """Schema for plain-text Codex generations wrapped in a JSON object."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["content"],
        "properties": {
            "content": {
                "type": "string",
                "minLength": 1,
            },
        },
    }
