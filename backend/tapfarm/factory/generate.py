"""Factory-floor inspection clip generation via the Runway Dev API.

Generates the 12 demo clips for the factory inspection campaign: realistic
factory/warehouse footage showing a box in one of four states (damaged,
missing shipping label, unsealed, or clean), under three lighting conditions,
shot in two styles (a fixed overhead security camera, and a ground-level
egocentric view).

The prompt is the ground truth: each clip is generated from a spec whose defect
slot is known, so the manifest can record the label exactly without any
separate annotation pass.

Format decisions (see the plan):
- Model gen4.5, 5s, 1280:720, mp4. Video-only; audio is deferred (gen4.5 has
  no native audio) and layered later.
- A fixed scaffold per style, then three compact slots {LIGHTING}. {DEFECT}.
  {NOISE}. — the scaffold stays constant so the only thing a classifier has to
  tell apart is the defect, and the wording never drifts.
- Credits are limited: every clip prints its `estimatedCost` and the run aborts
  if any single clip would cost more than MAX_CREDITS_PER_CLIP.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import time
from dataclasses import asdict, dataclass

import httpx

API = "https://api.dev.runwayml.com/v1"
API_VERSION = "2024-11-06"
MODEL = "gen4.5"
RATIO = "1280:720"
DURATION = 5

# A single 5s 720p gen4.5 clip costs 60 credits (12/sec). This cap is a tripwire
# against a wildly wrong estimate, not a budget control: the task is created by
# the time we see the estimate, so the guard only stops the download. Set well
# above the real cost.
MAX_CREDITS_PER_CLIP = 100

# --- the consistent format ----------------------------------------------------

# The scaffold is identical for every clip in a style; the box descriptor and
# the defect phrasing vary per clip so no two clips look alike. Only the three
# slots draw from closed vocabularies: {LIGHTING}. {DEFECT}. {NOISE}.
SCAFFOLD = {
    "cctv": (
        "Fixed overhead security-camera view of {box} moving left to right on "
        "rollers on an elevated industrial factory conveyor line, plain grey "
        "concrete floor and palettes in the background."
    ),
    "robot": (
        "Ground-level egocentric view of {box} on a factory floor, a "
        "conveyor line with boxes in frame, realistic industrial warehouse, "
        "natural motion."
    ),
}

LIGHTING = {
    "harsh-fluorescent": "Harsh fluorescent light with slight flicker",
    "dim-tungsten": "Dim warm tungsten light",
    "backlit": "Backlit from a loading bay",
}

# Six box shapes/sizes, cycled across the CCTV clips so each inspection target
# differs. Ground-level clips keep the generic "cardboard packages" scaffold.
BOXES = [
    "a tall, narrow cardboard box",
    "a wide, flat cardboard box",
    "a small, cube-shaped cardboard box",
    "a large, rectangular cardboard box",
    "a long, shallow cardboard box",
    "a medium, square cardboard box",
]

# Three phrasings per defect class, cycled across that class's three lighting
# clips. The class stays the ground-truth label; the wording varies so the dent,
# damage and sealing look different in each shot.
DEFECT = {
    "damaged": [
        "one corner crushed and torn open, cardboard ripped and deeply dented, clearly damaged",
        "a large torn gash across the top, cardboard ripped and split open",
        "the side panel deeply dented and crushed inward, box visibly bashed",
    ],
    "missing-label": [
        "shipping label missing, blank side",
        "no shipping label, bare cardboard",
        "label peeled away, adhesive residue only",
    ],
    "unsealed": [
        "top flaps open, no tape",
        "top flaps loose, gaping open",
        "sealing tape missing, flaps ajar",
    ],
    "clean": [
        "intact and undamaged, neatly sealed with tape",
        "pristine, sealed cleanly, no damage",
        "undamaged, tightly sealed",
    ],
}

NOISE = {
    "cctv": "Mild motion blur, CCTV sensor grain",
    "robot": "Mild motion blur, slight sensor noise",
}

# A defect is "present" for the three real defects and absent for the control.
DEFECT_PRESENT = {
    "damaged": True,
    "missing-label": True,
    "unsealed": True,
    "clean": False,
}


@dataclass(frozen=True)
class ClipSpec:
    clip_id: str
    defect: str
    lighting: str
    style: str
    seed: int
    box: str
    defect_phrase: str

    @property
    def prompt(self) -> str:
        scaffold = SCAFFOLD[self.style].format(box=self.box)
        return (
            f"{scaffold} "
            f"{LIGHTING[self.lighting]}. {self.defect_phrase}. "
            f"{NOISE[self.style]}."
        )

    @property
    def defect_present(self) -> bool:
        return DEFECT_PRESENT[self.defect]


# 12 clips = 4 defects x 3 lighting, both styles evenly (6 cctv + 6 robot),
# each defect and each lighting covered 3 and 4 times respectively. The box
# shape/size and the defect phrasing are cycled so no two clips look alike.
def build_specs() -> list[ClipSpec]:
    rows = [
        ("damaged", "harsh-fluorescent", "cctv"),
        ("damaged", "dim-tungsten", "cctv"),
        ("damaged", "backlit", "robot"),
        ("missing-label", "harsh-fluorescent", "robot"),
        ("missing-label", "dim-tungsten", "cctv"),
        ("missing-label", "backlit", "robot"),
        ("unsealed", "harsh-fluorescent", "cctv"),
        ("unsealed", "dim-tungsten", "robot"),
        ("unsealed", "backlit", "cctv"),
        ("clean", "harsh-fluorescent", "robot"),
        ("clean", "dim-tungsten", "cctv"),
        ("clean", "backlit", "robot"),
    ]
    specs = []
    # Track how many times each defect class has been seen, so its three
    # phrasings rotate across its three lighting clips.
    defect_index: dict[str, int] = {}
    for i, (defect, lighting, style) in enumerate(rows):
        clip_id = f"{defect}__{lighting}__{style}"
        box = BOXES[i % len(BOXES)]
        phrase = DEFECT[defect][defect_index.get(defect, 0) % len(DEFECT[defect])]
        defect_index[defect] = defect_index.get(defect, 0) + 1
        # Deterministic seed per clip so a re-run is reproducible.
        specs.append(
            ClipSpec(
                clip_id=clip_id,
                defect=defect,
                lighting=lighting,
                style=style,
                seed=1_000_000 + i * 97,
                box=box,
                defect_phrase=phrase,
            )
        )
    return specs


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": API_VERSION,
        "Content-Type": "application/json",
    }


def start_clip(client: httpx.Client, api_key: str, spec: ClipSpec) -> dict:
    resp = client.post(
        f"{API}/text_to_video",
        headers=_headers(api_key),
        json={
            "model": MODEL,
            "promptText": spec.prompt,
            "ratio": RATIO,
            "duration": DURATION,
            "seed": spec.seed,
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"start failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


def poll_clip(
    client: httpx.Client, api_key: str, task_id: str, timeout_s: int = 600
) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        resp = client.get(f"{API}/tasks/{task_id}", headers=_headers(api_key))
        if resp.status_code != 200:
            raise RuntimeError(f"poll failed ({resp.status_code}): {resp.text[:500]}")
        task = resp.json()
        status = task.get("status")
        if status == "SUCCEEDED":
            return task
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"task {task_id} ended in status {status}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"task {task_id} did not finish in {timeout_s}s")
        time.sleep(5)


def download_video(client: httpx.Client, url: str, dest: pathlib.Path) -> None:
    resp = client.get(url, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def _load_manifest(manifest_path: pathlib.Path) -> dict[str, dict]:
    """Load existing manifest rows keyed by clip_id, if any."""
    if not manifest_path.exists():
        return {}
    rows = {}
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "clip_id" in row:
            rows[row["clip_id"]] = row
    return rows


def generate_all(
    out_dir: pathlib.Path,
    api_key: str,
    *,
    only: set[str] | None = None,
    timeout_s: int = 600,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    specs = build_specs()
    if only:
        specs = [s for s in specs if s.clip_id in only]

    # Merge into the existing manifest instead of clobbering it, so a partial
    # re-run (e.g. --only on a few clips) keeps every other clip's row intact.
    manifest = out_dir / "manifest.jsonl"
    manifest_rows = _load_manifest(manifest)

    with httpx.Client() as client:
        for spec in specs:
            print(f"[{spec.clip_id}] starting... prompt={spec.prompt!r}")
            task = start_clip(client, api_key, spec)
            cost = (task.get("estimatedCost") or {}).get("credits")
            print(f"    task {task['id']}  estimated cost: {cost} credits")
            if isinstance(cost, (int, float)) and cost > MAX_CREDITS_PER_CLIP:
                raise RuntimeError(
                    f"clip {spec.clip_id} would cost {cost} credits, over the "
                    f"{MAX_CREDITS_PER_CLIP} cap; aborting before spending it"
                )

            done = poll_clip(client, api_key, task["id"], timeout_s=timeout_s)
            output = done.get("output")
            url = output[0] if isinstance(output, list) and output else None
            if not url:
                raise RuntimeError(f"task {task['id']} produced no output URL")

            dest = media_dir / f"{spec.clip_id}.mp4"
            download_video(client, url, dest)
            manifest_rows[spec.clip_id] = {
                "clip_id": spec.clip_id,
                "file": f"media/{spec.clip_id}.mp4",
                "defect": spec.defect,
                "defect_present": spec.defect_present,
                "defect_phrase": spec.defect_phrase,
                "box": spec.box,
                "lighting": spec.lighting,
                "style": spec.style,
                "prompt": spec.prompt,
                "seed": spec.seed,
            }
            print(f"    saved {dest} ({dest.stat().st_size} bytes)")

    manifest.write_text(
        "".join(
            json.dumps(manifest_rows[clip_id]) + "\n"
            for clip_id in sorted(manifest_rows)
        )
    )
    print(f"manifest at {manifest} now has {len(manifest_rows)} clips "
          f"({len(specs)} generated this run)")


def load_key() -> str:
    key = os.environ.get("RUNWAYML_API_SECRET") or os.environ.get("RUNWAY_API_KEY")
    if key:
        return key
    env_file = pathlib.Path(__file__).resolve().parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("RUNWAY") and "=" in line and not line.startswith("#"):
                _, value = line.split("=", 1)
                return value.strip()
    raise RuntimeError(
        "no Runway API key found; set RUNWAYML_API_SECRET or backend/.env"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate factory inspection clips")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/factory"))
    parser.add_argument("--only", nargs="*", help="restrict to these clip ids")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    generate_all(args.out, load_key(), only=set(args.only) if args.only else None,
                 timeout_s=args.timeout)
