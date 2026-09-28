# Running the project on a Raspberry Pi 5

Everything that works on the laptop works on the Pi. That covers live ArUco detection, the full `--pick` workflow, calibration, `--synthetic`, `--show-map`, the marker tools and the tests.

The camera can be a Raspberry Pi ribbon camera (Camera Module 3, Camera Module 2, HQ camera) or a USB webcam. It is picked automatically, so the commands are the same as on the laptop.

Short version, once the files are on the Pi:

```bash
cd ~/ArUcoMarkerDetector
sed -i 's/\r$//' pi_setup.sh          # only needed if the zip was made on Windows
bash pi_setup.sh                      # one time, ~5-10 min
source .venv/bin/activate             # every new terminal
python tools/check_camera.py          # camera + ArUco check
python main.py --pick 102             # the real workflow
```

The rest of this file explains each step.

---

## 0. What you need

| Item | Notes |
|---|---|
| Raspberry Pi 5 + official 27 W USB-C power supply | A weak supply causes camera drop-outs. |
| microSD card, 16 GB+, with **Raspberry Pi OS (64-bit)** | Flash it with Raspberry Pi Imager. Use the **Desktop** version if you want the preview window and calibration. In Imager's settings, set a username, password, Wi-Fi and enable SSH. |
| Camera | **Camera Module 3** is recommended because it has autofocus. Camera Module 2, the HQ camera and USB webcams also work. |
| **Raspberry Pi 5 camera cable** (22-pin to 15-pin) | The Pi 5 camera port is the small 22-pin type, so the cable that comes in the Camera Module box **does not fit** a Pi 5. |
| Screen: monitor + keyboard, or VNC | Needed for the preview window and for `--calibrate`. SSH alone is enough for running without a window. |
| Printed markers | Print from `markers/pdf/` at **100% / Actual Size**, the same as for the laptop. |

---

## 1. On the laptop: make the zip

Leave out `.venv`. It is the Windows Python environment and cannot run on the Pi. Also leave out the laptop's camera calibration, which is wrong for the Pi camera.

In **PowerShell** (Windows 10/11 has `tar` built in):

```powershell
cd E:\Micro
tar -a -c -f smart-shelf.zip --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=camera_calibration.json ArUcoMarkerDetector
```

This creates `E:\Micro\smart-shelf.zip`.

If you zip with File Explorer instead (right-click the folder, **Send to**, **Compressed (zipped) folder**), that also works. It is just bigger, and `pi_setup.sh` deletes the copied Windows `.venv` on the Pi.

---

## 2. Copy the zip to the Pi

Pick one of these options.

- **USB stick:** copy `smart-shelf.zip` onto it and plug it into the Pi. On the Pi desktop, drag the file into your home folder, or in a terminal:
  ```bash
  cp /media/$USER/*/smart-shelf.zip ~/
  ```
- **Over the network (scp)**, from PowerShell on the laptop. Use the username and hostname you set in Raspberry Pi Imager:
  ```powershell
  scp E:\Micro\smart-shelf.zip <username>@<hostname>.local:~/
  ```
  Example: `scp E:\Micro\smart-shelf.zip pi@raspberrypi.local:~/`

---

## 3. Unzip on the Pi

Open a terminal on the Pi, or connect with `ssh <username>@<hostname>.local` from the laptop:

```bash
cd ~
unzip smart-shelf.zip
cd ArUcoMarkerDetector        # the folder name you zipped; run `ls` if unsure
ls                            # you should see main.py, pi_setup.sh, README_PI.md, ...
```

---

## 4. Connect and test the camera (before any Python)

1. Shut the Pi down with `sudo poweroff` and unplug the power. **Never plug a ribbon cable in while the Pi is powered.**
2. Connect the camera to the **CAM/DISP 0** port with the Pi 5 cable. Lift the connector latch, push the cable in fully, then press the latch down. The official guide shows the cable orientation: https://www.raspberrypi.com/documentation/accessories/camera.html
3. Power on and run:

