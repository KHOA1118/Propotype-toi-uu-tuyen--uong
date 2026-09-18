"""One-time, reproducible extraction; preserves original function source verbatim."""
import ast
import hashlib
import pathlib
import sys

source_path = pathlib.Path(sys.argv[1])
source = source_path.read_text(encoding="utf-8-sig")
tree = ast.parse(source)
parts = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        parts.append(ast.get_source_segment(source, node))
        if node.name == "run_lns":
            break
    elif isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id in {"DESTROY_OPERATORS", "REPAIR_OPERATORS"}
        for target in node.targets
    ):
        parts.append(ast.get_source_segment(source, node))
header = '''"""Original LNS functions extracted verbatim from the user's Colab export.
Notebook setup, execution, plotting and reporting are intentionally excluded.
Use adapter.solve_mock() to initialize an isolated instance.
"""
import math
import random
import time
from collections import Counter
import numpy as np

DEPOT_ID = 0

'''
destination = pathlib.Path(__file__).resolve().parents[1] / "lns" / "core.py"
destination.parent.mkdir(exist_ok=True)
destination.write_text(header + "\n\n".join(parts) + "\n", encoding="utf-8")
print(f"Extracted {len(parts)} definitions. Source SHA256: {hashlib.sha256(source_path.read_bytes()).hexdigest()}")
