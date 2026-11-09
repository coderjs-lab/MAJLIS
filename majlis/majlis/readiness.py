"""ITU AI-readiness dimensions and an illustrative causal propagation.

Sources (read, not copied by hand):
  - ../simulation/data/framework/dimensions.json   (the 13 dimensions)
  - ../simulation/server/game/causal_graph.py      (the `_CAUSAL_EDGES` list)

Both come from the team's AI Readiness simulation reference model (MIT licence,
attribution retained). Importing causal_graph.py would pull in its server
package (`server.models`), so the edge list is parsed from the source with
`ast` instead; no code from that file is executed.

`propagate` mirrors the reference model's rule: effect on a successor =
delta * edge_weight * decay**hop, hops limited by `depth`, effects below 0.01
dropped. It is illustrative, not a measurement.
"""
from __future__ import annotations

import ast
import json
from functools import lru_cache
from pathlib import Path

SIM_ROOT = Path(__file__).resolve().parents[2] / "simulation"
DIMENSIONS_FILE = SIM_ROOT / "data" / "framework" / "dimensions.json"
CAUSAL_GRAPH_FILE = SIM_ROOT / "server" / "game" / "causal_graph.py"
DECAY = 0.5
MIN_EFFECT = 0.01


@lru_cache(maxsize=1)
def _dimensions() -> list[dict]:
    return json.loads(DIMENSIONS_FILE.read_text(encoding="utf-8"))["dimensions"]


def dimension_names() -> dict[int, str]:
    """{1: 'Data/Model Marketplace', ..., 13: 'Digital Infrastructure'}"""
    return {int(d["id"]): d["name"] for d in _dimensions()}


def dimension_short_names() -> dict[int, str]:
    return {int(d["id"]): d["short_name"] for d in _dimensions()}


@lru_cache(maxsize=1)
def edges() -> tuple[tuple[int, int, float], ...]:
    """(source, target, weight) parsed from `_CAUSAL_EDGES` in the reference model."""
    tree = ast.parse(CAUSAL_GRAPH_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target == "_CAUSAL_EDGES" and node.value is not None:
            return tuple((int(s), int(t), float(w)) for s, t, w in ast.literal_eval(node.value))
    raise ValueError(f"_CAUSAL_EDGES not found in {CAUSAL_GRAPH_FILE}")


def propagate(dim_id: int, delta: float = 1.0, depth: int = 2) -> dict[int, float]:
    """Accumulated effect of changing one dimension by `delta`, including the
    dimension itself. Values rounded to 3 decimals."""
    succ: dict[int, list[tuple[int, float]]] = {}
    for s, t, w in edges():
        succ.setdefault(s, []).append((t, w))
    accumulated = {dim_id: delta}
    frontier = {dim_id: delta}
    for hop in range(depth):
        nxt: dict[int, float] = {}
        for d, v in frontier.items():
            for t, w in succ.get(d, []):
                effect = v * w * (DECAY ** hop)
                if abs(effect) >= MIN_EFFECT:
                    nxt[t] = nxt.get(t, 0.0) + effect
        if not nxt:
            break
        for d, v in nxt.items():
            accumulated[d] = accumulated.get(d, 0.0) + v
        frontier = nxt
    return {d: round(v, 3) for d, v in accumulated.items()}
