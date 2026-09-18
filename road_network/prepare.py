"""Build derived artifacts and measure complete-file ingestion. No LNS calls."""
import argparse
import gc
import json
from pathlib import Path
import time
import tracemalloc
from .loader import load_osm, to_geojson


def prepare(source, output_dir):
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    outputs = [output_dir / name for name in ("network.json", "roads.geojson", "map_load_report.json")]
    if source.parent == output_dir or source in outputs:
        raise ValueError("Processed output must be separate from the raw source directory")
    network = load_osm(source)
    cold_seconds = network["metadata"]["load_seconds"]
    gc.collect()
    tracemalloc.start()
    measured = load_osm(source)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del measured
    geojson = to_geojson(network)
    output_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(network, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    started = time.perf_counter()
    outputs[0].write_text(serialized, encoding="utf-8")
    outputs[1].write_text(json.dumps(geojson, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    report = {"metadata": network["metadata"], "performance": {
        "uninstrumented_load_seconds": cold_seconds,
        "traced_retained_python_bytes": current, "traced_peak_python_bytes": peak,
        "measurement_scope": "Python allocations for an additional full parse/normalization; not whole-process RSS; OS file cache not flushed",
        "write_artifacts_seconds": time.perf_counter() - started,
        "network_json_bytes": outputs[0].stat().st_size, "geojson_bytes": outputs[1].stat().st_size,
    }, "example_node": next(iter(network["nodes"].values())), "example_edge": next(iter(network["edges"].values()))}
    outputs[2].write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-dir", default="data/processed")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output_dir), ensure_ascii=False, indent=2))
