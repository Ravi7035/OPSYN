"""Tiny JSON-file store for incident records (MVP persistence).

One file, rewritten atomically on every mutation. No database dependency:
the file is the source of truth, so records survive backend restarts and
frontend navigation. All file access is guarded by a lock; corrupt or
missing files degrade to an empty store (logged, never raised).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.models.incident_records import IncidentRecord, StageEvent, STATUS_INJECTED

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^INC-(\d{4})-(\d+)$")


def _utcnow_year() -> str:
    return f"{datetime.now(timezone.utc).year}"


class IncidentStore:
    """Synchronous JSON record store. Safe to share across requests."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    # -- internal ------------------------------------------------------

    def _read_state(self) -> dict[str, object]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"records": {}}
        try:
            state = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Incident store unreadable, starting empty: %s", exc)
            return {"records": {}}
        if not isinstance(state, dict) or not isinstance(state.get("records"), dict):
            logger.warning("Incident store has unexpected shape, starting empty")
            return {"records": {}}
        return state

    def _write_state(self, state: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(self._path)

    def _next_id(self, records: dict[str, object]) -> str:
        year = _utcnow_year()
        best = 0
        for key in records:
            match = _ID_RE.match(str(key))
            if match and match.group(1) == year:
                best = max(best, int(match.group(2)))
        return f"INC-{year}-{best + 1:03d}"

    # -- public ---------------------------------------------------------

    def create(
        self,
        service: str = "payment-api",
        injected_fault_type: str | None = None,
        agent_incident_id: str | None = None,
        detected_symptoms: list[str] | None = None,
        title: str = "Payment API experiencing elevated failures",
    ) -> IncidentRecord:
        """Create an INJECTED record with the next sequential ID."""
        with self._lock:
            state = self._read_state()
            records = state["records"]
            assert isinstance(records, dict)
            record = IncidentRecord(
                incident_id=self._next_id(records),
                agent_incident_id=agent_incident_id,
                service=service,
                title=title,
                injected_fault_type=injected_fault_type,
                detected_symptoms=list(detected_symptoms or []),
                stage_history=[StageEvent(stage=STATUS_INJECTED)],
            )
            records[record.incident_id] = record.model_dump(mode="json")
            self._write_state(state)
            logger.info(
                "INCIDENT_RECORDED id=%s fault=%s",
                record.incident_id,
                injected_fault_type,
            )
            return record

    def get(self, incident_id: str) -> IncidentRecord | None:
        with self._lock:
            records = self._read_state()["records"]
            assert isinstance(records, dict)
            raw = records.get(incident_id)
        if raw is None:
            return None
        try:
            return IncidentRecord.model_validate(raw)
        except Exception as exc:  # corrupt entry: visible, never fatal
            logger.warning("Incident record %s invalid: %s", incident_id, exc)
            return None

    def list_all(self) -> list[IncidentRecord]:
        """All records in chronological (creation) order."""
        with self._lock:
            records = self._read_state()["records"]
            assert isinstance(records, dict)
            raw_items = list(records.values())
        result: list[IncidentRecord] = []
        for raw in raw_items:
            try:
                result.append(IncidentRecord.model_validate(raw))
            except Exception as exc:
                logger.warning("Skipping invalid incident record: %s", exc)
        result.sort(key=lambda r: (r.created_at, r.incident_id))
        return result

    def update(self, incident_id: str, **fields: object) -> IncidentRecord | None:
        """Patch mutable fields; returns the updated record or None."""
        with self._lock:
            state = self._read_state()
            records = state["records"]
            assert isinstance(records, dict)
            raw = records.get(incident_id)
            if raw is None:
                return None
            try:
                record = IncidentRecord.model_validate(raw)
            except Exception as exc:
                logger.warning("Incident record %s invalid: %s", incident_id, exc)
                return None
            for key, value in fields.items():
                if key in IncidentRecord.model_fields:
                    setattr(record, key, value)
            records[incident_id] = record.model_dump(mode="json")
            self._write_state(state)
            return record

    def mark_stage(self, incident_id: str, stage: str) -> IncidentRecord | None:
        """Append a lifecycle transition; returns updated record or None."""
        with self._lock:
            state = self._read_state()
            records = state["records"]
            assert isinstance(records, dict)
            raw = records.get(incident_id)
            if raw is None:
                return None
            try:
                record = IncidentRecord.model_validate(raw)
            except Exception as exc:
                logger.warning("Incident record %s invalid: %s", incident_id, exc)
                return None
            record.mark_stage(stage)
            records[incident_id] = record.model_dump(mode="json")
            self._write_state(state)
            logger.info("INCIDENT_STAGE id=%s stage=%s", incident_id, stage)
            return record
