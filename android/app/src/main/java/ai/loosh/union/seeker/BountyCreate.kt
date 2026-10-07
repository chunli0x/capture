package ai.loosh.union.seeker

/** Bounty-kind wire values; the server contract is `object|place|action`. */
const val KIND_OBJECT = "object"
const val KIND_PLACE = "place"
const val KIND_ACTION = "action"

/** A single category in a bounty's immutable per-kind taxonomy. */
data class BountyCategory(val id: Int, val name: String, val kind: String)

/**
 * The complete create-bounty request body as pure data, so the kind/category
 * namespace threading is unit-testable without Android's `org.json`.
 */
data class BountyDraft(
    val kind: String,
    val title: String,
    val categories: List<BountyCategory>,
    val rewardUsdcUnits: Long,
    val slots: Int,
    val deadline: Long,
)

/**
 * Builds the create-bounty payload from the form fields.
 *
 * The bounty `kind` and every category's `kind` must agree (the server rejects
 * a mismatch), so each category inherits the bounty kind — i.e. it lands in the
 * matching taxonomy namespace (`objects`/`scenes`/`actions`). A missing or
 * unknown kind falls back to [KIND_OBJECT], preserving phase-1 behavior.
 */
fun buildBountyDraft(
    kind: String?,
    title: String,
    categories: String,
    rewardUsdcUnits: Long,
    slots: Int,
    deadline: Long,
): BountyDraft {
    val resolved =
        when (kind) {
            KIND_PLACE -> KIND_PLACE
            KIND_ACTION -> KIND_ACTION
            else -> KIND_OBJECT
        }
    val cats =
        categories
            .split(',')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .mapIndexed { index, name ->
                BountyCategory(id = index + 1, name = name, kind = resolved)
            }
    return BountyDraft(
        kind = resolved,
        title = title,
        categories = cats,
        rewardUsdcUnits = rewardUsdcUnits,
        slots = slots,
        deadline = deadline,
    )
}
