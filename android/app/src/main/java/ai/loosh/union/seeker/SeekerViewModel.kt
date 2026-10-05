package ai.loosh.union.seeker

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import ai.loosh.union.Base58
import ai.loosh.union.BuildConfig
import com.solana.mobilewalletadapter.clientlib.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

private fun JSONArray.objects() = (0 until length()).map { getJSONObject(it) }

data class PilotState(
    val server: String = "", val wallet: String = "", val worker: Boolean = false, val reviewer: Boolean = false,
    val busy: Boolean = false, val message: String = "", val error: String? = null,
    val bounties: List<JSONObject> = emptyList(), val submissions: List<JSONObject> = emptyList(),
    val reviews: List<JSONObject> = emptyList(), val transactions: List<JSONObject> = emptyList(),
    val selected: JSONObject? = null, val image: Bitmap? = null, val reviewing: Boolean = false,
    val bond: Long = 0,
)

class SeekerViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs=application.getSharedPreferences("seeker.api",0)
    private val mutable=MutableStateFlow(PilotState(server=prefs.getString("server",null) ?: BuildConfig.SEEKER_API_BASE))
    val state=mutable.asStateFlow()
    private var token: String?=null
    private var draftInput: List<String>?=null
    private var draftBody: JSONObject?=null
    private var draftKey: String?=null
    private val http=OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
        .callTimeout(75,TimeUnit.SECONDS).build()
    private val adapter=MobileWalletAdapter(connectionIdentity=ConnectionIdentity(
        identityUri=Uri.parse("https://union.loosh.ai"),iconUri=Uri.parse("favicon.ico"),identityName="Seeker test pilot"
    )).apply { blockchain=Solana.Devnet }

    private fun run(label: String, block: suspend () -> Unit) {
        if (mutable.value.busy) return
        mutable.update { it.copy(busy=true,error=null,message=label) }
        viewModelScope.launch {
            try { block(); mutable.update { it.copy(message="Ready") } }
            catch (e: Exception) { mutable.update { it.copy(error=e.message ?: "Request failed") } }
            finally { mutable.update { it.copy(busy=false) } }
        }
    }

    fun server(value: String) {
        if (mutable.value.busy) return
        val url=value.trim().trimEnd('/')
        val uri=Uri.parse(url)
        if (uri.host.isNullOrBlank() || !(uri.scheme=="https" || BuildConfig.DEBUG && uri.scheme=="http") || uri.userInfo!=null) {
            mutable.update { it.copy(error="Enter an HTTPS server address (HTTP is allowed only in debug).") };return
        }
        token=null;adapter.authToken=null;draftInput=null;draftBody=null;draftKey=null
        prefs.edit().putString("server",url).apply()
        mutable.value=PilotState(server=url)
    }

    private suspend fun bytes(path: String, json: JSONObject?=null, raw: ByteArray?=null): ByteArray = withContext(Dispatchers.IO) {
        val url=mutable.value.server
        require(BuildConfig.DEBUG || url.startsWith("https://")) { "Release builds require HTTPS." }
        val builder=Request.Builder().url(url+path)
        token?.let { builder.header("Authorization","Bearer $it") }
        if (json!=null) builder.post(json.toString().toRequestBody("application/json".toMediaType()))
        if (raw!=null) builder.post(raw.toRequestBody("application/octet-stream".toMediaType()))
        http.newCall(builder.build()).execute().use { response ->
            val data=response.body?.bytes() ?: error("Empty server response")
            if (!response.isSuccessful) {
                val detail=runCatching { JSONObject(String(data)).optString("detail") }.getOrDefault("Request failed")
                error("${response.code}: $detail")
            }
            data
        }
    }
    private suspend fun get(path: String)=JSONObject(String(bytes(path)))
    private suspend fun post(path: String, data: JSONObject=JSONObject())=JSONObject(String(bytes(path,data)))
    private suspend fun list(path: String)=JSONArray(String(bytes(path))).objects()

    fun connect(sender: ActivityResultSender)=run("Sign in with your devnet wallet") {
        val connection=adapter.connect(sender)
        check(connection is TransactionResult.Success) { "Wallet connection was not approved." }
        val wallet=Base58.encode(connection.authResult.accounts.first().publicKey)
        val challenge=post("/auth/challenge",JSONObject().put("wallet",wallet))
        val signed=adapter.transact(sender) { auth ->
            check(Base58.encode(auth.accounts.first().publicKey)==wallet) { "Wallet changed; sign in again." }
            signMessagesDetached(arrayOf(challenge.getString("message").toByteArray(Charsets.UTF_8)),arrayOf(auth.accounts.first().publicKey))
        }
        check(signed is TransactionResult.Success) { "Sign-in was not approved." }
        val signature=signed.successPayload?.messages?.first()?.signatures?.first() ?: error("Wallet returned no signature")
        val session=post("/auth/verify",JSONObject().put("challenge_id",challenge.getString("challenge_id")).put("signature",Base58.encode(signature)))
        token=session.getString("token")
        mutable.update { it.copy(wallet=wallet) };refreshData()
    }

    fun logout()=run("Signing out") {
        post("/auth/logout");token=null;adapter.authToken=null
        mutable.value=PilotState(server=mutable.value.server)
    }
    private suspend fun refreshData() {
        val me=get("/me")
        val b=list("/bounties");val s=list("/submissions")
        val r=if(me.getBoolean("reviewer")) list("/review-queue") else emptyList()
        val tx=list("/transactions")
        mutable.update { it.copy(worker=me.getBoolean("worker"),reviewer=me.getBoolean("reviewer"),bond=me.getLong("bond_test_skr_units"),bounties=b,submissions=s,reviews=r,transactions=tx) }
    }
    fun refresh()=run("Refreshing") { refreshData() }
    fun close() { if(!mutable.value.busy) mutable.update { it.copy(selected=null,image=null) } }

    fun create(title: String,categories: String,reward: String,slots: String,hours: String)=run("Creating bounty draft") {
        val amount=reward.toBigDecimal().movePointRight(6).longValueExact()
        val cats=JSONArray();categories.split(',').map { it.trim() }.filter { it.isNotEmpty() }.forEachIndexed { index,name -> cats.put(JSONObject().put("id",index+1).put("name",name)) }
        val duration=hours.toLong();require(duration in 1..720) { "Choose 1–720 hours." }
        val input=listOf(title,categories,reward,slots,hours)
        val fresh=JSONObject().put("title",title).put("categories",cats).put("reward_usdc_units",amount).put("slots",slots.toInt()).put("deadline",System.currentTimeMillis()/1000+duration*3600)
        if(draftInput!=input) { draftInput=input;draftBody=fresh;draftKey=UUID.randomUUID().toString() }
        val data=draftBody ?: error("Missing draft")
        val hash=draftKey ?: error("Missing draft key")
        withContext(Dispatchers.IO) {
            val req=Request.Builder().url(mutable.value.server+"/bounties").header("Authorization","Bearer $token")
                .header("Idempotency-Key",hash).post(data.toString().toRequestBody("application/json".toMediaType())).build()
            http.newCall(req).execute().use { check(it.isSuccessful) { it.body?.string() ?: "Create failed" } }
        }
        refreshData()
    }
    fun claim(bid: String)=run("Reserving a capture slot") {
        val s=post("/bounties/$bid/claim");mutable.update { it.copy(selected=s,image=null,reviewing=false) }
        if(!s.isNull("media_hash")) loadImage(s.getString("id"))
        refreshData()
    }
    fun open(s: JSONObject,review: Boolean)=run("Opening approved image") {
        mutable.update { it.copy(selected=s,image=null,reviewing=review) }
        if(!s.isNull("media_hash")) loadImage(s.getString("id"))
    }
    private suspend fun loadImage(id: String) {
        val data=bytes("/submissions/$id/media")
        val image=withContext(Dispatchers.Default) { BitmapFactory.decodeByteArray(data,0,data.size) ?: error("Image cannot be decoded") }
        mutable.update { it.copy(image=image) }
    }
    fun capture(data: ByteArray)=run("Checking your photo before upload approval") {
        val s=mutable.value.selected ?: error("Select a claim first")
        val id=s.getString("id")
        val result=JSONObject(String(bytes("/submissions/$id/media",raw=data)))
        s.put("media_hash",result.getString("media_hash"))
        loadImage(id);refreshData()
    }
    fun submit(boxes: List<LabelBox>)=run("Submitting manual labels") {
        val s=mutable.value.selected ?: error("No selected photo")
        val array=JSONArray()
        boxes.forEach { array.put(JSONObject().put("category_id",it.categoryId).put("x",it.x.toDouble()).put("y",it.y.toDouble()).put("w",it.w.toDouble()).put("h",it.h.toDouble())) }
        val action=if(mutable.value.reviewing) "reviews" else "labels"
        post("/submissions/${s.getString("id")}/$action",JSONObject().put("media_hash",s.getString("media_hash")).put("boxes",array))
        mutable.update { it.copy(selected=null,image=null) };refreshData()
    }
    fun transact(path: String,sender: ActivityResultSender)=run("Review this test-token transaction in your wallet") {
        val prepared=post("$path/prepare")
        val tx=Base64.decode(prepared.getString("transaction_base64"),Base64.DEFAULT)
        val result=adapter.transact(sender) { auth ->
            check(Base58.encode(auth.accounts.first().publicKey)==mutable.value.wallet) { "Wallet changed; sign in again." }
            signAndSendTransactions(arrayOf(tx))
        }
        check(result is TransactionResult.Success) { "Wallet did not send the transaction. Refresh to recover if it was sent." }
        val sig=result.successPayload?.signatures?.first() ?: error("Wallet returned no signature; use Recover.")
        val id=prepared.getString("id")
        var confirmed=false
        repeat(10) {
            if(!confirmed) {
                try { post("/transactions/$id/confirm",JSONObject().put("signature",Base58.encode(sig)));confirmed=true }
                catch(e: Exception) { if(it==9) throw e;delay(1500) }
            }
        }
        refreshData()
    }
    fun recover(id: String)=run("Checking finalized chain history") { post("/transactions/$id/reconcile");refreshData() }
}
