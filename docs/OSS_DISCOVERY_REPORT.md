# OSS_DISCOVERY_REPORT

Master Spec v3.1 §60 / RESTORE-10A 산출물. 조사일: 2026-07 (이 세션).
방법: 시드 리스트 전수 + 웹/GitHub/논문 추가 탐색. 각 후보는 README가 아니라
LICENSE/model license/활동성/추론·학습 코드를 가능한 범위에서 직접 확인했다.

상태 어휘: USE_DIRECTLY / USE_THROUGH_ADAPTER / BENCHMARK_ONLY /
REFERENCE_ARCHITECTURE / DO_NOT_USE / REVIEW_REQUIRED

---

## 1. 시드 리스트 감사 결과

| OSS | 코드 라이선스 | 모델/데이터 라이선스 | 활동성 | 권고 | 비고 |
|---|---|---|---|---|---|
| PaddleOCR | Apache-2.0 | 모델은 repo별 확인 필요 | 매우 활발 | **USE_THROUGH_ADAPTER** | 한국어 지원, PP-StructureV3, PaddleOCR-VL 최신. OCR/layout/formula 후보 |
| HTSNet | **LICENSE 파일 없음** | 학습 데이터(IAM/PRImA)는 각각 별도 조건 | 저활동(65커밋, python3.6) | **REFERENCE_ARCHITECTURE** | 겹침 픽셀 분류 + 합성법이 우리 LayerDNA와 개념 일치. 코드 재사용 불가(무저작권 표시=저작권 유보) |
| OpenCV | Apache-2.0 | — | 매우 활발 | **USE_DIRECTLY** | deskew/registration/CC/geometry 기본 부품 |
| SymPy | BSD | — | 매우 활발 | **USE_DIRECTLY** | SolveDNA deterministic 검증기 |
| Docling | MIT | 모델별 확인 필요 | 활발 | **BENCHMARK_ONLY** | 문서 구조/reading order 비교축 |
| Surya | 코드 Apache-2.0 | **수정 OpenRAIL-M: 연매출 $5M+/펀딩 $5M+/경쟁 서비스 금지** | 활발(21.4k★) | **BENCHMARK_ONLY** | 상용 제품에는 모델 라이선스 위험. 벤치 기준선으로만 |
| MinerU | Apache-2.0 + 추가조건(MAU 1억/매출 $20M 초과 시 별도 라이선스 + 온라인 표시 의무) | 모델별 확인 필요. **내부 의존 PDF-Extract-Kit은 GPL-3** | 매우 활발(80k★) | **BENCHMARK_ONLY / REVIEW_REQUIRED** | GPL-3 의존성은 production 배포 시 copyleft 위험. adapter 격리 필수 |
| UniMERNet | Apache-2.0 | UniMER-1M/UniMER-Test 공개. 학습 코드 공개(2024-09) | 활발 | **USE_THROUGH_ADAPTER** | Math OCR 1순위 벤치 후보. CDM metric 포함 |
| Pix2Text | 코드 MIT | **pix2text-mfr 모델 repo에 LICENSE 없음 → REVIEW_REQUIRED** | 활동 유지 | **BENCHMARK_ONLY** | 텍스트+수식 혼합 인식. 가중치 라이선스 확정 전 production 금지 |
| MathOCR | MIT | 엔진별 상이 | 저활동 | **REFERENCE_ARCHITECTURE** | 다중 엔진(pix2tex/RapidLaTeXOCR) 전략 참고 |
| GeoS | Apache-2.0 | 구형 데이터 | 중지 | **REFERENCE_ARCHITECTURE** | diagram→graph→solver 연결 구조의 원조 |
| Wiedergutmachung | MIT | 합성 데이터 생성법이 핵심 | 중지 | **REFERENCE_ARCHITECTURE** | pixel-wise GT 합성법 → 자체 synthetic corpus 설계에 반영 |
| DocTr++ (THE-FLIER/doctr) | MIT | 사전학습 가중치는 HF 조건 확인 필요 | 보통 | **BENCHMARK_ONLY** | dewarping/rectification 비교축 |
| python-hwpx | Apache-2.0 | — | 활동 | **REVIEW_REQUIRED → USE_THROUGH_ADAPTER 후보** | HWPX 생성/파싱. 우리 자체 renderer와 역할 비교 후 결정 |
| hwpx-plugins | Apache-2.0 | — | 활동 | **REFERENCE_ARCHITECTURE** | python-hwpx 생태계 참고 |

