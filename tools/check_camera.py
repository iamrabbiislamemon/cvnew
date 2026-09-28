"""Live camera + ArUco check: run this first on the Raspberry Pi, before main.py.

  python tools/check_camera.py --list                  # which cameras this machine has
  python tools/check_camera.py                         # open the camera main.py would use, detect markers for 20 s
  python tools/check_camera.py --seconds 0             # keep running until Q/ESC in the window (or Ctrl+C)
  python tools/check_camera.py --save snapshot.jpg     # also save the last frame (handy over SSH)
  python tools/check_camera.py --camera-backend webcam --camera 8   # a USB webcam (/dev/video8) instead

It uses the same camera, detector, config and calibration as main.py, so a marker reported here is
exactly what the robot will see. Exit code 0 when the camera delivered frames, 3 when it did not.
"""
import argparse
import glob
import logging
import os
import sys
import time

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from aruco.calibration import DEFAULT_CALIBRATION_PATH, load_if_available  # noqa: E402
from aruco.perception import Perception, UserAbort, display_available  # noqa: E402
from aruco.pose_estimator import PoseEstimator  # noqa: E402
from camera.camera_source import (CAMERA_BACKENDS, CAMERA_ROTATIONS, CameraError, CameraSource,  # noqa: E402
                                  list_pi_cameras, open_camera)
from config.loader import DEFAULT_CONFIG_PATH, ConfigError, load_config  # noqa: E402

log = logging.getLogger("warehouse")
PROGRESS_EVERY_S = 5.0


class _KeepLastFrame(CameraSource):
    """Passes frames through and keeps the latest one, for --save and the frame size in the summary."""

    def __init__(self, source: CameraSource):
        self._source = source
        self.last = None

    def read(self):
        frame = self._source.read()
        if frame is not None:
            self.last = frame.copy()        # before Perception draws its overlay on it
        return frame

    def release(self) -> None:
        self._source.release()


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="list the cameras on this machine and exit")
    p.add_argument("--camera", type=int, default=0, help="same as main.py --camera")
    p.add_argument("--camera-backend", choices=CAMERA_BACKENDS, default="auto", help="same as main.py")
    p.add_argument("--rotate", type=int, choices=CAMERA_ROTATIONS, default=0, help="same as main.py")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--seconds", type=float, default=20.0, help="how long to run; 0 = until Q/ESC or Ctrl+C")
    p.add_argument("--no-display", action="store_true", help="no preview window")
    p.add_argument("--save", metavar="PATH", help="write the last camera frame to this image file")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--calibration-file", default=DEFAULT_CALIBRATION_PATH)
    return p.parse_args()


def list_cameras() -> None:
    print("Raspberry Pi ribbon cameras (--camera-backend picamera --camera N):")
    try:
        cameras = list_pi_cameras()
        for index, (_, info) in enumerate(cameras):
            print("  {}: {}  [{}]".format(index, info.get("Model", "?"), info.get("Id", "")))
        if not cameras:
            print("  none detected")
    except CameraError as e:
        print("  unavailable: {}".format(e))
    devices = sorted(glob.glob("/dev/video*"), key=lambda d: (len(d), d))      # video2 before video10
    if devices:
        print("V4L2 video devices (--camera-backend webcam --camera N, N from /dev/videoN):")
        for device in devices:
            try:
                with open("/sys/class/video4linux/{}/name".format(os.path.basename(device))) as f:
                    name = f.read().strip()
            except OSError:
                name = "?"
            # On a Pi 5 most nodes belong to the camera/ISP hardware (rp1-cfe, pispbe), not to a webcam.
            print("  {}  {}".format(device, name))
    elif not sys.platform.startswith("linux"):
        print("Webcams: use --camera-backend webcam --camera 0, 1, ... (OpenCV index)")


def label(config, det) -> str:
    """Short text drawn next to the marker in the preview window."""
    if det.kind == "product":
        product = config.products.get_by_marker(det.marker_id)
        return "{} ({})".format(product.name if product else "unregistered product", det.marker_id)
    if det.kind == "shelf":
        shelf = config.shelves.get_by_marker(det.marker_id)
        return "Shelf {} ({})".format(shelf.shelf_id if shelf else "unregistered", det.marker_id)
    return "not a project marker {}".format(det.marker_id)


