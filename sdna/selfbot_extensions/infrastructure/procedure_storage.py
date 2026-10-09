"""
Procedure Storage - JSON-based persistence for procedures.

Infrastructure layer: implements ProcedureRepository.

Indexed by `site.action` because that is how everything else refers to a
procedure - the qualified name is the identity, the uuid is just a filename.
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional, List

from ..domain.procedure import Procedure, ProcedureStatus, ProcedureRepository

logger = logging.getLogger(__name__)

DEFAULT_PROCEDURE_DIR = str(Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "selfbot" / "procedures")


class JsonProcedureRepository(ProcedureRepository):
    """Persists procedures to JSON files."""

    def __init__(self, storage_dir: str = DEFAULT_PROCEDURE_DIR):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self.storage_dir / "index.json"
        self._load_index()

    def _load_index(self):
        """Load the qualified-name -> id index."""
        if self._index_file.exists():
            self._index = json.loads(self._index_file.read_text())
        else:
            self._index = {}

    def _save_index(self):
        self._index_file.write_text(json.dumps(self._index, indent=2))

    def _procedure_path(self, procedure_id: str) -> Path:
        return self.storage_dir / f"{procedure_id}.json"

    def save(self, procedure: Procedure) -> None:
        path = self._procedure_path(procedure.id)
        path.write_text(json.dumps(procedure.to_dict(), indent=2))
        self._index[procedure.qualified_name] = procedure.id
        self._save_index()

    def get(self, procedure_id: str) -> Optional[Procedure]:
        path = self._procedure_path(procedure_id)
        if not path.exists():
            return None
        return Procedure.from_dict(json.loads(path.read_text()))

    def get_by_name(self, site: str, action: str) -> Optional[Procedure]:
        procedure_id = self._index.get(f"{site}.{action}")
        if not procedure_id:
            return None
        return self.get(procedure_id)

    def list_all(self) -> List[Procedure]:
        procedures = []
        for procedure_id in self._index.values():
            procedure = self.get(procedure_id)
            if procedure:
                procedures.append(procedure)
        return procedures

    def list_by_site(self, site: str) -> List[Procedure]:
        return [p for p in self.list_all() if p.site == site]

    def list_by_status(self, status: ProcedureStatus) -> List[Procedure]:
        return [p for p in self.list_all() if p.status is status]

    def list_sites(self) -> List[str]:
        return sorted({p.site for p in self.list_all()})

    def delete(self, procedure_id: str) -> bool:
        path = self._procedure_path(procedure_id)
        if not path.exists():
            return False

        procedure = self.get(procedure_id)
        if procedure and procedure.qualified_name in self._index:
            del self._index[procedure.qualified_name]
            self._save_index()

        path.unlink()
        return True


class InMemoryProcedureRepository(ProcedureRepository):
    """In-memory repository, for tests and dry runs."""

    def __init__(self):
        self._by_id = {}
        self._index = {}

    def save(self, procedure: Procedure) -> None:
        self._by_id[procedure.id] = procedure
        self._index[procedure.qualified_name] = procedure.id

    def get(self, procedure_id: str) -> Optional[Procedure]:
        return self._by_id.get(procedure_id)

    def get_by_name(self, site: str, action: str) -> Optional[Procedure]:
        procedure_id = self._index.get(f"{site}.{action}")
        return self._by_id.get(procedure_id) if procedure_id else None

    def list_all(self) -> List[Procedure]:
        return list(self._by_id.values())

    def list_by_site(self, site: str) -> List[Procedure]:
        return [p for p in self.list_all() if p.site == site]

    def list_by_status(self, status: ProcedureStatus) -> List[Procedure]:
        return [p for p in self.list_all() if p.status is status]

    def list_sites(self) -> List[str]:
        return sorted({p.site for p in self.list_all()})

    def delete(self, procedure_id: str) -> bool:
        procedure = self._by_id.pop(procedure_id, None)
        if not procedure:
            return False
        self._index.pop(procedure.qualified_name, None)
        return True
