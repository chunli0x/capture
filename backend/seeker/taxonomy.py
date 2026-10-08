"""Canonical, server-owned category registry (closed vocabulary).

The single source of truth for every category id a bounty or label may
reference. Ids are resolved server-side in ``create_bounty`` and in label
validation; nothing client-supplied — and in particular no free-text category
name — ever reaches a bounty's stored taxonomy or a submission's labels. Each
entry is a fixed ``{id, name, kind}`` triple (environment entries also carry a
``group``).

Three namespaces map to the primary bounty kinds (``objects`` -> ``object``,
``scenes`` -> ``place``, ``actions`` -> ``action``). Three further namespaces
are secondary label dimensions — facial expressions, body language, and
environment — that may optionally accompany any submission regardless of the
bounty's primary kind.
"""

from typing import Final

# namespace -> {category_id: (name, kind)}
_NAMESPACES: Final[dict[str, dict[int, tuple[str, str]]]] = {
    "objects": {
        1: ("phone", "object"),
        2: ("computer", "object"),
        3: ("bowls", "object"),
        4: ("toys", "object"),
        5: ("shoes", "object"),
        6: ("tree", "object"),
        7: ("flower", "object"),
        8: ("food", "object"),
        9: ("water", "object"),
        10: ("furniture", "object"),
        11: ("bush", "object"),
        12: ("car", "object"),
        13: ("pillow", "object"),
        14: ("ball", "object"),
        15: ("door", "object"),
        16: ("bag", "object"),
        17: ("bone", "object"),
        18: ("doorstop", "object"),
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
    },
    "actions": {
        1: ("sniff", "action"),
        2: ("observe", "action"),
        3: ("think", "action"),
        4: ("sleep", "action"),
        5: ("lie in the sun", "action"),
        6: ("avoid the rain", "action"),
        7: ("chase", "action"),
        8: ("fetch", "action"),
        9: ("walk", "action"),
        10: ("sit", "action"),
        11: ("lie down", "action"),
        12: ("tail wag", "action"),
        13: ("dig", "action"),
        14: ("jump", "action"),
        15: ("run", "action"),
        16: ("trot", "action"),
        17: ("waiting", "action"),
        18: ("eager sitting", "action"),
        19: ("begging", "action"),
        20: ("scratching", "action"),
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
        17: ("tongue-out", "expression"),
        18: ("teeth-bared", "expression"),
        19: ("blinking", "expression"),
        20: ("ears-flat", "expression"),
    },
    "postures": {
        1: ("standing", "posture"),
        2: ("crouching", "posture"),
        3: ("sitting", "posture"),
        4: ("lying", "posture"),
        5: ("curled", "posture"),
        6: ("stretched out", "posture"),
        7: ("tail-up", "posture"),
        8: ("tail-down", "posture"),
        9: ("tail-tucked", "posture"),
        10: ("ears-flat", "posture"),
        11: ("hackles-raised", "posture"),
        12: ("stiff posture", "posture"),
        13: ("relaxed posture", "posture"),
        14: ("leaning forward", "posture"),
        15: ("backing away", "posture"),
        16: ("paw raised", "posture"),
        17: ("head tilt", "posture"),
        18: ("arched back", "posture"),
        19: ("belly exposed", "posture"),
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

# secondary label dimension -> namespace (optional, multi-select, non-gating)
_SECONDARY: Final = {
    "expressions": "expressions",
    "postures": "postures",
    "environment": "environment",
}


def all_categories() -> list[dict]:
    """Every category in the registry, flattened, for GET /taxonomy."""
    out = []
    for namespace, entries in _NAMESPACES.items():
        for cid, (name, kind) in entries.items():
            item = {"id": cid, "name": name, "kind": kind}
            if namespace == "environment":
                item["group"] = _ENV_GROUPS[cid]
            out.append(item)
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
