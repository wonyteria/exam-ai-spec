from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from document.models import Answer, Document, Equation, Question, Solution, TextSpan
from renderers.hwp.worker import WindowsHWPWorker
from renderers.hwpx import render_hwpx


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "data" / "wp08_proof"
    out.mkdir(parents=True, exist_ok=True)
    doc = Document(tenant_id="wp08-proof-tenant")
    doc.questions.append(
        Question(
            number=1,
            label="1",
            points=4,
            body=[TextSpan(text="WP08 proof 본문")],
            answer=Answer(value="2"),
            solution=Solution(steps=[TextSpan(text="풀이")]),
            equations=[Equation(latex="x^2=4", hwp_formula="x^{2} = 4")],
        )
    )
    hwpx = out / "proof_input.hwpx"
    hwpx.write_bytes(render_hwpx(doc))
    hwp = out / "proof_output.hwp"
    pdf = out / "proof_output.pdf"
    proof = WindowsHWPWorker().convert_with_proof(
        hwpx, hwp, pdf, request_revision="wp08-proof-revision"
    )
    manifest = {
        "tenant_id": doc.tenant_id,
        "request_revision": "wp08-proof-revision",
        "steps": proof.get("step_returns", {}),
        "checks": proof.get("checks", {}),
        "files": {
            "hwpx": {"path": str(hwpx), "sha256": _sha(hwpx), "bytes": hwpx.stat().st_size},
            "hwp": {"path": str(hwp), "sha256": _sha(hwp), "bytes": hwp.stat().st_size},
            "pdf": {"path": str(pdf), "sha256": _sha(pdf), "bytes": pdf.stat().st_size},
        },
        "proof": proof,
    }
    mf = out / "proof_manifest.json"
    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(mf))


if __name__ == "__main__":
    main()
