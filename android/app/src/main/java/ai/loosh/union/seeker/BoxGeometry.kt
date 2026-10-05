package ai.loosh.union.seeker

import kotlin.math.abs
import kotlin.math.min

data class LabelBox(val categoryId: Int, val x: Float, val y: Float, val w: Float, val h: Float)

/** Coordinates are measured in the image's aspect-ratio-sized surface, never a letterbox. */
fun dragBox(category: Int, x0: Float, y0: Float, x1: Float, y1: Float): LabelBox? {
    if (listOf(x0,y0,x1,y1).any { !it.isFinite() }) return null
    val a=x0.coerceIn(0f,1f); val b=y0.coerceIn(0f,1f)
    val c=x1.coerceIn(0f,1f); val d=y1.coerceIn(0f,1f)
    if (abs(c-a)<.01f || abs(d-b)<.01f) return null
    return LabelBox(category,min(a,c),min(b,d),abs(c-a),abs(d-b))
}
