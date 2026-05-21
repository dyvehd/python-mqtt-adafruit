# Smart Fire System - IoT Gateway

This repository contains the **IoT Gateway** component of the **Smart Fire Monitoring and Alarm System**, a multidisciplinary project that combines embedded hardware, AI-based fire detection, and a cloud dashboard to monitor and respond to fire hazards in real time.

The gateway acts as the bridge between the physical hardware (a Yolo:Bit microcontroller with sensors) and the cloud (Adafruit IO). It reads sensor data, runs YOLO26 AI inference on camera/webcam feeds, evaluates multi-level alerts, and publishes everything to Adafruit IO via MQTT. It also subscribes to command feeds to forward control signals back to the hardware.

Additionally, for the MVP, the gateway hosts a **multi-threaded HTTP live streaming server** that serves real-time, annotated video feeds directly to the React dashboard over the local network.

---

## System Architecture

```
Yolo:Bit + DHT20 + Actuators (Fan, Pump)
        |
        | USB Serial (JSON lines)
        v
   IoT Gateway (this repo) --------------------------+
        |                                            |
        | MQTT (publish telemetry, subscribe cmd)    | HTTP / MJPEG Stream
        v                                            | (Direct Port 8080)
   Adafruit IO Cloud                                 |
        |                                            |
        v                                            v
   Backend Server (FastAPI)                       React Web Dashboard
        ^                                            ^
        |                                            |
        +-- WebSocket Telemetry Broker (/api/ws) ----+
```

---

## Adafruit IO Feed Mapping

| Feed Name                        | MQTT Key                                        | Description                                         | Direction        |
| -------------------------------- | ----------------------------------------------- | --------------------------------------------------- | ---------------- |
| `sensor/results`                 | `sfs-mqtt.sensor-slash-results`                 | Temperature and humidity readings                   | Gateway -> Cloud |
| `sensor/device-status`           | `sfs-mqtt.sensor-slash-device-status`           | Online/offline health check for the microcontroller | Gateway -> Cloud |
| `ai/results`                     | `sfs-mqtt.ai-slash-results`                     | YOLO fire/smoke detection with confidence scores    | Gateway -> Cloud |
| `event/alert-level-alarm-reason` | `sfs-mqtt.event-slash-alert-level-alarm-reason` | Combined `LEVEL:REASON` (e.g. `ALARM:FIRE`)         | Gateway -> Cloud |
| `cmd/system`                     | `sfs-mqtt.cmd-slash-system`                     | Master switch (`on`/`off`)                          | Cloud -> Gateway |
| `cmd/fan-pump`                   | `sfs-mqtt.cmd-slash-fan-pump`                   | Fan/pump control (`on`/`off`/`auto`)                | Cloud -> Gateway |
| `cmd/test-run`                   | `sfs-mqtt.cmd-slash-test-run`                   | Fire drill trigger (`on`/`off`)                     | Cloud -> Gateway |

---

## Project Structure

```
src/
  config.py            Feed constants, thresholds, serial config, credential loading
  providers.py         SensorProvider / AIProvider protocols, data classes, mock implementations
  alert.py             Multi-level alert evaluation (NORMAL / WARNING / ALARM)
  gateway.py           Gateway class - orchestrates MQTT, providers, and alert logic
  serial_provider.py   SerialSensorProvider - thread-safe buffered reader over USB serial
  stream_server.py     MJPEGStreamServer - HTTP server hosting the live feed
  ai_provider.py       YoloAIProvider - YOLO inference thread, IoU tracking, rolling window
  main.py              Entry point with CLI argument parsing
main.py                Thin wrapper that delegates to src/main.py
pyproject.toml         Project metadata and dependencies (managed with uv)
uv.lock                Lockfile for reproducible installs
```

### Key modules

`providers.py` defines `Protocol` classes (`SensorProvider`, `AIProvider`) so data sources can be swapped without changing the rest of the code. Two mock implementations (`MockSensorProvider`, `MockAIProvider`) allow development and testing without hardware.

