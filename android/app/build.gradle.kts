plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "ai.loosh.tapfarm"
    compileSdk = 35

    defaultConfig {
        applicationId = "ai.loosh.tapfarm"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-spike"

        // Point this at your machine's LAN IP when running the backend locally;
        // the Seeker cannot reach your laptop's localhost. Override without
        // editing the file: -PtapfarmApiBase=http://192.168.1.20:8000
        val apiBase = (project.findProperty("tapfarmApiBase") as String?)
            ?: "http://10.0.2.2:8000"
        buildConfigField("String", "API_BASE", "\"$apiBase\"")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.mwa.clientlib.ktx)
    implementation(libs.okhttp)
}
