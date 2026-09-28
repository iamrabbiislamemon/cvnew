#!/usr/bin/env bash
# One-time setup of this project on a Raspberry Pi 5 (Raspberry Pi OS 64-bit, Bookworm or Trixie).
# Run it from the project folder:      bash pi_setup.sh
# Safe to run again: it only adds what is missing. See README_PI.md for what each step is for.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n==> %s\n' "$*"; }

if [ "$(uname -m)" != "aarch64" ]; then
    echo "This needs 64-bit Raspberry Pi OS (aarch64), but this system is $(uname -m)."
    echo "Flash 'Raspberry Pi OS (64-bit)' with Raspberry Pi Imager and try again."
    exit 1
fi

say "Installing system packages: Picamera2 (Pi camera library), Python venv support, OpenGL runtime, V4L2 tools"
sudo apt update
sudo apt install -y --no-install-recommends python3-venv python3-picamera2 python3-numpy libgl1 v4l-utils

# A .venv zipped up on Windows (it has Scripts\ instead of bin/) cannot run here.
if [ -d .venv ] && [ ! -x .venv/bin/python ]; then
    say "Removing the .venv copied from Windows (it only works on Windows)"
    rm -rf .venv
fi
# Picamera2 only comes from apt, so the venv must see the system packages.
if [ -x .venv/bin/python ] && ! grep -q "include-system-site-packages = true" .venv/pyvenv.cfg; then
    say "Recreating .venv: it was made without --system-site-packages and cannot see Picamera2"
    rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
    say "Creating .venv (with access to the system Picamera2)"
    python3 -m venv --system-site-packages .venv
fi

# Picamera2 is compiled against the system numpy. If pip replaced it (e.g. numpy 2 over Bookworm's 1.24),
# importing Picamera2 fails with "numpy.dtype size changed". Pin numpy to the system version for every pip call.
SYSTEM_NUMPY=$(/usr/bin/python3 -c 'import numpy; print(numpy.__version__)')
echo "numpy==${SYSTEM_NUMPY}" > .venv/pi-constraints.txt

say "Installing OpenCV 4.7+ into .venv (numpy stays at the system's ${SYSTEM_NUMPY})"
.venv/bin/python -m pip install --upgrade pip
# --only-binary: never compile anything from source (OpenCV would take hours on a Pi); pip picks the newest
# ready-made wheel that works with the pinned numpy instead (4.11 on Bookworm's numpy 1.24, 5.x on numpy 2).
.venv/bin/python -m pip install --only-binary=:all: -c .venv/pi-constraints.txt "opencv-python>=4.7"

say "Installing the marker-PDF tools and pytest (optional)"
.venv/bin/python -m pip install --only-binary=:all: -c .venv/pi-constraints.txt "reportlab>=4.0" "pymupdf>=1.24" pytest \
    || echo "WARNING: reportlab/pymupdf/pytest did not install. Only tools/generate_marker_pdf.py and its test need them."

say "Checking the installation"
.venv/bin/python - <<'EOF'
import cv2
import numpy
print("OpenCV {} | numpy {}".format(cv2.__version__, numpy.__version__))
if not hasattr(cv2.aruco, "ArucoDetector"):
    raise SystemExit("OpenCV {} is too old: this project needs 4.7 or newer.".format(cv2.__version__))
from picamera2 import Picamera2
print("Picamera2 OK")
EOF
.venv/bin/python tools/check_camera.py --list

if [ -f config/camera_calibration.json ]; then
    echo
    echo "NOTE: config/camera_calibration.json exists. A calibration made on the laptop is WRONG for the Pi camera."
    echo "      If it came from the laptop, move it away and calibrate on the Pi (README_PI.md, step 8):"
    echo "          mv config/camera_calibration.json config/camera_calibration.laptop.json"
fi

cat <<EOF

Setup finished. In every new terminal:
    cd $PWD
    source .venv/bin/activate

Then:
    python tools/check_camera.py          # camera + ArUco detection check (step 7 of README_PI.md)
    python main.py --pick 102             # the full pick-and-place workflow
EOF
