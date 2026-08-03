"""
Minimal Mobile Camera Streamer in Python (OpenCV)
Run this script to view your phone's camera stream directly with near zero latency.

Usage:
  python cli_cam.py [IP_ADDRESS] [PORT]

Example:
  python cli_cam.py 192.168.1.7 4747
"""

import os
import sys
import time
import threading
import cv2

# Set FFmpeg flags for zero-latency streaming
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "fflags;nobuffer|flags;low_delay|framedrop|max_delay;0"


class UltraFastGrabber:
    def __init__(self, cap):
        self.cap = cap
        self.latest_frame = None
        self.stopped = False
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._update, daemon=True).start()
        return self

    def _update(self):
        while not self.stopped:
            if not self.cap or not self.cap.isOpened():
                time.sleep(0.005)
                continue
            try:
                grabbed = self.cap.grab()
                if grabbed:
                    ret, frame = self.cap.retrieve()
                    if ret and frame is not None:
                        with self.lock:
                            self.latest_frame = frame
                else:
                    time.sleep(0.002)
            except Exception:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            if self.latest_frame is None:
                return False, None
            return True, self.latest_frame

    def stop(self):
        self.stopped = True
        if self.cap:
            self.cap.release()


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.100"
    port = sys.argv[2] if len(sys.argv) > 2 else "4747"

    # Possible endpoints for DroidCam / IP Webcam
    endpoints = [
        f"http://{ip}:{port}/mjpegfeed?640x480",
        f"http://{ip}:{port}/video?640x480",
        f"http://{ip}:{port}/video",
        f"http://{ip}:{port}/mjpegfeed",
        f"http://{ip}:{port}/live"
    ]

    temp_cap = None
    connected_url = ""
    
    for url in endpoints:
        print(f"Trying to connect to: {url} ...")
        c = cv2.VideoCapture(url)
        c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if c.isOpened():
            ret, frame = c.read()
            if ret and frame is not None:
                temp_cap = c
                connected_url = url
                print(f"✅ Successfully connected to: {connected_url}")
                break
            else:
                c.release()

    if temp_cap is None:
        print(f"\n❌ Error: Unable to connect to DroidCam/Camera at {ip}:{port}")
        print("Please verify:")
        print(" 1. DroidCam app is open on your mobile screen.")
        print(" 2. Both mobile and laptop are on the exact same Wi-Fi network.")
        print(f" 3. Try opening http://{ip}:{port}/video in your browser on PC.")
        return

    grabber = UltraFastGrabber(temp_cap).start()

    print("\nPress 'q' on the video window to Quit.")
    print("Press 's' to take a Snapshot.\n")

    count = 0
    while True:
        ret, frame = grabber.read()
        if not ret or frame is None:
            time.sleep(0.005)
            continue

        cv2.imshow("Mobile Camera Stream (Zero-Latency)", frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            count += 1
            filename = f"cli_snapshot_{count}.jpg"
            cv2.imwrite(filename, frame)
            print(f"📸 Saved snapshot to {filename}")

    grabber.stop()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
