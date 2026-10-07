package ai.loosh.union.seeker

/**
 * A single scene class for a `place` bounty. Closed vocabulary; the type holds
 * exactly one category id, so a place label can never be multi-label.
 */
data class SceneLabel(val categoryId: Int)

/**
 * Single-select scene choice against the bounty's closed vocabulary. Returns
 * the label only when exactly one known category is selected; null otherwise
 * (including unknown ids, which can never mint a label client-side).
 */
fun sceneLabel(selectedId: Int?, taxonomyIds: Set<Int>): SceneLabel? =
    selectedId?.takeIf { it in taxonomyIds }?.let(::SceneLabel)

/** A single action tag plus a valid trim for an `action` bounty. Closed vocab, one tag, one trim. */
data class ActionLabel(val categoryId: Int, val startMs: Int, val endMs: Int)

/**
 * Builds an action label only when a known category is selected and a valid
 * nonempty trim is supplied; null otherwise.
 */
fun actionLabel(categoryId: Int?, taxonomyIds: Set<Int>, trim: TrimRange?): ActionLabel? =
    if (categoryId != null && categoryId in taxonomyIds && trim != null)
        ActionLabel(categoryId, trim.startMs, trim.endMs)
    else null
