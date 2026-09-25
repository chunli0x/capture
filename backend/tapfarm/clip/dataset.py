"""Builds the clip-judgment pools.

The ghost-overlay dataset renders its own images, so its truth is what it
rendered at. Clips cannot work that way: the answer to "phone or wallet?" comes
from whoever filmed or sourced the clip, so this module *partitions and records*
clips supplied to it rather than inventing them. The brief is explicit that a
video-generation pipeline is out of scope.

## Four pools, same reasoning as the pose campaign

- **practice** - unpaid training. Truth is released to the client so it can say
  "Correct." immediately. Practice clips are therefore a separate pool that
  never appears in qualification; if they overlapped, releasing practice truth
  would leak the blind set's answers.
- **qualify** - the blind set. Truth never leaves the server. Because a
  two-choice question has a chance floor, this pool must be large enough that
  luck does not clear it - see `scoring.chance_pass_probability`.
- **golden** - hidden known-answer clips mixed into paid work for drift
  detection, indistinguishable from live work to the labeler.
- **live** - stands in for real buyer work, with no truth to grade against.
  Its answers, where known at all, are written to a separate file that grading
  never opens.

Placeholder clips exist so the loop is runnable before real footage arrives.
They are labelled as placeholders in the manifest and must not reach a demo:
a synthetic card reading "PHONE" proves nothing about a task being hard for a
bot, and showing one to a judge while claiming otherwise is exactly the kind of
overclaim the rest of this repo is built to avoid.
"""

from __future__ import annotations

import json
import pathlib
import random
from dataclasses import asdict, dataclass

PRACTICE, QUALIFY, GOLDEN, LIVE = "practice", "qualify", "golden", "live"

TRUTH_FILE = "truth.jsonl"
LIVE_TRUTH_FILE = "live_truth.jsonl"
MANIFEST_FILE = "clips.jsonl"


@dataclass(frozen=True)
class ClipTaskRecord:
    """What may be sent to the client. Never the answer."""

    task_id: str
    pool: str
    clip: str
    question: str
    choices: list[str]
    placeholder: bool = False


@dataclass(frozen=True)
class SourceClip:
    """A clip plus its known answer, as supplied to the builder."""

    clip: str
    question: str
    choices: list[str]
    answer: str
    placeholder: bool = False

    def __post_init__(self) -> None:
        if self.answer not in self.choices:
            raise ValueError(
                f"answer {self.answer!r} is not one of the choices {self.choices!r}; "
                "a clip whose answer is unreachable would be ungradeable and would "
                "silently fail every labeler who saw it"
            )
        if len(set(self.choices)) != len(self.choices):
            raise ValueError(f"duplicate choices in {self.choices!r}")
        if len(self.choices) < 2:
            raise ValueError("a judgment needs at least two choices")


def build_clip_dataset(
    out_dir: pathlib.Path,
    clips: list[SourceClip],
    *,
    practice: int,
    qualify: int,
    golden: int,
    seed: int = 0,
) -> list[ClipTaskRecord]:
    """Partition clips into the four pools and write the manifest and truth.

    Pools are disjoint by construction - a clip is consumed by the first pool
    that takes it - because overlap between practice and qualify is the one
    failure that would quietly void the gate.
    """
    wanted = practice + qualify + golden
    if wanted > len(clips):
        raise ValueError(
            f"pools need {wanted} clips (practice {practice} + qualify {qualify} + "
            f"golden {golden}) but only {len(clips)} were supplied"
        )

    rng = random.Random(seed)
    shuffled = list(clips)
    rng.shuffle(shuffled)

    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[ClipTaskRecord] = []
    truth: dict[str, str] = {}
    live_truth: dict[str, str] = {}

    cursor = 0
    for pool, count in ((PRACTICE, practice), (QUALIFY, qualify), (GOLDEN, golden)):
        for _ in range(count):
            source = shuffled[cursor]
            cursor += 1
            task_id = f"{pool}-{len(records):04d}"
            records.append(
                ClipTaskRecord(
                    task_id=task_id,
                    pool=pool,
                    clip=source.clip,
                    question=source.question,
                    choices=list(source.choices),
                    placeholder=source.placeholder,
                )
            )
            truth[task_id] = source.answer

    for source in shuffled[cursor:]:
        task_id = f"{LIVE}-{len(records):04d}"
        records.append(
            ClipTaskRecord(
                task_id=task_id,
                pool=LIVE,
                clip=source.clip,
                question=source.question,
                choices=list(source.choices),
                placeholder=source.placeholder,
            )
        )
        live_truth[task_id] = source.answer

    _write_jsonl(out_dir / MANIFEST_FILE, [asdict(r) for r in records])
    _write_jsonl(
        out_dir / TRUTH_FILE, [{"task_id": k, "answer": v} for k, v in truth.items()]
    )
    _write_jsonl(
        out_dir / LIVE_TRUTH_FILE,
        [{"task_id": k, "answer": v} for k, v in live_truth.items()],
    )
    return records


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def load_records(out_dir: pathlib.Path) -> list[ClipTaskRecord]:
    rows = _read_jsonl(out_dir / MANIFEST_FILE)
    return [ClipTaskRecord(**row) for row in rows]


def load_truth(out_dir: pathlib.Path) -> dict[str, str]:
    """Answers for the graded pools only.

    Deliberately does not read `live_truth.jsonl`. Grading must not be able to
    reach live answers even by accident, which is why they live in a file this
    function never opens.
    """
    return {row["task_id"]: row["answer"] for row in _read_jsonl(out_dir / TRUTH_FILE)}


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def placeholder_clips(count: int, *, question: str, choices: list[str]) -> list[SourceClip]:
    """Stand-in clips so the loop runs before real footage exists.

    These reference clip paths that a renderer or the PM supplies; nothing here
    fabricates video. Every one is flagged `placeholder=True` so a demo check
    can refuse to serve them.
    """
    return [
        SourceClip(
            clip=f"placeholder/{i:03d}.mp4",
            question=question,
            choices=list(choices),
            answer=choices[i % len(choices)],
            placeholder=True,
        )
        for i in range(count)
    ]