## 2. 추가 발견 후보 (시드 외)

### A. Handwriting/Print separation & overlap 복원

| OSS | 라이선스 | 권고 | 비고 |
|---|---|---|---|
| mahsavafaie/WGM | MIT | BENCHMARK_ONLY | pixel급 printed/handwritten 분리(FCNN+CRF). 구형이나 baseline으로 유효 |
| Jumpst3r/printed-hw-segmentation | MIT | BENCHMARK_ONLY | FCN+CRF, docker 배포형. ICDAR-WS 2019 |
| xuebinqin/DIS + ivanhe123/Handwriting-Removal-DIS | DIS: Apache-2.0 / 변형: MIT | REFERENCE_ARCHITECTURE | highly-accurate dichotomous segmentation을 필기 제거에 적용한 사례. 가중치는 HF 별도 확인 |
| miccunifi/DocWaveDiff | MIT | **BENCHMARK_ONLY (우선)** | predict-and-refine diffusion으로 deblur/inpainting/필기제거 통합. 문서 복원 최신 축 |
| TextDoctor (arXiv 2503.04021) | 코드 공개 여부 확인 필요 | REFERENCE_ARCHITECTURE | patch pyramid diffusion으로 텍스트 요소 복원 |
| Uni-DocDiff (arXiv 2508.04055) | 코드 확인 필요 | REFERENCE_ARCHITECTURE | task-prompt 통합 문서 복원 |
| GSDM text inpainting (arXiv 2401.14832) | 코드 공개 표기 | REFERENCE_ARCHITECTURE | 구조-유도 텍스트 inpainting — generative라서 candidate 전용 정책 필요 |

### B. Math OCR

| OSS | 라이선스 | 권고 | 비고 |
|---|---|---|---|
| OleehyO/TexTeller | Apache-2.0 | **BENCHMARK_ONLY (우선)** | 80M pairs 학습, 스캔/손글씨/혼합 수식. UniMERNet과 직접 비교 대상 |
| LATTE (arXiv 2409.14201) | 확인 필요 | REFERENCE_ARCHITECTURE | delta-view 반복 정제 — damaged formula 복원 전략 참고 |
| MathNet (arXiv 2404.13667) | 확인 필요 | REFERENCE_ARCHITECTURE | LaTeX 정규화/canonical form — 우리 math_ast 검증에 유용 |
| pix2tex / RapidLaTeXOCR | MIT류 확인 필요 | BENCHMARK_ONLY | MathOCR이 이미 래핑하는 엔진군 |

### C. Geometry diagram → graph

| OSS | 라이선스 | 권고 | 비고 |
|---|---|---|---|
| mingliangzhang2018/PGDP | MIT | **BENCHMARK_ONLY (우선)** | PGDPNet: 최초 end-to-end 도형 파싱, PGDP5K(primitive+relation 주석). FigureGraph와 개념 거의 일치 |
| eternal8080/Geoparsing | **LICENSE 없음** | REFERENCE_ARCHITECTURE | ACL 최신, GDP-29K(평면+입체+손글씨 도형), SFT+RLVR. 라이선스 없어 코드/모델 사용 불가 |
| RuRuo0/GeoParser (FGeo-Parser) | LICENSE 없음 | REFERENCE_ARCHITECTURE | BLIP/T5 기반 diagram+text parsing → FormalGeo |
| FormalGeo/FormalGeo | **GPL-3** | DO_NOT_USE(production) | copyleft. 형식언어 설계 참고만 |
| NikhilSDate/FastGDPJEI | 확인 필요 | REFERENCE_ARCHITECTURE | 경량 rule 기반 도형 파서 — 로컬 deterministic 후보 |