def describe(config, det) -> str:
    """One console line for the first time a marker is seen."""
    text = "marker {} [{}]".format(det.marker_id, det.dictionary)
    if det.kind == "product":
        product = config.products.get_by_marker(det.marker_id)
        text += ": product {}".format("{} -> shelf {}".format(product.name, product.shelf_id) if product
                                      else "(ID in the product range, but not registered)")
    elif det.kind == "shelf":
        shelf = config.shelves.get_by_marker(det.marker_id)
        text += ": shelf {}".format(shelf.shelf_id if shelf else "(ID in the shelf range, but not registered)")
    else:
        text += ": not a project marker (dictionary/ID outside config/locations.json)"
        return text
    if det.pose is not None:
        text += ", distance {:.1f} cm (calibrated)".format(det.pose.distance_cm)
    elif det.approx_distance_cm is not None:
        text += ", ~{:.0f} cm (rough, uncalibrated)".format(det.approx_distance_cm)
    return text + ", {:.0f} px wide".format(det.side_px)


def run(args) -> int:
    config = load_config(args.config)
    calibration = load_if_available(args.calibration_file)
    print("Calibration: {}".format("{} ({}x{})".format(args.calibration_file, *calibration.image_size)
                                   if calibration else "none (distances are rough estimates)"))
    show = not args.no_display and display_available()
    if not show and not args.no_display:
        print("No screen found (running over SSH?): no preview window. Use --save to look at a frame.")

    camera = _KeepLastFrame(open_camera(args.camera_backend, args.camera, args.width, args.height, args.rotate))
    vision = Perception(camera, config, PoseEstimator(calibration), display=show,
                        labeler=lambda det: label(config, det))
    vision.set_status("camera check - Q/ESC quits")
    print("Show product and shelf markers to the camera{}.".format(
        "" if args.seconds == 0 else " (running {:.0f} s)".format(args.seconds)))

    seen = {}
    frames = 0
    start = last_note = time.monotonic()
    try:
        while args.seconds == 0 or time.monotonic() - start < args.seconds:
            observation = vision.look()
            frames = observation.frame_index
            for det in observation.detections:
                key = (det.dictionary, det.marker_id)
                if key not in seen:
                    print("  SEEN {}".format(describe(config, det)))
                seen[key] = seen.get(key, 0) + 1
            now = time.monotonic()
            if now - last_note >= PROGRESS_EVERY_S:
                last_note = now
                in_view = ", ".join(str(d.marker_id) for d in observation.detections) or "none"
                print("  ... {:.0f} s, {:.1f} fps, markers in view: {}".format(now - start, frames / (now - start),
                                                                          in_view))
    except (UserAbort, KeyboardInterrupt):
        pass
    finally:
        vision.close()

    elapsed = time.monotonic() - start
    if camera.last is None:
        print("\nNo frames came from the camera.")
        return 3
    if args.save:
        cv2.imwrite(args.save, camera.last)
        print("Saved the last frame to {}".format(args.save))
    height, width = camera.last.shape[:2]
    print("\nCamera OK: {} frames in {:.1f} s ({:.1f} fps) at {}x{}".format(
        frames, elapsed, frames / elapsed if elapsed else 0.0, width, height))
    if seen:
        print("Markers seen: " + ", ".join("{} x{}".format(marker_id, count)
                                           for (_, marker_id), count in sorted(seen.items(), key=lambda s: s[0][1])))
    else:
        print("No markers seen. Check: good light, the white border around each printed marker, focus "
              "(--save a frame and look at it), and that it was printed from markers/pdf at 100% size.")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = parse_args()
    if args.list:
        list_cameras()
        return 0
    try:
        return run(args)
    except CameraError as e:
        print("Camera error: {}".format(e))
        return 3
    except ConfigError as e:
        print("Error: {}".format(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
