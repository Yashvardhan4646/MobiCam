# 📱 AI Mobile Camera & Security System

A high-performance, **zero-latency** AI security camera system that turns any smartphone into an intelligent **AI surveillance camera** over Wi-Fi, USB. Includes a native open-source Android app (`MyCam Server`) and a Python desktop client with real-time AI object detection.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![OpenCV](https://img.shields.io/badge/OpenCV-4.5%2B-green.svg)
![Android](https://img.shields.io/badge/Android-Kotlin%20%2F%20CameraX-3DDC84.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## ✨ System Features

- ⚡ **Zero-Latency Video Pipeline**: Custom background frame grabber (`FastStreamReader`) flushes socket buffers continuously to eliminate network lag.
- 🤖 **Real-Time AI Vision**: MobileNet-SSD Deep Neural Network detects people, pets, vehicles, and objects with bounding box overlays.
- 📸 **Auto Person Snapshots**: Instantly captures high-resolution screenshots (`.jpg`) when a person enters the camera field of view.
- 🎥 **Auto 5-Second Video Clips**: Automatically records 5-second `.mp4` video clips upon person detection.
- 📱 **Native Open-Source Android App**: Includes `MyCamServer.apk` built with Android CameraX and Jetpack Compose.
- 🌐 **Global Remote Access**: Stream your phone camera from anywhere in the world over 4G/5G using Tailscale VPN mesh.
- 🔊 **Security Audio Alarms**: Triggers audible sound alerts on person detection or motion events.
- 🔄 **Transform Controls**: Rotate camera (90°, 180°, 270°), flip horizontally/vertically, and customize confidence thresholds.

---

## 🏗 System Architecture

```
┌───────────────────────────┐                ┌──────────────────────────────┐
│   Android Phone (Camera)  │  Wi-Fi / 4G    │   Computer (Python Client)   │
│ ┌───────────────────────┐ │  MJPEG Stream  │ ┌──────────────────────────┐ │
│ │  MyCam Server / App   │ ├───────────────►│ │  FastStreamReader (0-lag)│ │
│ │  (CameraX + HTTP:8080)│ │                │ └────────────┬─────────────┘ │
│ └───────────────────────┘ │                │              ▼               │
└───────────────────────────┘                │ ┌──────────────────────────┐ │
                                             │ │ AI Object Detection DNN  │ │
                                             │ └────────────┬─────────────┘ │
                                             │              ▼               │
                                             │ ┌──────────────────────────┐ │
                                             │ │ GUI Viewport / Auto Recs │ │
                                             │ └──────────────────────────┘ │
                                             └──────────────────────────────┘
```

---

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yashvardhan4646/MobiCam.git
cd MobiCam
```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

---

## 🚀 Quick Start Guide

### 📱 STEP 1: Set Up Your Mobile Phone Camera

#### Option A: MyCam Server (Official Open-Source APK) 🌟 Recommended
1. Download **[`MyCamServer.apk`](releases/MyCamServer.apk)** directly from the `releases/` folder or GitHub Releases.
2. Install the `.apk` on your Android phone and grant Camera permissions.
3. Open **MyCam Server** and tap **▶ START STREAM**. Note your displayed IP (e.g., `http://192.168.1.100:8080/video`).

#### Option B: DroidCam (Android / iOS)
1. Install **DroidCam** from Google Play Store or Apple App Store.
2. Open DroidCam. Note the **Wi-Fi IP** (e.g., `192.168.1.100`) and **Port** (`4747`).

#### Option C: IP Webcam (Android)
1. Install **IP Webcam** from Google Play Store.
2. Scroll down and tap **"Start server"**. Note the IP address displayed (e.g., `http://192.168.1.100:8080`).

---

### 💻 STEP 2: Launch the Computer Viewer

#### Graphical Mode (GUI - Recommended)
```bash
python main.py
```
1. Select your app preset (e.g., `DroidCam (WiFi)` or `IP Webcam (Android)`).
2. Enter your Phone's **IP Address** and **Port**.
3. Click **▶ Start Stream**.

##### 🌟 GUI Capabilities:
- 📸 **Manual Snapshot**: Click to instantly take photos saved to `snapshots/`.
- 🔴 **Manual Recording**: Click to record continuous `.mp4` video saved to `recordings/`.
- 🤖 **AI Filters**: Filter detection by *Person Only*, *Pets*, or *Vehicles*.
- 📸 **Auto 5s Video & Snap on Person**: Toggle automatic capture when a person appears.

#### Command Line Mode (CLI - Minimal Window)
```bash
python cli_cam.py 192.168.1.100 4747
```
- Press **'s'** to take a manual snapshot.
- Press **'q'** to quit.

---
## 🕒 24/7 Surveillance Setup Guidelines

To keep your mobile camera running continuously as a non-stop security camera:

1. **Fix Mobile IP (Static IP)**: Set your Wi-Fi settings on your phone from DHCP to **Static** so the router doesn't change your IP address.
2. **Disable Battery Saver**: Set your camera app battery usage setting to **Unrestricted** (Don't optimize).
3. **Enable Screen Dimmer**: Use the built-in **Dim Screen** button in `MyCam Server` or DroidCam to prevent screen burn-in and phone overheating.
4. **Resolution Tip**: Set video stream resolution to **720p or 480p @ 30 FPS** to reduce thermal load during long runs.

---

## 🔨 Building the Android App from Source

If you wish to modify or rebuild the Android app `.apk`:

1. Navigate to the `/android` directory:
   ```bash
   cd android
   ```
2. Build the debug APK using Gradle:
   - **Windows**: `build_apk.bat` or `gradlew.bat assembleDebug`
   - **Linux / macOS**: `./gradlew assembleDebug`
3. Compiled APK will be output at `android/app/build/outputs/apk/debug/app-debug.apk`.

---

## 📁 Project Directory Structure

```
.
├── main.py              # Main GUI application & AI processing loop
├── ai_engine.py         # MobileNet-SSD & HOG detection engine
├── cli_cam.py           # Minimal command-line OpenCV viewer
├── config.json          # Application configuration settings
├── requirements.txt     # Python requirements manifest
├── .gitignore           # Git ignore rules
├── build_apk.bat        # Helper script for compiling Android APK
│
├── releases/            # Pre-compiled release packages
│   └── MyCamServer.apk  # Official compiled Android APK (13.8 MB)
│
├── android/             # Native Android App source code (Kotlin + CameraX)
│   ├── app/src/main/    # AndroidManifest, MainActivity.kt, MjpegStreamServer.kt
│   └── build.gradle.kts # Android dependencies and build configuration
│
├── models/              # MobileNet-SSD caffe model binaries
├── snapshots/           # Saved snapshots (.jpg)
├── recordings/          # Saved video recordings & 5s auto-clips (.mp4)
└── events/              # Saved security alert images
```

---

## 📜 License

This project is licensed under the **MIT License**. Free for personal and commercial use.

---

## ⚠️ Disclaimer

This software is provided for educational, research, and personal home monitoring purposes only. 
- **Privacy & Compliance**: Users are solely responsible for complying with local, state, and national laws regarding video surveillance and privacy. Do not use this software for unauthorized recording or invasion of privacy.
- **No Warranty**: The developer assumes no liability for missed motion alerts, hardware damage, data loss, or improper usage of the stream. Use at your own risk.