### D. 한국어 문서 OCR / 시험지 파싱

| OSS | 라이선스 | 권고 | 비고 |
|---|---|---|---|
| DeepSeek-AI/DeepSeek-OCR | MIT | **BENCHMARK_ONLY (강력 후보)** | vLLM 지원, 97% @10x 압축. 한국어 성능은 벤치 필요 |
| allenai/olmOCR | Apache-2.0 | BENCHMARK_ONLY | olmOCR 2 = 82.3 벤치 최상위권. 7B VLM — GPU 필요 |
| posicube-services/KolmOCR | Apache-2.0(코드) | **BENCHMARK_ONLY (한국어 우선)** | olmOCR 한국어 최적화 + 한국어 벤치마크 동봉. 가중치 조건 별도 확인 |
| datalab-to/chandra | 코드 Apache-2.0 / 가중치 OpenRAIL-M(<$2M) | REVIEW_REQUIRED | 상용 제한 — 벤치 전용 |
| ONTHEIT-AI/BizOnAI-OCR | Apache-2.0 | BENCHMARK_ONLY | 한국 공문서 특화, KDoc-OCRBench 제공 |
| d3vksy/ExamSplitter | MIT | REFERENCE_ARCHITECTURE | 수능/모의고사 문제 영역 YOLOv8 검출 — 한국 시험지 layout 실증 |
| zeetee1235/DocStruct | 확인 필요 | REFERENCE_ARCHITECTURE | parser+OCR 이중트랙 융합, 한글 정규화 — 우리 consensus와 유사 구조 |

## 3. 네 가지 심층 영역 결론

1. **겹침 분리/복원**: production급 ready-made는 없다. HTSNet(무 라이선스)과
   Wiedergutmachung(MIT)의 **합성법**을 우리 synthetic corpus에 흡수하고,
   DocWaveDiff(MIT)를 inpainting 계열 벤치 축으로 둔다. 단, generative
   결과는 항상 candidate — 절대규칙 유지.
2. **손상 수식 인식**: UniMERNet(Apache-2.0, 학습코드 공개)을 1순위 adapter
   후보로, TexTeller를 비교축으로. LATTE의 iterative refinement는
   MathDNA 단계 아이디어로 채택.
3. **도형→semantic graph**: PGDP(MIT, PGDP5K)가 FigureGraph와 가장 가까운
   공개 구현. Geoparsing은 라이선스 없어 참고만.
4. **한국어 시험지 parsing**: PaddleOCR(Apache-2.0)이 baseline adapter로
   유력. KolmOCR/olmOCR/DeepSeek-OCR을 벤치 비교축으로.
   ExamSplitter에서 한국 시험지 문제 영역 검출 실증 참고.

## 4. 라이선스 위험 요약

- **Surya / Chandra 가중치**: 수정 OpenRAIL-M — 매출·펀딩·경쟁 조건.
  상용 production 부품으로 사용 금지, 벤치만.
- **MinerU 내부 PDF-Extract-Kit = GPL-3**: MinerU 채택 시 구성요소 감사 필수.
- **FormalGeo GPL-3, Geoparsing·GeoParser·pix2text-mfr 무 라이선스**:
  production 사용 불가, 아키텍처 참고만.
- **HTSNet 무 라이선스**: 코드 재사용 불가. 합성 아이디어만.
- 각 후보의 **모델 가중치 라이선스는 코드와 별도** — registry에 분리 기록.

## 5. 후속

벤치마크 프레임워크(RESTORE-10B)에서 실제 fixture로 측정한 뒤
USE_THROUGH_ADAPTER 승격 여부를 결정한다. 발견≠채택(§34).
