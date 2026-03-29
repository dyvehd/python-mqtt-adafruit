from __future__ import annotations

import json
import logging
import threading
import time

import serial

from src.config import SERIAL_BAUDRATE, SERIAL_RECONNECT_DELAY_SEC, SERIAL_TIMEOUT_SEC
from src.providers import SensorReading

logger = logging.getLogger(__name__)


def parse_line(raw: str) -> SensorReading | None:
    """Parse a JSON line from the microcontroller into a SensorReading.
    Expected format: ``{"temp": 25.3, "hum": 60.1}``
    Returns None for error objects, malformed JSON, or missing keys.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed serial line: %r", raw)
        return None

    if not isinstance(data, dict):
        return None

    if "error" in data:
        logger.warning("Microcontroller error: %s", data["error"])
        return None

    try:
        temp = float(data["temp"])
        hum = float(data["hum"])
    except (KeyError, TypeError, ValueError):
        logger.warning("Missing or invalid keys in serial data: %r", data)
        return None

    return SensorReading(temperature=temp, humidity=hum)


class SerialSensorProvider:
    """Reads sensor data from a Yolo:Bit connected via USB serial.
    A daemon thread continuously reads JSON lines from the serial port and
    caches the latest valid SensorReading.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = SERIAL_BAUDRATE,
        timeout: float = SERIAL_TIMEOUT_SEC,
        reconnect_delay: float = SERIAL_RECONNECT_DELAY_SEC,
    ):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._reconnect_delay = reconnect_delay

        self._lock = threading.Lock()
        self._latest: SensorReading | None = None

        thread = threading.Thread(target=self._reader_loop, daemon=True)
        thread.start()

    def get_readings(self) -> SensorReading:
        with self._lock:
            if self._latest is None:
                raise RuntimeError(
                    f"No sensor data received yet from serial port {self._port}"
                )
            return self._latest

    def send_command(self, command_data: dict) -> None:
        if self._ser and self._ser.is_open:
            try:
                # Chuyển từ Dictionary (Python) sang chuỗi JSON và thêm ký tự xuống dòng (\n)
                # Mạch Yolo:Bit cần lập trình để đọc từng dòng kết thúc bằng \n
                cmd_str = json.dumps(command_data) + "\n"

                self._ser.write(cmd_str.encode("utf-8"))
                logger.info("The order has been sent to Yolo:Bit: %s", cmd_str.strip())
            except Exception as e:
                logger.error("Error sending command to Serial port: %s", e)
        else:
            logger.warning("The serial port is not open, commands cannot be sent!")

    def _reader_loop(self) -> None:
        """Continuously read lines from the serial port, reconnecting on failure."""
        while True:
            try:
                logger.info("Opening serial port %s @ %d baud", self._port, self._baudrate)
                self._ser = serial.Serial(self._port, self._baudrate, timeout=self._timeout)
                logger.info("Serial port %s opened", self._port)

                while True:
                    raw_bytes = self._ser.readline()
                    if not raw_bytes:
                        continue
                    raw = raw_bytes.decode("utf-8", errors="replace")
                    reading = parse_line(raw)
                    if reading is not None:
                        with self._lock:
                            self._latest = reading
                        logger.debug("Serial reading: %s", reading)

            except serial.SerialException as exc:
                logger.error("Serial error on %s: %s. Retrying in %ss...", self._port, exc, self._reconnect_delay)
            except OSError as exc:
                logger.error("OS error on %s: %s. Retrying in %ss...", self._port, exc, self._reconnect_delay)
            finally:

                if self._ser and self._ser.is_open:
                    self._ser.close()

            time.sleep(self._reconnect_delay)