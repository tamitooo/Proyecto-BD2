"""Pure visual-contract tests; do not require FastAPI, IVF or any vector model."""
import json
import math

import pytest

from tools.generate_geometric_dataset import SHAPES, COLORS, render_shape


def test_squares_are_not_a_supported_shape():
    assert "cuadrado" not in SHAPES
    assert "rectangle" not in SHAPES
    with pytest.raises(ValueError):
        render_shape("cuadrado", "rojo", size=160, seed=1)


def test_tossed_board_has_independent_shapes_and_reproducible_label():
    for seed in range(40):
        primary = SHAPES[seed % len(SHAPES)]
        img, info = render_shape(primary, "azul", size=160, seed=seed)
        img2, info2 = render_shape(primary, "azul", size=160, seed=seed)
        assert img.size == (160, 160)
        assert img.tobytes() == img2.tobytes()
        assert info == info2
        objects = json.loads(info["escena_json"])
        assert 7 <= len(objects) <= 12
        assert len(objects) == info["n_formas"]
        assert info["n_dominantes"] > info["n_distractores"] >= 2
        assert sum(obj["figura"] == primary for obj in objects) == info["n_dominantes"]
        assert len({obj["figura"] for obj in objects}) >= 2
        assert not any(obj["figura"] == "cuadrado" for obj in objects)
        assert all(obj["color"] in COLORS for obj in objects)
        assert all(0 <= obj["angulo"] <= 360 for obj in objects)
        assert all(obj["radio"] > 0 for obj in objects)


def test_layout_is_scattered_not_aligned_to_a_lattice():
    images = [render_shape("estrella", "rojo", size=160, seed=s)[1] for s in range(50, 140)]
    scenes = [json.loads(meta["escena_json"]) for meta in images]
    xs = [o["x"] for scene in scenes for o in scene]
    ys = [o["y"] for scene in scenes for o in scene]
    radii = [o["radio"] for scene in scenes for o in scene]
    angles = [o["angulo"] for scene in scenes for o in scene]
    assert len(set(xs)) > 70 and len(set(ys)) > 70
    assert len(set(radii)) > 12 and len(set(angles)) > 200
    # Real spatial spread: centers appear on both sides of the canvas.
    assert min(xs) < 30 and max(xs) > 130
    assert min(ys) < 30 and max(ys) > 130


def test_dominant_label_not_forced_to_center():
    primaries = [render_shape("hexagono", "verde", size=160, seed=s)[1] for s in range(80)]
    assert len({(m["centro_x"], m["centro_y"]) for m in primaries}) >= 65
    assert any(math.hypot(m["centro_x"]-80,m["centro_y"]-80)>50 for m in primaries)
