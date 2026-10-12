package ai.loosh.union.seeker

/**
 * The judge verdict and payout carried by a submit response, per the Capture v2
 * contract: `{ verdict: { accepted, reason }, payout_usdc, level_after }`.
 *
 * Pure and JSON-free so the parsing decisions (null handling, defaults) are
 * unit testable. The ViewModel extracts primitives from `org.json` and hands
 * them to [buildSubmissionResult].
 */

/** The VLM judge's word. [reason] is empty when the server sent none. */
data class Verdict(val accepted: Boolean, val reason: String)

/**
 * The submit response mapped to plain Kotlin.
 *
 * [verdict] is null when the response carried no verdict, which the UI must
 * distinguish from "rejected". [status] carries the server's submission status
 * ("accepted"/"rejected"/"review"), so a free-tier upload routed to peer review
 * ("review") is shown as "pending review" rather than an infinite "judging"
 * spinner.
 */
data class SubmissionResult(
    val verdict: Verdict?,
    val payoutUsdc: Int,
    val levelAfter: Int?,
    val status: String = "",
) {
    /** True only when the judge accepted *and* a payout was recorded. */
    val paid: Boolean get() = verdict?.accepted == true && payoutUsdc > 0

    val rejected: Boolean get() = verdict?.accepted == false

    /** True when the submission was routed to peer review (no judge verdict yet). */
    val pendingReview: Boolean get() = verdict == null && status == "review"
}

/**
 * Builds a [SubmissionResult] from the individual response fields. [accepted]
 * null (no verdict object) yields a result with no verdict; [payoutUsdc] and
 * [levelAfter] fall back to 0 and null respectively.
 */
fun buildSubmissionResult(
    accepted: Boolean?,
    reason: String?,
    payoutUsdc: Int,
    levelAfter: Int?,
    status: String = "",
): SubmissionResult =
    SubmissionResult(
        verdict = accepted?.let { Verdict(it, reason.orEmpty()) },
        payoutUsdc = payoutUsdc,
        levelAfter = levelAfter,
        status = status,
    )
