from __future__ import annotations

from jobs.models import JobState
from . import export_verification, preprocessing, rendering
from .context import PipelineContext, StageFn
from .print_layer import engine as print_layer_engine
from .reconstruction import engine as reconstruction_engine
from .recognition import runner as recognition_runner
from .recognition import segmenter
from .source_truth import consensus
from .student_trace import separator
from .verification import logic, solving
from .zero_typo_gate import gate

STAGES: list[tuple[JobState, str, StageFn]] = [
    (JobState.PREPROCESSING, "preprocessing", preprocessing.run),
    (JobState.SEPARATING_TRACES, "student_trace", separator.run),
    (JobState.RESTORING_PRINT, "print_layer", print_layer_engine.run),
    (JobState.RESTORING_PRINT, "reconstruction", reconstruction_engine.run),
    (JobState.RECOGNIZING, "segmentation", segmenter.run),
    (JobState.RECOGNIZING, "recognition", recognition_runner.run),
    (JobState.VERIFYING_SOURCE, "source_verification", consensus.run),
    (JobState.VERIFYING_LOGIC, "logic_verification", logic.run),
    (JobState.SOLVING, "solving", solving.run),
    (JobState.RENDERING, "rendering", rendering.run),
    (JobState.VERIFYING_EXPORT, "export_verification", export_verification.run),
    (JobState.COMPLETED, "zero_typo_gate", gate.run),
]
