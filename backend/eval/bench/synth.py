"""Synthetic damage generator v0 (Master Spec §29, RESTORE-10B).

Renders a clean exam-ish page, then applies synthetic handwriting,
grading marks, and capture degradation — emitting the damaged image plus
pixel ground-truth masks (print / handwriting / grading / overlap) so
layer metrics (incl. PRINT_DESTRUCTION) are computable without manual
annotation.

This is internal research tooling: synthetic performance is never
reported as real-exam performance.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


@dataclass
class SynthSpec:
    """What to damage and how much."""
    width: int = 640
    height: int = 900
    n_text_lines: int = 12
    handwriting_strokes: int = 8
    grading_marks: int = 3
    rotate_deg: float = 0.6
    blur_radius: float = 0.6
    noise_sigma: float = 3.0
    seed: int = 0


@dataclass
class SynthResult:
    damaged: Image.Image
    clean: Image.Image
    masks: dict[str, np.ndarray] = field(default_factory=dict)


_STROKE_COLORS = {
    "pencil": (110, 110, 110),
    "dark_pen": (30, 30, 30),
    "red_pen": (200, 30, 30),
}


def _draw_clean(spec: SynthSpec, rng: random.Random) -> Image.Image:
    img = Image.new("RGB", (spec.width, spec.height), "white")
    d = ImageDraw.Draw(img)
    y = 60
    for i in range(spec.n_text_lines):
        x = 60
        w = rng.randint(120, spec.width - 160)
        d.rectangle([x, y, x + w, y + 12], fill=(0, 0, 0))
        y += rng.randint(48, 64)
        if y > spec.height - 80:
            break
    return img


def _stroke(draw: ImageDraw.ImageDraw, rng: random.Random, spec: SynthSpec,
            color, width: int = 3) -> None:
    """A wandering polyline stroke."""
    x = rng.randint(40, spec.width - 120)
    y = rng.randint(40, spec.height - 120)
    pts = [(x, y)]
    for _ in range(rng.randint(3, 7)):
        x += rng.randint(-60, 90)
        y += rng.randint(-25, 25)
        x = max(8, min(spec.width - 8, x))
        y = max(8, min(spec.height - 8, y))
        pts.append((x, y))
    draw.line(pts, fill=color, width=width, joint="curve")


def generate(spec: SynthSpec | None = None) -> SynthResult:
    spec = spec or SynthSpec()
    rng = random.Random(spec.seed)
    clean = _draw_clean(spec, rng)
    base = np.array(clean)
    print_mask = np.any(base < 128, axis=2)  # dark print pixels

    hand_img = Image.new("RGB", clean.size, "white")
    hd = ImageDraw.Draw(hand_img)
    for _ in range(spec.handwriting_strokes):
        color = _STROKE_COLORS[
            rng.choice(["pencil", "dark_pen", "dark_pen"])
        ]
        _stroke(hd, rng, spec, color)
    hand_mask = np.any(np.array(hand_img) < 245, axis=2)

    grad_img = Image.new("RGB", clean.size, "white")
    gd = ImageDraw.Draw(grad_img)
    for _ in range(spec.grading_marks):
        cx = rng.randint(60, spec.width - 100)
        cy = rng.randint(60, spec.height - 100)
        r = rng.randint(18, 42)
        if rng.random() < 0.5:
            gd.ellipse([cx - r, cy - r, cx + r, cy + r],
                       outline=(220, 0, 0), width=4)
        else:  # X mark
            gd.line([cx - r, cy - r, cx + r, cy + r], fill=(220, 0, 0), width=4)
            gd.line([cx + r, cy - r, cx - r, cy + r], fill=(220, 0, 0), width=4)
    grad_mask = np.any(np.array(grad_img) < 245, axis=2)

    damaged = np.array(clean).copy()
    damaged[hand_mask] = np.array(hand_img)[hand_mask]
    damaged[grad_mask] = np.array(grad_img)[grad_mask]
    img = Image.fromarray(damaged)

    # capture degradation
    if spec.rotate_deg:
        img = img.rotate(spec.rotate_deg, fillcolor="white")
    if spec.blur_radius:
        img = img.filter(ImageFilter.GaussianBlur(spec.blur_radius))
    if spec.noise_sigma:
        nprng = np.random.default_rng(spec.seed)
        arr = np.asarray(img, dtype=np.float32)
        arr += nprng.normal(0, spec.noise_sigma, arr.shape)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    overlap = (hand_mask | grad_mask) & print_mask
    return SynthResult(
        damaged=img,
        clean=clean,
        masks={
            "print": print_mask,
            "handwriting": hand_mask,
            "grading": grad_mask,
            "overlap": overlap,
        },
    )


def save_pair(result: SynthResult, out_dir: Path, name: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.damaged.save(out_dir / f"{name}_damaged.png")
    result.clean.save(out_dir / f"{name}_clean.png")
    for k, m in result.masks.items():
        Image.fromarray((m * 255).astype(np.uint8)).save(
            out_dir / f"{name}_mask_{k}.png"
        )
    return out_dir
