# OSS_DEPENDENCY_REGISTRY

Master Spec v3.1 §61 산출물. Last Verified: 2026-07 (이 세션).
필드: Name, GitHub, Purpose, ExamDNA Module, Version/Commit, Code License,
Model License, Dataset License, Commercial Status, Local, GPU, Korean,
Math, Status.

| Name | GitHub | Purpose | ExamDNA Module | Code License | Model License | Dataset License | Commercial | Local | GPU | Korean | Math | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PaddleOCR | PaddlePaddle/PaddleOCR | 한국어 OCR·layout·formula 후보 | ReadDNA | Apache-2.0 | repo별 확인 필요 | 내장 데이터셋 다수 | 허용(모델별 확인) | O | 권장 | O | △(PP-FormulaNet) | USE_THROUGH_ADAPTER |
| EasyOCR | JaidedAI/EasyOCR | 독립 OCR 관찰자(CRAFT+CRNN, 한국어) | ReadDNA | Apache-2.0 | Apache-2.0 | 자체 모델 | 코드 Apache-2.0, 가중치는 repo 라이선스 재확인 필요 | O | 권장 | O | — | USE_THROUGH_ADAPTER |
| OpenCV | opencv/opencv | deskew/CC/geometry | Preprocessing | Apache-2.0 | — | — | 허용 | O | 불필요 | — | — | USE_DIRECTLY |
| SymPy | sympy/sympy | symbolic 검증·답 대조 | SolveDNA | BSD | — | — | 허용 | O | 불필요 | — | O | USE_DIRECTLY |
| UniMERNet | opendatalab/UniMERNet | 수식→LaTeX | MathDNA | Apache-2.0 | Apache-2.0 (repo 동일) | UniMER-1M 공개 | 허용 | O | 권장 | △ | O | USE_THROUGH_ADAPTER |
| Pix2Text | breezedeus/Pix2Text | 텍스트+수식 혼합 인식 | MathDNA | MIT | **mfr repo 무 라이선스** | — | **보류** | O | 권장 | △ | O | BENCHMARK_ONLY |
| TexTeller | OleehyO/TexTeller | 수식→LaTeX (80M pairs) | MathDNA | Apache-2.0 | Apache-2.0 | 공개 데이터 조합 | 허용(가중치 조건 재확인) | O | 필요 | △ | O | BENCHMARK_ONLY |
| Docling | docling-project/docling | 문서 구조화 비교축 | RegionDNA bench | MIT | 모델별 확인 | — | 허용 | O | 권장 | △ | △ | BENCHMARK_ONLY |
| MinerU | opendatalab/MinerU | 문서 파싱 비교축 | ReadDNA bench | Apache-2.0+추가조건 | 모델별 확인 | — | 조건부(MAU/매출) + **PDF-Extract-Kit GPL-3 주의** | O | 필요 | △ | O | BENCHMARK_ONLY |
| Surya | datalab-to/surya | 다언어 OCR 벤치축 | ReadDNA bench | Apache-2.0 | **수정 OpenRAIL-M ($5M 조건)** | — | **벤치 외 불가** | O | 필요 | O | △ | BENCHMARK_ONLY |
| Chandra | datalab-to/chandra | VLM OCR 벤치축 | ReadDNA bench | Apache-2.0 | 수정 OpenRAIL-M ($2M 조건) | — | **벤치 외 불가** | O | 필요 | △ | O | REVIEW_REQUIRED |
| olmOCR | allenai/olmocr | VLM OCR 벤치축 | ReadDNA bench | Apache-2.0 | Apache-2.0계열 확인 | olmOCR-mix | 허용 | O | 필요(7B) | △ | O | BENCHMARK_ONLY |
| KolmOCR | posicube-services/KolmOCR | 한국어 VLM OCR | ReadDNA bench | Apache-2.0 | 가중치 조건 별도 확인 | — | 조건부 | O | 필요 | O | △ | BENCHMARK_ONLY |
| DeepSeek-OCR | DeepSeek-AI/DeepSeek-OCR | OCR 압축 VLM | ReadDNA bench | MIT | MIT | — | 허용 | O(vLLM) | 필요 | △ | △ | BENCHMARK_ONLY |
| BizOnAI-OCR | ONTHEIT-AI/BizOnAI-OCR | 한국어 공문서 OCR | ReadDNA bench | Apache-2.0 | 확인 필요 | KDoc-OCRBench | 허용 | O | 필요 | O | X | BENCHMARK_ONLY |
| ExamSplitter | d3vksy/ExamSplitter | 한국 시험지 문제 영역 검출 | RegionDNA | MIT | YOLOv8(Ultralytics AGPL 주의) | — | 검토 필요 | O | 권장 | O | — | REFERENCE_ARCHITECTURE |
| DocWaveDiff | miccunifi/DocWaveDiff | 문서 복원·필기 제거 | LayerDNA bench | MIT | MIT | 합성 | 허용 | O | 필요 | — | — | BENCHMARK_ONLY |
| DocTr++ | THE-FLIER/doctr | dewarping | Preprocessing bench | MIT | HF 가중치 확인 | — | 허용 | O | 필요 | — | — | BENCHMARK_ONLY |
| WGM | mahsavafaie/WGM | printed/handwritten 분리 | LayerDNA bench | MIT | MIT | — | 허용 | O | 권장 | — | — | BENCHMARK_ONLY |
| printed-hw-segmentation | Jumpst3r/printed-hw-segmentation | P/H 분리 | LayerDNA bench | MIT | MIT | — | 허용 | O | 불필요 | — | — | BENCHMARK_ONLY |
| DIS (+HW-Removal) | xuebinqin/DIS | 분할 기반 필기 제거 | LayerDNA | Apache-2.0 | HF 가중치 확인 | HandwritingSegmentationDataset | 허용(가중치 확인) | O | 필요 | — | — | REFERENCE_ARCHITECTURE |
| HTSNet | jottue/HTSNet | 겹침 P/H 픽셀 분류 | LayerDNA | **무 라이선스** | — | IAM/PRImA 별도 | **불가** | O | — | — | — | REFERENCE_ARCHITECTURE |
| Wiedergutmachung | ISE-FIZKarlsruhe/Wiedergutmachung | P/H 분리 합성 데이터 | Synthetic corpus | MIT | — | 합성 생성 | 허용 | O | — | — | — | REFERENCE_ARCHITECTURE |
| PGDP | mingliangzhang2018/PGDP | 도형 primitive+relation 파싱 | FigureDNA bench | MIT | MIT | PGDP5K | 허용 | O | 권장 | — | O | BENCHMARK_ONLY |
| Geoparsing | eternal8080/Geoparsing | 평면+입체 도형 파싱 | FigureDNA | **무 라이선스** | 무 라이선스 | GDP-29K | **불가** | O | 필요 | — | O | REFERENCE_ARCHITECTURE |
| GeoParser | RuRuo0/GeoParser | 도형+텍스트 파싱 | FigureDNA | 무 라이선스 | 무 라이선스 | FormalGeo7K-v2 | **불가** | O | 필요 | — | O | REFERENCE_ARCHITECTURE |
| GeoS | seominjoon/geosolver | 도형→그래프→solver 구조 | FigureDNA | Apache-2.0 | — | — | 허용 | O | — | — | O | REFERENCE_ARCHITECTURE |
| FormalGeo | FormalGeo/FormalGeo | 기하 형식언어 | FigureDNA | **GPL-3** | — | — | **copyleft — production 불가** | O | — | — | O | DO_NOT_USE |
| MathOCR | ChristosBouronikos/MathOCR | 다중 수식 엔진 전략 | MathDNA | MIT | 엔진별 상이 | — | 허용 | O | 권장 | — | O | REFERENCE_ARCHITECTURE |
| python-hwpx | airmang/python-hwpx | HWPX 생성/파싱 | Document Engine | Apache-2.0 | — | — | 허용 | O | 불필요 | O | O | REVIEW_REQUIRED |
| hwpx-plugins | airmang/hwpx-plugins | HWPX 플러그인 참고 | Document Engine | Apache-2.0 | — | — | 허용 | O | 불필요 | O | — | REFERENCE_ARCHITECTURE |
| DocStruct | zeetee1235/DocStruct | parser+OCR 융합 구조 | ReadDNA | 확인 필요 | — | — | 확인 필요 | O | — | O | — | REFERENCE_ARCHITECTURE |
| TextDoctor | (arXiv 2503.04021) | 텍스트 inpainting | LayerDNA | 코드 확인 필요 | — | 7개 공개 데이터셋 | 확인 필요 | — | 필요 | — | — | REFERENCE_ARCHITECTURE |
| Uni-DocDiff | (arXiv 2508.04055) | 통합 문서 복원 | LayerDNA | 코드 확인 필요 | — | — | 확인 필요 | — | 필요 | — | — | REFERENCE_ARCHITECTURE |
| LATTE | (arXiv 2409.14201) | LaTeX 반복 정제 | MathDNA | 코드 확인 필요 | — | — | 확인 필요 | — | 필요 | — | O | REFERENCE_ARCHITECTURE |
| FastGDP | NikhilSDate/FastGDPJEI | 경량 도형 파서 | FigureDNA | 확인 필요 | — | 포함 | 확인 필요 | O | 불필요 | — | O | REFERENCE_ARCHITECTURE |

## 운영 규칙

- Status가 BENCHMARK_ONLY 이하인 항목은 production dependency로 추가하지 않는다.
- 모델 가중치 라이선스 미확인 = REVIEW_REQUIRED 이상 승격 불가.
- 채택 절차(§65): Candidate 등록 → License audit → Isolated Adapter →
  Same Fixture Benchmark → 기존 후보 비교 → Decision.
- GPL/AGPL 계열(PDF-Extract-Kit, FormalGeo, Ultralytics)은 production
  경로에서 배제하거나 격리 법적 검토 후 결정한다.
