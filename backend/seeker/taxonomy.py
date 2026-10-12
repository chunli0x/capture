"""Canonical, server-owned category registry (closed vocabulary), Capture v2.

The single source of truth for every category id a bounty or label may
reference. Ids are resolved server-side in ``create_bounty`` and in label
validation; nothing client-supplied — and in particular no free-text category
name — ever reaches a bounty's stored taxonomy or a submission's labels.

v2 changes (pinned by ``/home/hermes/clock-in/CAPTURE-V2-CONTRACT.md`` and
``/home/hermes/egocentric-data-spec.md`` §1.2):

- objects: drop phone/computer/car/tree/flower; add stairs, person,
  obstacles-clutter, curb-step.
- places: add staircase, under-furniture, bathroom, doorway, garage.
- actions: drop ``observe`` (spec §1.2 "DROP/merge"); add ``eat`` (missing from
  the spec's canonical agent vocabulary) and the human-action labels.
- posture is REQUIRED; expression is OPTIONAL (schema-level change in
  ``schemas.py``; here only the ``required`` flag changes).
- four new string-keyed metadata namespaces — ``surface_type``, ``lighting``,
  ``weather``, ``ego_motion`` — all optional, exposed as string ``id`` (slug).

2026-10-12: registry vocabulary is human ground-level-egocentric capture.
Labels describe people, objects, places, and actions at ground level. Numeric
ids are the stable contract; names are the only thing that may be reworded
over time.

Numeric namespaces keep the ``{int: (name, kind)}`` shape; the metadata
namespaces are ``{slug: name}``. ``all_categories()`` flattens both and marks
each entry ``required``.
"""

from typing import Final

