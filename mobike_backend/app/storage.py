import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DEFAULT_DATA_PATH = os.path.join(DATA_DIR, "data.json")


def _utc_ts() -> int:
    """Return unix timestamp (seconds) in UTC."""
    return int(time.time())


@dataclass
class StorageError(Exception):
    """Represents storage-layer errors."""

    message: str


class JsonFileStorage:
    """
    Very small file-based storage for a demo/college project.

    Data shape:
    {
      "users": [{id, name, email, password_hash, is_admin, created_at}],
      "bikes": [{id, name, model, location, rate_per_hour, is_available, created_at, updated_at}],
      "rentals": [{id, user_id, bike_id, start_time, end_time, status, total_cost}]
    }
    """

    def __init__(self, path: str = DEFAULT_DATA_PATH):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._write(self._seed())

    def _seed(self) -> Dict[str, Any]:
        """Initial seed dataset."""
        now = _utc_ts()
        return {
            "users": [
                # Password hashes are set by auth layer if you want to recreate;
                # these are placeholders that will be overwritten by `seed_admin_if_missing`.
                {
                    "id": 1,
                    "name": "Admin",
                    "email": "admin@mobike.local",
                    "password_hash": "",
                    "is_admin": True,
                    "created_at": now,
                },
                {
                    "id": 2,
                    "name": "Demo User",
                    "email": "user@mobike.local",
                    "password_hash": "",
                    "is_admin": False,
                    "created_at": now,
                },
            ],
            "bikes": [
                {
                    "id": 1,
                    "name": "Ocean Rider",
                    "model": "City 1",
                    "location": "Campus Gate",
                    "rate_per_hour": 20.0,
                    "is_available": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": 2,
                    "name": "Blue Sprint",
                    "model": "Road 2",
                    "location": "Library",
                    "rate_per_hour": 25.0,
                    "is_available": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": 3,
                    "name": "Harbor Cruiser",
                    "model": "Hybrid 3",
                    "location": "Hostel Block A",
                    "rate_per_hour": 18.0,
                    "is_available": True,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
            "rentals": [],
        }

    def _read(self) -> Dict[str, Any]:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def get_all(self) -> Dict[str, Any]:
        """Return full dataset (copy)."""
        with self._lock:
            return self._read()

    def update_all(self, data: Dict[str, Any]) -> None:
        """Overwrite dataset."""
        with self._lock:
            self._write(data)

    def next_id(self, collection: str) -> int:
        """Compute next ID for a collection."""
        data = self.get_all()
        items = data.get(collection, [])
        if not items:
            return 1
        return max(int(x.get("id", 0)) for x in items) + 1

    def find_one(self, collection: str, **filters: Any) -> Optional[Dict[str, Any]]:
        """Find first item matching filters."""
        data = self.get_all()
        for item in data.get(collection, []):
            ok = True
            for k, v in filters.items():
                if item.get(k) != v:
                    ok = False
                    break
            if ok:
                return item
        return None

    def list(self, collection: str, **filters: Any) -> List[Dict[str, Any]]:
        """List items optionally filtered."""
        data = self.get_all()
        items = list(data.get(collection, []))
        if not filters:
            return items
        out: List[Dict[str, Any]] = []
        for item in items:
            ok = True
            for k, v in filters.items():
                if item.get(k) != v:
                    ok = False
                    break
            if ok:
                out.append(item)
        return out