`serial_provider.py` implements `SensorProvider` by reading JSON lines (`{"temp": 25.3, "hum": 60.1}`) from a Yolo:Bit over USB serial. A background daemon thread continuously reads and parses lines; `get_readings()` returns the latest cached value, thread-safely.

`alert.py` evaluates a `SensorReading` and an `AIDetection` against configurable thresholds:

- Temperature > 40 C --> `WARNING` (early warning, fan on)
- Temperature > 55 C or fire detected by AI --> `ALARM` (siren, pump, red lights)

`gateway.py` ties everything together. Each publish cycle it reads from the sensor and AI providers, evaluates the alert level, and publishes all results to Adafruit IO. It also subscribes to command feeds and publishes device status (online/offline) based on sensor availability.

`stream_server.py` (`MJPEGStreamServer`) spins up a multi-threaded `ThreadingHTTPServer` running on a separate daemon thread. It serves a `/video_feed` endpoint that streams raw JPEGs in `multipart/x-mixed-replace` format, natively understood by modern browsers. Includes out-of-the-box CORS configuration (`Access-Control-Allow-Origin: *`) and handles client disconnect events (broken pipes) cleanly without disrupting the gateway.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- An [Adafruit IO](https://io.adafruit.com/) account with the feeds listed above

---

## Setup

1. **Clone the repository**:

   ```bash
   git clone <repo-url>
   cd python-mqtt-adafruit
   ```

2. **Install dependencies**:

   ```bash
   uv sync
   ```

3. **Configure Environment Variables**:
   Create a `.env` file in the project root:
   ```env
   AIO_USERNAME="your_username"
   AIO_KEY="your_aio_key"
   ```

---

## Usage & CLI Arguments

The gateway is equipped with multiple CLI parameters to orchestrate the hardware, AI providers, and live streaming options.

### CLI Option Reference

| Option          | Type   | Default         | Description                                                                                      |
| :-------------- | :----- | :-------------- | :----------------------------------------------------------------------------------------------- |
| `--serial`      | `PORT` | _None_          | Serial port for Yolo:Bit (e.g. `COM3`). Uses mock sensor data if omitted.                        |
| `--camera-id`   | `ID`   | `mock`          | Camera index (e.g. `0` for integrated, `1` for USB). Uses beautiful Mock AI generator if `mock`. |
| `--model`       | `PATH` | `model/best.pt` | Path to the custom YOLO model weights.                                                           |
| `--stream-port` | `PORT` | `8080`          | Port to serve the MJPEG live video stream.                                                       |

### Running the Gateway

**1. Development Mode**:

```bash
uv run python main.py --camera-id mock
```

_Spins up a synthetic telemetry generator and serves a mock video feed (surveillance HUD + bouncing YOLO boxes) on `http://localhost:8080/video_feed`._

**2. Physical IoT Mode (With Yolo:Bit and USB Camera)**:

```bash
uv run python main.py --serial COM3 --camera-id 0 --model model/best.pt --stream-port 8080
```

_Connects to Yolo:Bit on `COM3`, grabs frame from camera `0`, applies CUDA-accelerated YOLO inference, publishes alerts to Adafruit IO, and serves the annotated live camera feed on port `8080`._

---

## Progress Tracker

| Task / Feature                        |  Status  | Description                                             |
| :------------------------------------ | :------: | :------------------------------------------------------ |
| **MQTT Cloud Integration**            | **Done** | Core publisher/subscriber loops with Adafruit IO        |
| **Modular Gateway Protocols**         | **Done** | Decoupled sensor/AI interfaces for easy swapping        |
| **Multi-Level Alert Evaluation**      | **Done** | Normal / Warning / Alarm logic and threshold triggers   |
| **Serial MCU Communication**          | **Done** | Event-driven protocol and buffered serial batch parsing |
| **YOLO AI Vision Pipeline**           | **Done** | Custom weights inference, rolling window, IoU tracking  |
| **Edge Video Stream Server**          | **Done** | MJPEG server serving `/video_feed`                      |
| **Microcontroller Abstraction Layer** | **Done** | Actuator safety controls (fan/pump loops, fire drills)  |
| **Actuator Command Forwarding**       | **Done** | Forward cloud manual controls to serial microcontroller |