# numeric namespace -> {category_id: (name, kind)}
_NAMESPACES: Final[dict[str, dict[int, tuple[str, str]]]] = {
    "objects": {
        1: ("bowls", "object"),
        2: ("toys", "object"),
        3: ("shoes", "object"),
        4: ("food", "object"),
        5: ("water", "object"),
        6: ("furniture", "object"),
        7: ("bush", "object"),
        8: ("pillow", "object"),
        9: ("ball", "object"),
        10: ("door", "object"),
        11: ("bag", "object"),
        12: ("bottle", "object"),
        13: ("doorstop", "object"),
        14: ("stairs", "object"),
        15: ("person", "object"),
        16: ("obstacles-clutter", "object"),
        17: ("curb-step", "object"),
    },
    "scenes": {
        1: ("bed", "place"),
        2: ("living room", "place"),
        3: ("kitchen", "place"),
        4: ("home", "place"),
        5: ("school", "place"),
        6: ("work", "place"),
        7: ("hallway", "place"),
        8: ("backyard", "place"),
        9: ("sidewalk", "place"),
        10: ("road", "place"),
        11: ("park", "place"),
        12: ("foyer", "place"),
        13: ("staircase", "place"),
        14: ("under-furniture", "place"),
        15: ("bathroom", "place"),
        16: ("doorway", "place"),
        17: ("garage", "place"),
    },
    "actions": {
        1: ("look around", "action"),
        2: ("pause", "action"),
        3: ("rest", "action"),
        4: ("relax outdoors", "action"),
        5: ("take shelter", "action"),
        6: ("walk toward", "action"),
        7: ("pick up", "action"),
        8: ("walk", "action"),
        9: ("sit", "action"),
        10: ("lie down", "action"),
        11: ("wave", "action"),
        12: ("reach low", "action"),
        13: ("jump", "action"),
        14: ("run", "action"),
        15: ("step quickly", "action"),
        16: ("wait", "action"),
        17: ("sitting up", "action"),
        18: ("reach up", "action"),
        19: ("adjust", "action"),
        20: ("eat", "action"),
        21: ("person walking", "action"),
        22: ("person standing", "action"),
        23: ("person sitting", "action"),
        24: ("person throwing", "action"),
        25: ("person opening door", "action"),
        26: ("person handing", "action"),
        27: ("person reaching", "action"),
    },
    "expressions": {
        1: ("neutral", "expression"),
        2: ("happy", "expression"),
        3: ("surprised", "expression"),
        4: ("fearful", "expression"),
        5: ("angry", "expression"),
        6: ("sad", "expression"),
        7: ("disgusted", "expression"),
        8: ("curious", "expression"),
        9: ("alert", "expression"),
        10: ("relaxed", "expression"),
        11: ("tense", "expression"),
        12: ("squinting", "expression"),
        13: ("wide-eyed", "expression"),
        14: ("yawning", "expression"),
        15: ("smiling", "expression"),
        16: ("frowning", "expression"),
        17: ("talking", "expression"),
        18: ("grimacing", "expression"),
        19: ("blinking", "expression"),
        20: ("attentive", "expression"),
    },
    "postures": {
        1: ("standing", "posture"),
        2: ("crouching", "posture"),
        3: ("sitting", "posture"),
        4: ("lying", "posture"),
        5: ("curled", "posture"),
        6: ("stretched out", "posture"),
        7: ("reaching up", "posture"),
        8: ("reaching down", "posture"),
        9: ("hunched", "posture"),
        10: ("looking away", "posture"),
        11: ("on guard", "posture"),
        12: ("stiff posture", "posture"),
        13: ("relaxed posture", "posture"),
        14: ("leaning forward", "posture"),
        15: ("backing away", "posture"),
        16: ("arm raised", "posture"),
        17: ("head tilt", "posture"),
        18: ("arched back", "posture"),
        19: ("reclining", "posture"),
        20: ("moving toward", "posture"),
        21: ("moving away", "posture"),
    },
    "environment": {
        1: ("indoor", "environment"),
        2: ("outdoor", "environment"),
        3: ("daytime", "environment"),
        4: ("night", "environment"),
        5: ("dawn", "environment"),
        6: ("dusk", "environment"),
        7: ("sunny", "environment"),
        8: ("overcast", "environment"),
        9: ("rainy", "environment"),
        10: ("snowy", "environment"),
        11: ("windy", "environment"),
        12: ("hard floor", "environment"),
        13: ("carpet", "environment"),
        14: ("tile", "environment"),
        15: ("wood floor", "environment"),
        16: ("concrete", "environment"),
        17: ("grass", "environment"),
        18: ("dirt", "environment"),
        19: ("gravel", "environment"),
        20: ("asphalt", "environment"),
        21: ("indoor lighting", "environment"),
        22: ("natural light", "environment"),
        23: ("low light", "environment"),
        24: ("bright light", "environment"),
    },
}

# string-keyed metadata namespaces -> {slug: name}. All optional in v2.
_METADATA: Final[dict[str, dict[str, str]]] = {
    "surface_type": {
        "hardwood": "Hardwood",
        "carpet": "Carpet",
        "tile": "Tile",
        "concrete": "Concrete",
        "grass": "Grass",
        "gravel": "Gravel",
        "mud": "Mud",
        "snow": "Snow",
    },
    "lighting": {
        "day": "Day",
        "golden-hour": "Golden hour",
        "dusk": "Dusk",
        "night": "Night",
        "artificial": "Artificial",
        "backlit": "Backlit",
    },
    "weather": {
        "sun": "Sun",
        "overcast": "Overcast",
        "rain": "Rain",
        "wet-ground": "Wet ground",
        "snow": "Snow",
    },
    "ego_motion": {
        "stationary": "Stationary",
        "forward": "Forward",
        "turn": "Turn",
        "pitch-sweep": "Pitch sweep",
    },
}

# environment category id -> mutually-exclusive sub-attribute group.
_ENV_GROUPS: Final[dict[int, str]] = {
    1: "indoor_outdoor",
    2: "indoor_outdoor",
    3: "time",
    4: "time",
    5: "time",
    6: "time",
    7: "weather",
    8: "weather",
    9: "weather",
    10: "weather",
    11: "weather",
    12: "surface",
    13: "surface",
    14: "surface",
    15: "surface",
    16: "surface",
    17: "surface",
    18: "surface",
    19: "surface",
    20: "surface",
    21: "light",
    22: "light",
    23: "light",
    24: "light",
}