```bash
rpicam-hello --list-cameras
```

Good output looks like this:

```
Available cameras
-----------------
0 : imx708 [4608x2592 10-bit RGGB] (/base/axi/pcie@120000/rp1/i2c@88000/imx708@1a)
```

`imx708` is Camera Module 3, `imx219` is Camera Module 2 and `imx477` is the HQ camera.

On the Pi desktop you can also run `rpicam-hello -t 5000`, which shows a 5-second live preview.

**If you see "No cameras available!":** reseat the cable at both ends and check it is the right way round. Also check that `/boot/firmware/config.txt` contains `camera_auto_detect=1`. Third-party cameras such as Arducam need the `dtoverlay=` line from their manual.

**USB webcam instead?** Plug it in and run `v4l2-ctl --list-devices`, then note its `/dev/videoN` number.

---

## 5. Run the setup script (once)

From the project folder:

```bash
sed -i 's/\r$//' pi_setup.sh     # removes Windows line endings; harmless if there are none
bash pi_setup.sh
```

It asks for your password (for `sudo apt`) and takes about 5-10 minutes. Here is what it does:

1. Installs the system packages:
   - `python3-picamera2`, the Pi camera library. It only comes from apt, not pip.
   - `python3-venv`
   - `libgl1`, which OpenCV needs
   - `v4l-utils`
2. Creates `.venv` with `--system-site-packages`, so the virtual environment can see Picamera2. If there is a `.venv` copied from Windows, it deletes it first.
3. Installs OpenCV 4.7+ (`opencv-python`) into `.venv`. It **keeps the system numpy version**, because a different numpy would break Picamera2 (`numpy.dtype size changed` error).
4. Installs `reportlab`, `pymupdf` and `pytest`, used by the marker-PDF tools and the tests.
5. Checks the installation and lists the cameras it finds.

<details>
<summary>The same steps by hand, if you prefer typing them</summary>

```bash
sudo apt update
sudo apt install -y --no-install-recommends python3-venv python3-picamera2 python3-numpy libgl1 v4l-utils
rm -rf .venv                                              # only if a .venv came from Windows
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
echo "numpy==$(/usr/bin/python3 -c 'import numpy; print(numpy.__version__)')" > .venv/pi-constraints.txt
pip install --only-binary=:all: -c .venv/pi-constraints.txt "opencv-python>=4.7"
pip install --only-binary=:all: -c .venv/pi-constraints.txt "reportlab>=4.0" "pymupdf>=1.24" pytest
```

Do **not** run a plain `pip install -r requirements.txt` on the Pi. It can upgrade numpy and break Picamera2.
</details>

---

## 6. In every new terminal

```bash
cd ~/ArUcoMarkerDetector
source .venv/bin/activate
```

The prompt then starts with `(.venv)`. Always run commands from the project folder, because the calibration file path is relative to it.

---

## 7. Check the camera and ArUco detection

```bash
python tools/check_camera.py --list      # which cameras the Pi has
python tools/check_camera.py             # opens the camera main.py uses and detects markers for 20 s
```

Hold product marker 102, then shelf marker 203, in front of the camera. You should see something like this:

```
Camera: Raspberry Pi camera 0 (imx708) at 1280x720, sensor mode 2304x1296
Calibration: none (distances are rough estimates)
Show product and shelf markers to the camera (running 20 s).
  SEEN marker 102 [ARUCO_ORIGINAL]: product Product B -> shelf C, ~41 cm (rough, uncalibrated), 97 px wide
  SEEN marker 203 [ARUCO_ORIGINAL]: shelf C, ~88 cm (rough, uncalibrated), 202 px wide
  ... 5 s, 29.8 fps, markers in view: 203

Camera OK: 598 frames in 20.0 s (29.9 fps) at 1280x720
Markers seen: 102 x251, 203 x198
```

Other options:

- `--seconds 0` keeps it running until you press Q/Esc in the window, or Ctrl+C.
- Over SSH there is no window. Add `--save snapshot.jpg` and open the saved image to check focus, orientation and lighting.

