"""Lazy read-only cache. No request can select a source path or mutate edges."""
from pathlib import Path
import threading
from .loader import load_osm, to_geojson
from .context import load_context


class NetworkStore:
    def __init__(self, source):
        self.source = Path(source)
        self._signature = None
        self._network = None
        self._context = None
        self._geojson = None
        self._lock = threading.Lock()

    def get(self, resource="network"):
        with self._lock:
            stat = self.source.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature != self._signature:
                network = load_osm(self.source)
                self._network = network
                self._geojson = None
                self._context = None
                self._signature = signature
            if resource == "context":
                if self._context is None:
                    self._context = load_context(self.source)
                return self._context
            if resource == "metadata":
                return self._network["metadata"]
            if resource == "geojson":
                if self._geojson is None:
                    self._geojson = to_geojson(self._network)
                return self._geojson
            return self._network
