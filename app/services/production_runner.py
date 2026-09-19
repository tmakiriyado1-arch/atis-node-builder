"""Production-facing runner for the existing NORA pipeline."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

from app.models import ImportBundle
from app.services.pipeline import EntityPipelineService, PipelineResult
from app.services.rita_intake import RITAEntity


@dataclass
class ProductionRunSummary:
    """Summary of a single production run with explicit batch-level accounting."""

    input_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    results: List[PipelineResult] = field(default_factory=list)
    bundle: Optional[ImportBundle] = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    written_files: dict[str, str] = field(default_factory=dict)


class ProductionRunner:
    """Execute the existing NORA pipeline against a RITA export and write ImportBundle artifacts."""

    def __init__(
        self,
        pipeline: Optional[EntityPipelineService] = None,
        output_dir: str | Path | None = None,
        overwrite: bool = True,
    ) -> None:
        self.pipeline = pipeline or EntityPipelineService()
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self.overwrite = overwrite

    def load_entities(self, input_path: str | Path) -> List[RITAEntity]:
        path = Path(input_path)
        if not path.exists():
            raise ValueError(f"RITA input file does not exist: {path}")

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"RITA input is not valid JSON: {path}") from exc

        if raw is None:
            raise ValueError("RITA input is empty")

        rows: Sequence[Any]
        if isinstance(raw, dict):
            rows = [raw]
        elif isinstance(raw, list):
            rows = raw
        else:
            raise ValueError("RITA input must be a JSON object or a list of objects")

        entities: List[RITAEntity] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Every RITA export entry must be an object")
            entities.append(RITAEntity.from_row(row))
        return entities

    async def run_file(self, input_path: str | Path, output_dir: str | Path | None = None, overwrite: Optional[bool] = None) -> ProductionRunSummary:
        input_file = Path(input_path)
        entities = self.load_entities(input_file)
        target_dir = Path(output_dir) if output_dir is not None else (self.output_dir if self.output_dir is not None else None)
        if target_dir is not None:
            target_dir.mkdir(parents=True, exist_ok=True)

        results = await self.pipeline.run_batch(entities)
        completed = [result for result in results if result.status == "completed" and result.canonical_row is not None]
        bundle = ImportBundle.from_rows([result.canonical_row for result in completed])

        summary = ProductionRunSummary(
            input_path=input_file,
            output_dir=target_dir,
            results=results,
            bundle=bundle,
            processed=len(results),
            succeeded=len(completed),
            failed=len(results) - len(completed),
        )

        if target_dir is not None:
            summary.written_files = self._write_bundle(target_dir, bundle, overwrite=overwrite if overwrite is not None else self.overwrite)

        return summary

    def run_file_sync(self, input_path: str | Path, output_dir: str | Path | None = None, overwrite: Optional[bool] = None) -> ProductionRunSummary:
        return asyncio.run(self.run_file(input_path, output_dir=output_dir, overwrite=overwrite))

    @staticmethod
    def _write_bundle(output_dir: Path, bundle: ImportBundle, overwrite: bool = True) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_map = {
            "nodes.csv": bundle.csv_text,
            "nodes.json": bundle.json_text,
            "node_template.md": bundle.template_text,
        }
        written: dict[str, str] = {}
        for filename, content in artifact_map.items():
            target = output_dir / filename
            if target.exists() and not overwrite:
                raise ValueError(f"Refusing to overwrite existing artifact: {target}")
            target.write_text(content, encoding="utf-8")
            written[filename] = str(target)
        return written


NoraProductionRunner = ProductionRunner
