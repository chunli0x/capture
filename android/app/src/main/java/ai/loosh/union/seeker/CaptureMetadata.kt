package ai.loosh.union.seeker

/**
 * The new optional capture-metadata namespaces added in Capture v2, distinct
 * from the three secondary label dimensions. All are optional (defaults
 * empty/false) and ride alongside the label payload:
 *
 * - `surface_type` (string id) — the ground surface under the camera.
 * - `lighting`     (string id) — the lighting condition.
 * - `weather`      (string id) — outdoor weather; empty indoors.
 * - `ego_motion`   (bool)      — true when the capture is from a moving camera.
 */

const val KIND_SURFACE_TYPE = "surface_type"
const val KIND_LIGHTING = "lighting"
const val KIND_WEATHER = "weather"

/**
 * Maps the optional metadata selections to their wire field names. String ids
 * are omitted when unset; `ego_motion` is always present so the backend never
 * has to guess between "no" and "not sent".
 */
fun captureMetadataFields(selection: SecondarySelection): Map<String, Any> =
    buildMap {
        selection.surfaceType?.let { put("surface_type", it) }
        selection.lighting?.let { put("lighting", it) }
        selection.weather?.let { put("weather", it) }
        put("ego_motion", selection.egoMotion)
    }

/**
 * The wire id for a metadata category. The new registries are keyed by string
 * id (their `slug`); numeric-id registries fall back to the integer id rendered
 * as text, so either backend shape produces a stable wire value.
 */
fun categoryWireId(c: TaxonomyCategory): String = c.slug ?: c.id.toString()

/**
 * Whether every *required* label dimension is present. In v2 that is posture:
 * expression is optional, environment/metadata are optional, but a label
 * without a posture is incomplete.
 */
fun isLabelComplete(selection: SecondarySelection): Boolean = selection.postures.isNotEmpty()