If this step works, `main.py` will see the same markers. It uses the same camera, detector and config.

---

## 8. Calibrate the Pi camera (recommended)

Calibration gives real distances and angles instead of rough estimates. It needs a screen, so run it in a terminal **on the Pi desktop** (monitor or VNC), not over plain SSH:

```bash
python main.py --calibrate --square-cm 2.5              # measure one printed chessboard square with a ruler
python main.py --calibrate --square-cm 2.5 --board 9x6  # other board size (inner corners)
```

Controls are the same as on the laptop: SPACE captures a view, ENTER finishes (10+ views, about 20 recommended), and Q/Esc cancels. The result is saved to `config/camera_calibration.json`.

- **Do not reuse the laptop's calibration.** It belongs to a different camera.
- A calibration is only valid at one resolution and rotation. The Pi camera default is **1280x720**. If you use `--width/--height` or `--rotate`, pass the **same values** to `--calibrate` and to every run.

---

## 9. Run the robot workflow

These are the same commands as in `command file.txt`, written the Linux way (`python` inside the activated `.venv`):

```bash
# Real camera (show marker 102, then walk the camera to shelf marker 203)
python main.py --pick 102
python main.py --pick "Product B"

# Interactive: asks which product to pick
python main.py

# Simulated camera (no camera needed)
python main.py --pick 102 --synthetic
python main.py --synthetic

# Map and planned paths
python main.py --show-map

# No preview window (automatic over SSH)
python main.py --pick 102 --no-display

# Camera mounted upside down on the robot
python main.py --pick 102 --rotate 180

# A USB webcam instead of the ribbon camera (N from `python tools/check_camera.py --list`)
python main.py --pick 102 --camera-backend webcam --camera N

# Other resolution (must match the calibration)
python main.py --pick 102 --width 1920 --height 1080
```

The physical test is exactly the same as with the laptop:

1. Show product marker **102**. The robot picks it.
2. Carry the Pi and camera toward the wall until shelf marker **203** is in view.
3. Walk in until the measured distance is within the stand-off (40 cm by default).

The robot then aligns, moves to the placement position, places the product and verifies the placement.

In the preview window, Q/Esc aborts. Without a window, Ctrl+C aborts. The exit codes are unchanged: 0 success, 1 run failed, 2 bad input/config, 3 camera error.

### Camera options (main.py and tools/check_camera.py)

| Option | Meaning |
|---|---|
| `--camera-backend auto` | **Default.** Uses the Pi ribbon camera if one is connected, otherwise the webcam. On the laptop it is always the webcam, as before. |
| `--camera-backend picamera` | Always the Pi ribbon camera (Picamera2). |
| `--camera-backend webcam` | Always a USB/laptop webcam (OpenCV). |
| `--camera N` | Which camera: the Nth ribbon camera (the Pi 5 has two ports, 0 and 1), or `/dev/videoN` for a webcam. |
| `--width W --height H` | Capture size. The Pi camera default is 1280x720 (the camera delivers up to 30 fps). |
| `--rotate 90\|180\|270` | Turns the image clockwise, for a camera mounted sideways or upside down. |
| `--no-display` | No preview window. Chosen automatically when there is no screen. |

---

## 10. Marker tools and tests

```bash
python tools/generate_markers.py                     # marker PNGs -> ./markers
python tools/generate_marker_pdf.py --all            # printable A4 PDF -> markers/pdf/all_markers.pdf
python tools/verify_markers.py                       # check the PNGs are detected
python tools/verify_markers.py --pdf markers/pdf/all_markers.pdf
python -m pytest -q                                  # all tests
python -m unittest discover -s tests -t .            # same, without pytest
```

---

## 11. Without a monitor: SSH and VNC

