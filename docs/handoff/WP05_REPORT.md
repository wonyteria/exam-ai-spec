# WP05 Report — 수식 AST·도형 scene·표/그래프 객체

Date: 2026-09-21
Commit base: WP04 `00ecbb1`

## Scope delivered

### Math AST + HWP equation script (`backend/document/math_ast.py`)

- `MNode` AST: `num|var|unit|op|sym|text|frac|sqrt|root|sup|sub|supsub|
  paren|seq`, each carrying a `style` token (`it`/`rm`).
- **Style contract (REQ-08)**: numbers and variables emit italic
  (HWP math default); units and literal text wrap in `rm{...}` —
  `3 cm` → `3 rm{cm}`, `5 \mathrm{kg}` → `rm{kg}`. Unit heuristic:
  multi-char unit words (`cm`, `kg`, …) always unit; single letters
  (`m`, `g`) only after a number/`)` — `l \perp m` keeps `m` a
  variable. Hangul literals are roman text; Korean units (원, 개, 명…)
  are in the unit set.
- **11pt**: `latex_to_hwp` always returns `baseUnit=1100`
  (`HWP_BASE_UNIT_11PT`) — validated live against HWP 2020 in the WP00
  tech check (`<hp:equation baseUnit="1100">`).
- Supported: `+ − × ÷ ± = < > ≤ ≥ ≠ ≈`, `frac`, `sqrt`, `root[n]`,
  `^`, `_` (incl. `x^2_i` → `supsub`), `overline`, `left/right`,
  `pi`, greek letters, `angle`, `triangle`, `parallel`, `perp`,
  `circ→deg`, `%`, primes, arrows, `mathrm/text/operatorname`.
- `MathParseError`/`UnsupportedMathError` — matrices, integrals,
  vectors, unknown commands fail loudly; never silent garbage (S04).

### Figure scene / table / graph (`backend/document/scene.py`)

- `FigureScene` — data-only primitives (`point`, `segment`, `line`,
  `ray`, `polyline`, `arc`, `circle`, `polygon`, `angle_mark`,
  `right_angle_mark`, `parallel_mark`, `equal_mark`, `label`, `axis`,
  `tick`) + relations (`right_angle`, `parallel`, `perpendicular`,
  `equal_length`, `equal_angle`, `on_line`, `on_circle`, `congruent`,
  `midpoint`). Model output is **never executed**.
- `validate_scene` rejects: unknown primitive/relation kinds, dangling
  refs (primitives, relations, labels), under-referenced strokes,
  duplicate ids, non-finite/out-of-range coords (NaN/inf/1e9), oversized
  payloads (200 primitives / 100 relations / 200-char labels / 1e6
  coord cap).
- `Table` — rectangularity + header required + size cap.
- `Graph` — axis ticks strictly increasing and finite, min<max,
  series points finite `[x,y]`.
- `Figure` gains typed `scene`/`table`/`graph` payloads (Optional;
  legacy `topology` dict stays for backward compatibility — revision
  JSON is additive-safe).

### Canonical integration (`canonical/service.py`)

- `_normalize_math(doc)` — runs in **both** revision paths
  (`create_revision`, `apply`): coerces raw dicts into `Equation`
  objects (a `SetField` op assigning `[{"latex": ...}]` produces real
  typed objects) and derives `hwp_formula` from `latex` when absent.
  Parse failures stay unset — the checker flags them.
- `MATH_FIGURE_SEMANTIC_CONSISTENCY` implemented in `_run_one`:
  - every equation's `latex` must parse **and** serialize to HWP script;
  - every `scene`/`table`/`graph` must validate;
  - declared `relations` without a `scene` to bind them → error
    (불완전 조건);
  - a figure with neither `source` nor `atu_ids` → provenance error
    (same contract as `SOURCE_REGION_COVERAGE` — figures are not
    self-verifying);
  - failures produce FAILED + blocking issue via `_flag_check_issue`.

### Equation-object editing

- `SetField(target_id=<qid>, field="equations", value=[{...}])` replaces
  equation objects atomically under If-Match CAS; the new revision
  re-derives `hwp_formula` (`x^2 = 9` → `x^{2} = 9`).

## Evidence (backend `pytest tests` — 111 passed)

`tests/test_wp05.py` (31 tests):

- `test_base_unit_is_11pt` — `baseUnit == 1100` on every conversion.
- `test_latex_to_hwp_script` (17 cases) — frac, sqrt/root, sup/sub,
  supsub, TIMES, ≤, ≠, angl, tri, paral, perp, deg, overbar.
- `test_numbers_italic_units_roman` — `3 rm{cm}`; num `it`, unit `rm`.
- `test_hangul_text_is_roman` — `3 원` → `3 rm{원}`.
- `test_unsupported_constructs_fail_loudly` — matrix, integral, vec,
  unknown cmd, empty, unbalanced → errors.
- `test_valid_scene_passes` — right-triangle scene (points, segments,
  right_angle_mark, relations, labels) valid.
- `test_scene_rejects_*` — unknown kind, dangling refs (relation +
  label), NaN/inf/out-of-range coords, 500-primitive flood, short
  stroke refs, duplicate ids.
- `test_table_and_graph_validation` — header/rectangularity, monotone
  ticks, finite series points.
- `test_math_figure_check_passes` — PASSED + `hwp_formula` materialized
  in the stored revision.
- `test_invalid_equation_fails_and_blocks` — unsupported LaTeX →
  FAILED + blocking issue.
- `test_figure_without_source_evidence_fails` — provenance gate.
- `test_declared_relations_without_scene_fail` — incomplete geometry →
  FAILED ("no scene").
- `test_malicious_scene_rejected_by_check` — NaN + dangling refs →
  FAILED + blocking issue.
- `test_equation_object_edit_creates_revision` — SetField edit → rev2,
  real Equation objects, re-derived formula, content_hash changed.

Full suite: **111 passed** (was 80 after WP04; +31 WP05).

## Boundaries / pending

- `CURRICULUM_COMPLIANCE`, `REQUIRED_CONTENT_COVERAGE`,
  `ORIGINAL_SOURCE_FIDELITY` remain NOT_RUN (need WP06 review data /
  source-region extraction depth).
- Scene extraction from pixels is not implemented — figures today are
  validated when a scene exists; scene *production* is pipeline work
  with the vision provider (shape → scene graph).
- HWP equation script coverage is a deliberate subset; unsupported
  constructs fail loudly into issues rather than approximating.
- `hwp_formula` is the stored script; embedding `hp:equation` with
  `baseUnit=1100` into a real HWPX is WP07/WP08 renderer work.
