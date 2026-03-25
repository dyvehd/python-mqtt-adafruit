# Smart Fire System - IoT Gateway

This repository contains the **IoT Gateway** component of the **Smart Fire Monitoring and Alarm System**, a multidisciplinary project that combines embedded hardware, AI-based fire detection, and a cloud dashboard to monitor and respond to fire hazards in real time.

The gateway runs on a laptop and acts as the bridge between the physical hardware (a Yolo:Bit microcontroller with sensors) and the cloud (Adafruit IO). It reads sensor data, runs AI inference, evaluates alert levels, and publishes everything to Adafruit IO via MQTT. It also subscribes to command feeds so that control signals from the web dashboard can be forwarded to the hardware.

## Where this fits in the system

```
Yolo:Bit + DHT20 + LCD + Fan + Pump + RGB LED
        |
        | USB Serial (JSON lines)
        v
   IoT Gateway (this repo)   <--- you are here
        |
        | MQTT (publish sensor/AI/alert data, subscribe to commands)
        v
   Adafruit IO Cloud
        |
        |
        v
   Backend Server + Database
        |
        |
        v
   Web Dashboard (real-time charts, controls, event log)
```

## Adafruit IO Feed Mapping


| Feed Name                    | MQTT Key                                    | Description                                         | Direction        |
| ---------------------------- | ------------------------------------------- | --------------------------------------------------- | ---------------- |
| `sensor/results`             | `sfs-mqtt.sensor-slash-results`             | Temperature and humidity readings                   | Gateway -> Cloud |
| `sensor/device-status`       | `sfs-mqtt.sensor-slash-device-status`       | Online/offline health check for the microcontroller | Gateway -> Cloud |
| `ai/results`                 | `sfs-mqtt.ai-slash-results`                 | YOLO fire/smoke detection with confidence scores    | Gateway -> Cloud |
| `event/alert-level`          | `sfs-mqtt.event-slash-alert-level`          | `NORMAL`, `WARNING`, or `ALARM`                     | Gateway -> Cloud |
| `event/alarm-trigger-reason` | `sfs-mqtt.event-slash-alarm-trigger-reason` | `NONE`, `HIGH_TEMP`, `FIRE`, or `TEST`              | Gateway -> Cloud |
| `cmd/system`                 | `sfs-mqtt.cmd-slash-system`                 | Master switch (`on`/`off`)                          | Cloud -> Gateway |
| `cmd/fan-pump`               | `sfs-mqtt.cmd-slash-fan-pump`               | Fan/pump control (`on`/`off`/`auto`)                | Cloud -> Gateway |
| `cmd/test-run`               | `sfs-mqtt.cmd-slash-test-run`               | Fire drill trigger (`on`/`off`)                     | Cloud -> Gateway |


## Project Structure

```
src/
  config.py            Feed constants, thresholds, serial config, credential loading
  providers.py         SensorProvider / AIProvider protocols, data classes, mock implementations
  alert.py             Multi-level alert evaluation (NORMAL / WARNING / ALARM)
  gateway.py           Gateway class - orchestrates MQTT, providers, and alert logic
  serial_provider.py   SerialSensorProvider - reads JSON from Yolo:Bit over USB serial
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

`gateway.py**` ties everything together. Each publish cycle it reads from the sensor and AI providers, evaluates the alert level, and publishes all results to Adafruit IO. It also subscribes to command feeds and publishes device status (online/offline) based on sensor availability.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- An [Adafruit IO](https://io.adafruit.com/) account with the feeds listed above

## Setup

1. Clone the repository:

```bash
 git clone <repo-url>
 cd python-mqtt-adafruit
```

1. Install dependencies:

```bash
 uv sync
```

1. Create a `.env` file in the project root with your Adafruit IO credentials:

```
 AIO_USERNAME="your_username"
 AIO_KEY="your_aio_key"
```

## Usage

**With mock data** (no hardware required - for development):

```bash
uv run python main.py
```

**With a Yolo:Bit connected via USB** (replace `COM3` with your serial port):

```bash
uv run python main.py --serial COM3
```

The gateway will connect to Adafruit IO, subscribe to command feeds, and begin publishing sensor data, AI results, and alert levels every 5 seconds.

## Progress


| Task                                                       | Status                                         |
| ---------------------------------------------------------- | ---------------------------------------------- |
| MQTT communication with Adafruit IO                        | Done                                           |
| Modular gateway architecture (provider protocols)          | Done                                           |
| Multi-level alert evaluation                               | Done (needs better series analysis)            |
| Serial sensor reading from Yolo:Bit                        | Done (needs to be tested against real devices) |
| Mock providers for development without hardware            | Done                                           |
| Integrate YOLO model for AI fire/smoke detection           | Not started                                    |
| Forward control commands to microcontroller (serial write) | Not started                                    |
| Persistent event logging                                   | Not started                                    |