- **SSH** (`ssh <username>@<hostname>.local`): `main.py` and `tools/check_camera.py` notice there is no screen. They run without the window and print everything to the terminal. Stop with Ctrl+C. Calibration is the one thing that needs a screen.
- **VNC** gives you the Pi desktop on the laptop, so the preview window and calibration work remotely. Enable it with `sudo raspi-config`, then **Interface Options**, then **VNC**. Connect with RealVNC Viewer to `<hostname>.local`.

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `/usr/bin/env: 'bash\r'` or `$'\r': command not found` | Windows line endings. Run `sed -i 's/\r$//' pi_setup.sh`, then `bash pi_setup.sh` again. |
| `No Raspberry Pi camera 0 (0 connected)` | The camera is not detected. Go back to step 4 and get `rpicam-hello --list-cameras` working first. |
| `Cannot open Raspberry Pi camera ... busy` | Another program has the camera. Close `rpicam-hello` or the other `main.py`, or run `pkill -f main.py`. |
| `Picamera2 is not available (No module named 'picamera2')` | Either `.venv` is not activated (`source .venv/bin/activate`) or it was made without `--system-site-packages`. Run `bash pi_setup.sh` again; it repairs this. |
| `numpy.dtype size changed, may indicate binary incompatibility` | pip replaced the system numpy. Run `bash pi_setup.sh` again. |
| `libGL.so.1: cannot open shared object file` | Run `sudo apt install libgl1`. |
| `qt.qpa.plugin: Could not find the Qt platform plugin "wayland"` | A harmless warning; the window still opens. If no window appears, run `export QT_QPA_PLATFORM=xcb` and try again. |
| `could not connect to display` / the program aborts | There is no screen. Use `--no-display`, or run on the Pi desktop or VNC. After `ssh -X`, the X forwarding may be broken; use plain `ssh`. |
| `Cannot open camera 0` with a USB webcam | On a Pi 5, `/dev/video0` is usually not the webcam. Find the right number with `python tools/check_camera.py --list`, then use `--camera-backend webcam --camera N`. |
| Image is upside down or sideways | Use `--rotate 180` (or 90/270). Calibrate again with the same value. |
| `Frame size ... != calibration size ...: pose disabled` | The run uses a different resolution than the calibration. Pass the calibration's `--width/--height`, or calibrate again. |
| Markers are not detected | Check the lighting, and that the white border around each marker has not been cut off. Make sure it was printed at 100%. Check focus with `--save snapshot.jpg`: Camera Module 3 autofocuses, but Camera Module 2 has a fixed lens. For a 5 cm product marker far away, try `--width 1920 --height 1080`. |
| Low frame rate | At 1280x720 the Pi camera delivers up to 30 fps. `--width 640 --height 480` is faster, but the view is narrower. |
| Camera stops mid-run | Check the power supply (use the official 27 W one) and the cable seating. |

---

## 13. What was changed for the Pi

The laptop behaviour did not change: with no new options, the laptop still uses its webcam exactly as before.

| File | Change |
|---|---|
| `camera/camera_source.py` | New `PiCameraSource`, the Raspberry Pi camera through Picamera2. It delivers BGR frames at 1280x720 by default, uses a full-view sensor mode and continuous autofocus. Also new: `open_camera()`, which picks the Pi camera or the webcam; `RotatedCamera` for `--rotate`; and `list_pi_cameras()`. |
| `main.py` | New `--camera-backend` and `--rotate` options. Live runs and `--calibrate` open the camera through `open_camera()`. With no screen (SSH), it runs without the preview window instead of crashing. |
| `aruco/perception.py` | New `display_available()`. |
| `tools/check_camera.py` | New camera + ArUco detection check (step 7). |
| `tests/test_pi_camera.py` | Tests for the Pi camera path, run with a stand-in Picamera2, so they also pass on the laptop. |
| `pi_setup.sh` | New one-time Pi setup script (step 5). |
| `.gitattributes` | Keeps `pi_setup.sh` with Linux line endings when it comes from git. |

The standalone scripts `marker_detection_system.py` and `advanced_marker_detection_system.py` are the original laptop demos and still use `cv2.VideoCapture(0)`. On the Pi, use `python tools/check_camera.py` instead. It runs the same detector through the Pi camera.
