"""Inverse coordinate mapping — working space back to source space."""
from __future__ import annotations

import math

import pytest
from PIL import Image, ImageOps

from core.examdna.spatial import map_bbox_to_source, map_point_to_source
from document.models import Page, PageImage, TransformStep


def _page(**kw) -> Page:
    return Page(index=0, original=PageImage(uri="/tmp/x.png"),
                width=kw.pop("w", 100), height=kw.pop("h", 200), **kw)


class TestScaleInverse:
    def test_normalize_scale_roundtrip(self):
        p = _page(w=500, h=400)
        p.transform_chain.append(TransformStep(
            kind="normalize_scale",
            params={"scale": 0.5, "from_width": 1000,
                    "from_height": 800, "to_width": 500, "to_height": 400},
        ))
        sx, sy = map_point_to_source(p, 100, 50)
        assert (sx, sy) == (200.0, 100.0)

    def test_pdf_raster_inverse_to_pt(self):
        p = _page(w=1700, h=2200)
        p.transform_chain.append(TransformStep(
            kind="pdf_raster",
            params={"pdf_page_index": 0, "scale": 2.0, "applied": True},
        ))
        sx, sy = map_point_to_source(p, 340, 440)
        assert (sx, sy) == pytest.approx((170.0, 220.0))

    def test_empty_chain_is_identity(self):
        p = _page()
        assert map_point_to_source(p, 12, 34) == (12.0, 34.0)


class TestDeskewInverse:
    def test_deskew_variant_point_undoes_rotation(self):
        p = _page(w=200, h=200)
        p.transform_chain.append(TransformStep(
            kind="deskew", params={"angle_deg": 10.0, "variant": "deskewed"},
        ))
        # A point at working-center must stay at center under any rotation.
        assert map_point_to_source(p, 100, 100, "deskewed") == pytest.approx(
            (100.0, 100.0)
        )
        # Forward-rotate a known point with the cv2 convention, then
        # invert — must land back on the original.
        from core.examdna.spatial import _rotate_cv

        fx, fy = _rotate_cv(60, 30, 100, 100, 10.0)
        assert map_point_to_source(p, fx, fy, "deskewed") == pytest.approx(
            (60.0, 30.0)
        )

    def test_deskew_not_applied_to_other_variants(self):
        p = _page(w=200, h=200)
        p.transform_chain.append(TransformStep(
            kind="deskew", params={"angle_deg": 10.0, "variant": "deskewed"},
        ))
        assert map_point_to_source(p, 60, 30, "shadow_free") == (60.0, 30.0)


class TestExifInverse:
    """Verify formulas against PIL's own exif_transpose on a real image."""

    @pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
    def test_inverse_matches_pil_transpose(self, orientation):
        # Distinct pixels at known source coords.
        src = Image.new("RGB", (7, 4))
        px = src.load()
        probes = [(0, 0), (6, 0), (0, 3), (6, 3), (3, 1)]
        for i, (x, y) in enumerate(probes):
            px[x, y] = (10 + i, 50 + i, 90 + i)

        # Forward through PIL: build the oriented image the same way
        # ImageOps.exif_transpose would for this orientation value.
        ops = {
            2: [Image.Transpose.FLIP_LEFT_RIGHT],
            3: [Image.Transpose.ROTATE_180],
            4: [Image.Transpose.FLIP_TOP_BOTTOM],
            5: [Image.Transpose.TRANSPOSE],
            6: [Image.Transpose.ROTATE_270],
            7: [Image.Transpose.TRANSVERSE],
            8: [Image.Transpose.ROTATE_90],
        }[orientation]
        oriented = src
        for op in ops:
            oriented = oriented.transpose(op)
        ow, oh = oriented.size

        # Locate each probe pixel in the oriented image by its color,
        # then check the inverse map returns the source coords.
        opx = oriented.load()
        page = _page(w=ow, h=oh)
        page.transform_chain.append(TransformStep(
            kind="exif_orientation",
            params={"exif_orientation": orientation,
                    "original_width": 7, "original_height": 4,
                    "axes_swapped": orientation >= 5,
                    "applied": True},
        ))
        for i, (x0, y0) in enumerate(probes):
            color = (10 + i, 50 + i, 90 + i)
            found = [
                (x, y) for y in range(oh) for x in range(ow)
                if opx[x, y] == color
            ]
            assert len(found) == 1
            assert map_point_to_source(page, *found[0]) == (x0, y0)


class TestBBoxAndChained:
    def test_bbox_inverse(self):
        p = _page(w=500, h=400)
        p.transform_chain.append(TransformStep(
            kind="normalize_scale",
            params={"scale": 0.5, "from_width": 1000,
                    "from_height": 800, "to_width": 500, "to_height": 400},
        ))
        assert map_bbox_to_source(p, [10, 20, 100, 60]) == [
            20.0, 40.0, 200.0, 120.0,
        ]

    def test_chained_scale_and_exif(self):
        # scale applied AFTER exif: reverse order undoes scale first.
        p = _page(w=350, h=200)
        p.transform_chain.extend([
            TransformStep(
                kind="exif_orientation",
                params={"exif_orientation": 6, "original_width": 400,
                        "original_height": 700, "axes_swapped": True,
                        "applied": True},
            ),
            TransformStep(
                kind="normalize_scale",
                params={"scale": 0.5, "from_width": 700,
                        "from_height": 400, "to_width": 350,
                        "to_height": 200},
            ),
        ])
        # working (175,100) -> pre-scale oriented (350,200) -> source
        # via orientation-6 inverse: (y, orig_h-1-x) = (200, 699-350)
        assert map_point_to_source(p, 175, 100) == (200.0, 349.0)
