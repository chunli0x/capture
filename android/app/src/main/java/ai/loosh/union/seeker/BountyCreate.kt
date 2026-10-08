package ai.loosh.union.seeker

/** Bounty-kind wire values; the server contract is `object|place|action`. */
const val KIND_OBJECT = "object"
const val KIND_PLACE = "place"
const val KIND_ACTION = "action"

/** Secondary (optional) metadata namespaces also served by `GET /taxonomy`. */
const val KIND_EXPRESSION = "expression"
const val KIND_POSTURE = "posture"
const val KIND_ENVIRONMENT = "environment"

/**
 * A single category in the global registry served by `GET /taxonomy`.
 * [group] is only present for `environment` entries (indoor_outdoor, time,
 * weather, surface, light) and is null for every other kind.
 */
data class TaxonomyCategory(val id: Int, val name: String, val kind: String, val group: String? = null)

/**
 * Resolves a form kind to one of the three wire values. An unknown or blank
 * kind falls back to [KIND_OBJECT], preserving phase-1 object behavior.
 */
fun resolveKind(kind: String?): String =
    when (kind) {
        KIND_PLACE -> KIND_PLACE
        KIND_ACTION -> KIND_ACTION
        else -> KIND_OBJECT
    }

/**
 * The create-bounty request body as pure data, so the closed-vocab threading
 * (chosen registry ids -> create body) is unit-testable without `org.json`.
 */
data class BountyDraft(
    val kind: String,
    val title: String,
    val categoryIds: List<Int>,
    val rewardUsdcUnits: Long,
    val slots: Int,
    val deadline: Long,
)

/**
 * Builds the create-bounty payload from form fields. Categories are closed
 * vocabulary: the ids come from the server registry for the bounty's kind and
 * are sent verbatim (`category_ids`), never minted client-side. Duplicate ids
 * are dropped; the bounty kind is resolved via [resolveKind].
 */
fun buildBountyDraft(
    kind: String?,
    title: String,
    categoryIds: List<Int>,
    rewardUsdcUnits: Long,
    slots: Int,
    deadline: Long,
): BountyDraft =
    BountyDraft(
        kind = resolveKind(kind),
        title = title,
        categoryIds = categoryIds.distinct(),
        rewardUsdcUnits = rewardUsdcUnits,
        slots = slots,
        deadline = deadline,
    )

/**
 * Filters the registry to a single kind namespace (server order preserved), so
 * the creation UI can only offer categories that belong to the selected kind.
 */
fun categoriesForKind(taxonomy: List<TaxonomyCategory>, kind: String?): List<TaxonomyCategory> {
    val resolved = resolveKind(kind)
    return taxonomy.filter { it.kind == resolved }
}