# bounty kind -> namespace
_KIND_NAMESPACE: Final = {
    "object": "objects",
    "place": "scenes",
    "action": "actions",
}

# secondary label dimension -> namespace (multi-select, non-gating)
_SECONDARY: Final = {
    "expressions": "expressions",
    "postures": "postures",
    "environment": "environment",
}

# namespaces whose labels are required in v2. posture was promoted from
# optional to required; expression was demoted to optional.
_REQUIRED: Final = {"objects", "scenes", "actions", "postures"}


def all_categories() -> list[dict]:
    """Every category in the registry, flattened, for GET /taxonomy."""
    out = []
    for namespace, entries in _NAMESPACES.items():
        for cid, (name, kind) in entries.items():
            item = {
                "id": cid,
                "name": name,
                "kind": kind,
                "required": namespace in _REQUIRED,
            }
            if namespace == "environment":
                item["group"] = _ENV_GROUPS[cid]
            out.append(item)
    for namespace, entries in _METADATA.items():
        for slug, name in entries.items():
            out.append(
                {
                    "id": slug,
                    "name": name,
                    "kind": namespace,
                    "required": False,
                }
            )
    return out


def resolve(kind: str, category_ids: list[int]) -> list[dict]:
    """Resolve a bounty kind + list of ids to the server-side taxonomy.

    Raises ``ValueError`` for any id not present in the kind's namespace (or
    for duplicate ids); callers surface that as a 422. Names are always drawn
    from the registry, never from the request.
    """
    try:
        namespace = _NAMESPACES[_KIND_NAMESPACE[kind]]
    except KeyError:
        raise ValueError(f"Unknown bounty kind {kind!r}") from None
    if len(set(category_ids)) != len(category_ids):
        raise ValueError("Category IDs must be unique")
    taxonomy = []
    for cid in category_ids:
        entry = namespace.get(cid)
        if entry is None:
            raise ValueError(f"Unknown category id {cid} for kind {kind!r}")
        name, kind_value = entry
        taxonomy.append({"id": cid, "name": name, "kind": kind_value})
    return taxonomy


def resolve_secondary(dimension: str, category_ids: list[int]) -> list[dict]:
    """Resolve optional secondary label ids against a secondary namespace.

    Secondary dimensions are expressions, postures, and environment. Raises
    ``ValueError`` for an unknown dimension, any unknown id, or duplicate ids.
    Environment enforces at most one id per sub-attribute group.
    """
    try:
        namespace = _NAMESPACES[_SECONDARY[dimension]]
    except KeyError:
        raise ValueError(f"Unknown secondary dimension {dimension!r}") from None
    if len(set(category_ids)) != len(category_ids):
        raise ValueError("Secondary category IDs must be unique")
    if dimension == "environment":
        groups = [_ENV_GROUPS.get(cid) for cid in category_ids]
        if len(set(groups)) != len(groups):
            raise ValueError("Environment allows at most one category per group")
    resolved = []
    for cid in category_ids:
        entry = namespace.get(cid)
        if entry is None:
            raise ValueError(
                f"Unknown category id {cid} for dimension {dimension!r}"
            )
        name, kind_value = entry
        item = {"id": cid, "name": name, "kind": kind_value}
        if dimension == "environment":
            item["group"] = _ENV_GROUPS[cid]
        resolved.append(item)
    return resolved


def resolve_metadata(namespace: str, slug: str) -> dict:
    """Resolve one string-keyed metadata slug (surface_type/lighting/weather).

    Raises ``ValueError`` for an unknown namespace or slug. Returns
    ``{id, name, kind}``.
    """
    if namespace not in _METADATA:
        raise ValueError(f"Unknown metadata namespace {namespace!r}")
    name = _METADATA[namespace].get(slug)
    if name is None:
        raise ValueError(f"Unknown {namespace} id {slug!r}")
    return {"id": slug, "name": name, "kind": namespace}


def is_metadata_namespace(namespace: str) -> bool:
    return namespace in _METADATA
