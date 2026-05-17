from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Iterable

from .base import TTSAdapter, TTSRequest, TTSResult


class TTSArena:
    def __init__(self, adapters: Iterable[TTSAdapter]) -> None:
        self.adapters = list(adapters)

    async def run(self, request: TTSRequest) -> list[TTSResult]:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        tasks = [self._safe_synthesize(adapter, request) for adapter in self.adapters]
        return await asyncio.gather(*tasks)

    async def _safe_synthesize(
        self, adapter: TTSAdapter, request: TTSRequest
    ) -> TTSResult:
        try:
            return await adapter.synthesize(request)
        except Exception as exc:  # noqa: BLE001 - arena should report all provider failures.
            return TTSResult(
                model_name=adapter.name,
                output_path=None,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )


def result_table(results: list[TTSResult]) -> str:
    rows = ["model\tstatus\tfile/error"]
    for result in results:
        detail = str(result.output_path) if result.ok else (result.error or "unknown error")
        rows.append(f"{result.model_name}\t{'OK' if result.ok else 'FAIL'}\t{detail}")
    return "\n".join(rows)


def write_results_manifest(results: list[TTSResult], output_dir: Path) -> Path:
    manifest_path = output_dir / "results.json"
    payload = [
        {
            "model_name": result.model_name,
            "output_path": str(result.output_path) if result.output_path else None,
            "ok": result.ok,
            "error": result.error,
        }
        for result in results
    ]
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def read_failed_model_names(output_dir: Path) -> set[str]:
    manifest_path = output_dir / "results.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No previous results manifest found: {manifest_path}. Run once without --rerun-failed."
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        str(item["model_name"])
        for item in payload
        if isinstance(item, dict) and not item.get("ok")
    }
