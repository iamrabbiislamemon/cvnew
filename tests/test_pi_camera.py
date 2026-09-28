"""Raspberry Pi camera support, tested without a Pi.

A stand-in for Picamera2 is put in sys.modules. It behaves like the real one where it matters here:
it lists USB webcams alongside ribbon cameras, hands frames back in B, G, R order as strided views,
and has to be closed to free the camera. The frames it returns contain real ArUco markers, so these
tests run the actual detector on "Pi camera" frames.
"""
import logging
import os
import sys
import types
import unittest
from unittest import mock

import cv2
import numpy as np
from cv2 import aruco

import tests.conftest  # noqa: F401  (puts the repo root on sys.path)
import camera.camera_source as camera_source
from aruco.detector import SUPPORTED_DICTIONARIES
from aruco.perception import Perception, display_available
from aruco.pose_estimator import PoseEstimator
from camera.camera_source import CameraError, PiCameraSource, RotatedCamera, open_camera
from config.loader import load_config

CFG = load_config()
RIBBON = {"Model": "imx708", "Id": "/base/axi/pcie@120000/rp1/i2c@88000/imx708@1a", "Location": 2}
USB = {"Model": "HD Webcam", "Id": "/base/axi/pcie@120000/rp1/usb@200000-1:1.0-046d:0825"}


def marker_scene(width, height, marker_id=102):
    """Grey frame with one ARUCO_ORIGINAL marker (plus white quiet zone) in the middle."""
    frame = np.full((height, width, 3), 90, dtype=np.uint8)
    dictionary = aruco.getPredefinedDictionary(SUPPORTED_DICTIONARIES["ARUCO_ORIGINAL"])
    tile = np.full((300, 300), 255, dtype=np.uint8)
    tile[50:250, 50:250] = aruco.generateImageMarker(dictionary, marker_id, 200)
    y0, x0 = (height - 300) // 2, (width - 300) // 2
    frame[y0:y0 + 300, x0:x0 + 300] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
    return frame


# Camera Module 3 (imx708): the 1536x864 mode is a centre crop of the sensor, the other two see all of it.
IMX708_MODES = [
    {"size": (1536, 864), "bit_depth": 10, "crop_limits": (768, 432, 3072, 1728)},
    {"size": (2304, 1296), "bit_depth": 10, "crop_limits": (0, 0, 4608, 2592)},
    {"size": (4608, 2592), "bit_depth": 10, "crop_limits": (0, 0, 4608, 2592)},
]


class FakePicamera2:
    cameras = [RIBBON]
    opened = []
    busy = False
    sensor_modes = IMX708_MODES

    def __init__(self, camera_num=0):
        if FakePicamera2.busy:
            raise RuntimeError("Failed to acquire camera: Device or resource busy")
        self.camera_num = camera_num
        self.config = None
        self.started = self.closed = False
        self.controls = {}
        self.camera_controls = {"AfMode": (0, 2, 0)}
        FakePicamera2.opened.append(self)

    @staticmethod
    def global_camera_info():
        return FakePicamera2.cameras

    def create_video_configuration(self, main, sensor=None):
        return {"main": dict(main), "sensor": sensor}

    def configure(self, config):
        self.config = config

    def camera_configuration(self):
        return self.config

    def start(self):
        self.started = True

    def set_controls(self, controls):
        self.controls.update(controls)

    def capture_array(self, name="main"):
        assert self.started and not self.closed and self.config["main"]["format"] == "RGB888"
        width, height = self.config["main"]["size"]
        padded = np.zeros((height, width + 32, 3), dtype=np.uint8)      # row stride wider than the image
        padded[:, :width] = marker_scene(width, height)
        return padded[:, :width]

    def close(self):
        self.closed = True


def fake_modules():
    libcamera = types.ModuleType("libcamera")
    libcamera.controls = types.SimpleNamespace(AfModeEnum=types.SimpleNamespace(Continuous=2))
    picamera2 = types.ModuleType("picamera2")
    picamera2.Picamera2 = FakePicamera2
    return {"picamera2": picamera2, "libcamera": libcamera}


class FakeWebcam:
    def __init__(self, index=0, width=None, height=None):
        self.index = index
        self.released = False

    def read(self):
        return marker_scene(640, 480)

    def release(self):
        self.released = True


class PiCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def setUp(self):
        FakePicamera2.cameras = [RIBBON]
        FakePicamera2.opened = []
        FakePicamera2.busy = False
        patcher = mock.patch.dict(sys.modules, fake_modules())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_auto_picks_the_ribbon_camera_with_autofocus_on(self):
        cam = open_camera("auto")
        self.assertIsInstance(cam, PiCameraSource)
        pi = FakePicamera2.opened[0]
        self.assertEqual(pi.config["main"]["size"], (1280, 720))
        self.assertEqual(pi.controls, {"AfMode": 2})
        frame = cam.read()
        self.assertEqual(frame.shape, (720, 1280, 3))
        self.assertTrue(frame.flags["C_CONTIGUOUS"])
        cam.release()
        self.assertTrue(pi.closed)

    def test_requested_resolution_is_used(self):
        cam = open_camera("picamera", width=640, height=480)
        self.assertEqual(cam.read().shape, (480, 640, 3))
        cam.release()

    def test_sensor_mode_keeps_the_full_field_of_view(self):
        open_camera("picamera").release()                           # 1280x720 fits the cropped 1536x864 mode
        self.assertEqual(FakePicamera2.opened[-1].config["sensor"], {"output_size": (2304, 1296), "bit_depth": 10})
        open_camera("picamera", width=3840, height=2160).release()
        self.assertEqual(FakePicamera2.opened[-1].config["sensor"]["output_size"], (4608, 2592))

    def test_camera_without_mode_list_lets_libcamera_choose(self):
        with mock.patch.object(FakePicamera2, "sensor_modes", []):
            cam = open_camera("picamera")
        self.assertIsNone(FakePicamera2.opened[-1].config["sensor"])
        self.assertEqual(cam.read().shape, (720, 1280, 3))
        cam.release()

    def test_aruco_markers_are_detected_on_pi_camera_frames(self):
        vision = Perception(open_camera("picamera"), CFG, PoseEstimator(None), display=False)
        try:
            det = vision.look().find("product", 102)
        finally:
            vision.close()
        self.assertIsNotNone(det)
        self.assertEqual(det.marker_size_cm, 5.0)
        self.assertIsNotNone(det.approx_distance_cm)

    def test_second_ribbon_camera_skips_usb_cameras_in_the_libcamera_list(self):
        FakePicamera2.cameras = [USB, RIBBON, dict(RIBBON, Model="imx219")]
        open_camera("picamera", index=1).release()
        self.assertEqual(FakePicamera2.opened[-1].camera_num, 2)

    def test_auto_falls_back_to_the_webcam_when_only_usb_cameras_are_listed(self):
        FakePicamera2.cameras = [USB]
        with mock.patch.object(camera_source, "WebcamSource", FakeWebcam):
            cam = open_camera("auto", index=8)
        self.assertIsInstance(cam, FakeWebcam)
        self.assertEqual(cam.index, 8)
        self.assertEqual(FakePicamera2.opened, [])

    def test_auto_falls_back_to_the_webcam_without_picamera2(self):
        with mock.patch.dict(sys.modules, {"picamera2": None}):      # None makes the import fail
            with mock.patch.object(camera_source, "WebcamSource", FakeWebcam):
                self.assertIsInstance(open_camera("auto"), FakeWebcam)
            with self.assertRaisesRegex(CameraError, "python3-picamera2"):
                open_camera("picamera")

    def test_missing_ribbon_camera_is_a_clear_error(self):
        FakePicamera2.cameras = []
        with self.assertRaisesRegex(CameraError, "rpicam-hello --list-cameras"):
            open_camera("picamera")

    def test_busy_camera_is_a_camera_error(self):
        FakePicamera2.busy = True
        with self.assertRaisesRegex(CameraError, "Close any other program"):
            open_camera("picamera")

    def test_rotation_turns_frames_and_releases_the_pi_camera(self):
        cam = open_camera("picamera", width=640, height=480, rotate=90)
        self.assertIsInstance(cam, RotatedCamera)
        self.assertEqual(cam.read().shape, (640, 480, 3))
        cam.release()
        self.assertTrue(FakePicamera2.opened[0].closed)

    def test_bad_backend_or_rotation_opens_nothing(self):
        with self.assertRaises(CameraError):
            open_camera("gopro")
        with self.assertRaises(CameraError):
            open_camera("picamera", rotate=45)
        self.assertEqual(FakePicamera2.opened, [])


class DisplayTests(unittest.TestCase):
    def test_linux_without_a_desktop_has_no_display(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(display_available())
        with mock.patch.object(sys, "platform", "linux"), mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True):
            self.assertTrue(display_available())
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            self.assertTrue(display_available())

    def test_windows_always_has_a_display(self):
        with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(display_available())


if __name__ == "__main__":
    unittest.main()
