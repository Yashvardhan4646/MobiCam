import os
import sys
import time
import urllib.request
import threading
from pathlib import Path
import cv2
import numpy as np

if sys.platform == "win32":
    import winsound

BASE_DIR = Path(__file__).parent.resolve()
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)

PROTOTXT_URL = "https://raw.githubusercontent.com/djmv/MobilNet_SSD_opencv/master/MobileNetSSD_deploy.prototxt"
MODEL_URL = "https://raw.githubusercontent.com/djmv/MobilNet_SSD_opencv/master/MobileNetSSD_deploy.caffemodel"

PROTOTXT_PATH = MODELS_DIR / "MobileNetSSD_deploy.prototxt"
MODEL_PATH = MODELS_DIR / "MobileNetSSD_deploy.caffemodel"

MOBILENET_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair",
    "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]

np.random.seed(42)
COLORS = np.random.randint(0, 255, size=(len(MOBILENET_CLASSES), 3), dtype="uint8")


class AIEngine:
    def __init__(self):
        self.net = None
        self.use_hog_fallback = False
        self.hog = None
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=30, detectShadows=False)
        self.last_sound_time = 0
        self.is_downloading = False

        # Cache last detection results for smooth high FPS rendering
        self.cached_detections = []
        self.cached_alert = False
        self.cached_msg = ""

        # Threading for non-blocking AI inference
        self.lock = threading.Lock()
        self.is_processing = False
        self.frame_counter = 0

        # Load MobileNet-SSD model
        self._load_model()

        # Fallback HOG
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def _load_model(self):
        try:
            # Check if model files exist and are not corrupted (> 1MB)
            if not PROTOTXT_PATH.exists() or not MODEL_PATH.exists() or MODEL_PATH.stat().st_size < 1000000:
                print("Downloading AI Object Detection model (MobileNet-SSD ~23MB)...")
                self.is_downloading = True
                urllib.request.urlretrieve(PROTOTXT_URL, str(PROTOTXT_PATH))
                urllib.request.urlretrieve(MODEL_URL, str(MODEL_PATH))
                self.is_downloading = False
                print("AI Model download complete!")

            if PROTOTXT_PATH.exists() and MODEL_PATH.exists():
                self.net = cv2.dnn.readNetFromCaffe(str(PROTOTXT_PATH), str(MODEL_PATH))
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                print("MobileNet-SSD DNN engine loaded successfully!")
        except Exception as e:
            print(f"Warning: MobileNet-SSD model load error ({e}). Using optimized HOG People Detector.")
            self.use_hog_fallback = True
            self.is_downloading = False

    def trigger_alarm_async(self):
        now = time.time()
        if now - self.last_sound_time > 3.0:
            self.last_sound_time = now
            threading.Thread(target=self._play_sound, daemon=True).start()

    def _play_sound(self):
        try:
            if sys.platform == "win32":
                winsound.Beep(1200, 300)
            else:
                sys.stdout.write('\a')
                sys.stdout.flush()
        except Exception:
            pass

    def process_frame(self, frame, mode="Off", conf_threshold=0.5, play_alarm=True, target_filter="All"):
        """
        High performance frame processing with non-blocking AI inference and bounding box caching.
        Yields 30+ FPS video rendering.
        """
        if mode == "Off":
            return frame, [], False, ""

        self.frame_counter += 1
        h, w = frame.shape[:2]
        annotated = frame.copy()

        # Run AI inference every 2nd frame or use background thread if not busy
        if not self.is_processing and (self.frame_counter % 2 == 0):
            self.is_processing = True
            threading.Thread(
                target=self._run_inference_worker,
                args=(frame.copy(), mode, conf_threshold, play_alarm, target_filter),
                daemon=True
            ).start()

        # Retrieve cached results
        with self.lock:
            detections = list(self.cached_detections)
            alert_triggered = self.cached_alert
            alert_msg = self.cached_msg

        # Draw cached detections on the current frame at 30+ FPS
        for det in detections:
            startX, startY, bw, bh = det["box"]
            endX, endY = startX + bw, startY + bh
            label_name = det["class"]
            confidence = det["conf"]
            color = det["color"]

            cv2.rectangle(annotated, (startX, startY), (endX, endY), color, 2)
            label_text = f"{label_name.upper()} {confidence * 100:.0f}%"

            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(annotated, (startX, startY - 20), (startX + tw + 6, startY), color, -1)
            cv2.putText(annotated, label_text, (startX + 3, startY - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        if alert_triggered and mode == "Security Motion Alert":
            cv2.rectangle(annotated, (0, 0), (w, 35), (0, 0, 220), -1)
            cv2.putText(annotated, f"SECURITY ALERT: {alert_msg}", (15, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        return annotated, detections, alert_triggered, alert_msg

    def _run_inference_worker(self, frame, mode, conf_threshold, play_alarm, target_filter):
        try:
            h, w = frame.shape[:2]
            detections = []
            alert_triggered = False
            alert_msg = ""
            person_detected = False

            if self.net is not None:
                blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
                self.net.setInput(blob)
                nn_out = self.net.forward()

                for i in range(nn_out.shape[2]):
                    confidence = float(nn_out[0, 0, i, 2])
                    if confidence >= conf_threshold:
                        idx = int(nn_out[0, 0, i, 1])
                        label_name = MOBILENET_CLASSES[idx] if idx < len(MOBILENET_CLASSES) else "object"

                        if target_filter == "Person Only" and label_name != "person":
                            continue
                        elif target_filter == "Pets" and label_name not in ["cat", "dog", "bird"]:
                            continue
                        elif target_filter == "Vehicles" and label_name not in ["car", "bus", "motorbike", "bicycle", "train"]:
                            continue

                        if label_name == "person":
                            person_detected = True

                        box = nn_out[0, 0, i, 3:7] * np.array([w, h, w, h])
                        startX, startY, endX, endY = box.astype("int")
                        startX, startY = max(0, startX), max(0, startY)
                        endX, endY = min(w, endX), min(h, endY)
                        color = [int(c) for c in COLORS[idx]]

                        detections.append({
                            "class": label_name,
                            "conf": confidence,
                            "box": (startX, startY, endX - startX, endY - startY),
                            "color": color
                        })

            elif self.hog is not None:
                # Optimized downscaled HOG for fast processing
                small = cv2.resize(frame, (320, 240))
                scale_x, scale_y = w / 320.0, h / 240.0
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                boxes, weights = self.hog.detectMultiScale(gray, winStride=(8, 8), padding=(4, 4), scale=1.1)

                for (x, y, bw, bh), weight in zip(boxes, weights):
                    if weight >= conf_threshold * 0.6:
                        person_detected = True
                        bx, by, bbw, bbh = int(x * scale_x), int(y * scale_y), int(bw * scale_x), int(bh * scale_y)
                        detections.append({
                            "class": "person",
                            "conf": float(weight),
                            "box": (bx, by, bbw, bbh),
                            "color": (0, 255, 0)
                        })

            # Motion detection check
            if mode == "Security Motion Alert":
                fg_mask = self.bg_subtractor.apply(frame)
                motion_pixels = cv2.countNonZero(fg_mask)
                motion_ratio = motion_pixels / (w * h)

                if motion_ratio > 0.03 or person_detected:
                    alert_triggered = True
                    alert_msg = "PERSON DETECTED" if person_detected else "MOTION DETECTED"
                    if play_alarm:
                        self.trigger_alarm_async()

            elif person_detected and play_alarm:
                alert_triggered = True
                alert_msg = "PERSON DETECTED"
                self.trigger_alarm_async()

            with self.lock:
                self.cached_detections = detections
                self.cached_alert = alert_triggered
                self.cached_msg = alert_msg

        except Exception as e:
            print(f"AI Worker error: {e}")
        finally:
            self.is_processing = False
