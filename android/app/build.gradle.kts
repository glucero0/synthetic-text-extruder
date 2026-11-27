plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val sharedPythonStagingDir = layout.buildDirectory.dir("generated/shared_python_src")

val syncSharedPython by tasks.registering(Sync::class) {
    from(rootProject.file("../synthetic_text_extruder")) {
        exclude("**/__pycache__/**", "**/*.pyc", "**/*.pyo")
    }
    into(sharedPythonStagingDir.map { it.dir("synthetic_text_extruder") })
}

android {
    namespace = "com.synthetictextextruder.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.synthetictextextruder.app"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("ANDROID_VERSION_CODE")?.toIntOrNull()) ?: 1
        versionName = System.getenv("ANDROID_VERSION_NAME") ?: "0.1.0-android"

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    val keystorePath = System.getenv("ANDROID_KEYSTORE_PATH")
    val hasReleaseSigning = !keystorePath.isNullOrBlank() && file(keystorePath).isFile

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(keystorePath!!)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD") ?: ""
                keyAlias = System.getenv("ANDROID_KEY_ALIAS") ?: ""
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD") ?: ""
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (hasReleaseSigning) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isDebuggable = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources {
            excludes += setOf("META-INF/LICENSE*", "META-INF/NOTICE*")
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        val pyBin = System.getenv("CHAQUOPY_BUILD_PYTHON")
        if (!pyBin.isNullOrBlank()) {
            buildPython(pyBin)
        }
        pip {
            options("--extra-index-url", "https://pypi.flet.dev")
            install("PyYAML==6.0.3")
            install("pillow==13.0.0")
            install("reportlab==5.1.0")
            install("cffi==2.1.1")
            install("cryptography==43.0.1")
            install("pydantic-core==2.50.4")
            install("pydantic==2.14.3")
            install("google-genai==2.23.0")
            install("google-api-python-client==2.201.0")
            install("google-auth-oauthlib==1.5.0")
            install("youtube-transcript-api==1.2.5")
            install("defusedxml==0.7.1")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(sharedPythonStagingDir)
        }
    }
}

tasks.configureEach {
    if (name.startsWith("merge") && name.contains("PythonSources")) {
        dependsOn(syncSharedPython)
    }
}

dependencies {
    val media3Version = "1.8.0"
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.window:window:1.3.0")
    implementation("androidx.browser:browser:1.8.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("androidx.media3:media3-common:$media3Version")
    implementation("androidx.media3:media3-exoplayer:$media3Version")
    implementation("androidx.media3:media3-transformer:$media3Version")
    implementation("androidx.media3:media3-effect:$media3Version")
    implementation("androidx.media3:media3-muxer:$media3Version")
    implementation("androidx.media3:media3-extractor:$media3Version")
    implementation("org.jellyfin.media3:media3-ffmpeg-decoder:1.8.0+1")
}
