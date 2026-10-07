"""Canonical, server-owned category registry (closed vocabulary).

The single source of truth for every category id a bounty may reference. Ids
are resolved server-side in ``create_bounty``; nothing client-supplied — and
in particular no free-text category name — ever reaches a bounty's stored
taxonomy. Each entry is a fixed ``{id, name, kind}`` triple. Namespaces map
to bounty kinds: ``objects`` -> ``object``, ``scenes`` -> ``place``,
``actions`` -> ``action``.
"""

from typing import Final

# namespace -> {category_id: (name, kind)}
_NAMESPACES: Final[dict[str, dict[int, tuple[str, str]]]] = {
    "objects": {
        1: ("cup", "object"),
        2: ("bottle", "object"),
        3: ("phone", "object"),
        4: ("book", "object"),
        5: ("chair", "object"),
    },
    "scenes": {
        1: ("beach", "place"),
        2: ("park", "place"),
        3: ("street", "place"),
        4: ("kitchen", "place"),
        5: ("office", "place"),
    },
    "actions": {
        1: ("jump", "action"),
        2: ("walk", "action"),
        3: ("sit", "action"),
        4: ("wave", "action"),
        5: ("throw", "action"),
    },
}

# bounty kind -> namespace
_KIND_NAMESPACE: Final = {
    "object": "objects",
    "place": "scenes",
    "action": "actions",
}


def all_categories() -> list[dict]:
    """Every category in the registry, flattened, for GET /taxonomy."""
    out = []
    for entries in _NAMESPACES.values():
        for cid, (name, kind) in entries.items():
            out.append({"id": cid, "name": name, "kind": kind})
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
