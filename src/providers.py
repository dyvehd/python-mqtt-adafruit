from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SensorReading:
    temperature: float
    humidity: float

    def __str__(self) -> str:
        return f"Temperature: {self.temperature:.1f}°C, Humidity: {self.humidity:.1f}%"


@dataclass(frozen=True)
class AIDetection:
    fire: bool
    fire_confidence: float
    smoke: bool
    smoke_confidence: float

    def __str__(self) -> str:
        return (
            f"fire: {self.fire}, conf: {self.fire_confidence:.2f}, "
            f"smoke: {self.smoke}, conf: {self.smoke_confidence:.2f}"
        )


class SensorProvider(Protocol):
    def get_readings(self) -> list[SensorReading]: ...
    def send_command(self, command: str) -> None: ...


class AIProvider(Protocol):
    def get_detection(self) -> AIDetection: ...
    def set_alert_callback(self, callback: Callable[[], None]) -> None: ...
    def get_latest_jpeg(self) -> bytes | None: ...


class MockSensorProvider:
    """Generates monotonically rising mock sensor data in batches.

    Each call to ``get_readings()`` returns a batch of 5 readings to
    simulate ~10 s of data arriving at 2 s intervals from the Yolo:Bit.
    """

    _READINGS_PER_BATCH = 5

    def __init__(
        self,
        base_temp: float = 20.0,
        base_humidity: float = 40.0,
        step: float = 0.1,
    ):
        self._base_temp = base_temp
        self._base_humidity = base_humidity
        self._step = step
        self._tick = 0

    def get_readings(self) -> list[SensorReading]:
        readings: list[SensorReading] = []
        for _ in range(self._READINGS_PER_BATCH):
            offset = self._tick * self._step
            self._tick += 1
            readings.append(
                SensorReading(
                    temperature=self._base_temp + offset,
                    humidity=self._base_humidity + offset,
                )
            )
        return readings

    def send_command(self, command: str) -> None:
        logger.debug("MockSensorProvider ignoring command: %s", command)


class MockAIProvider:
    """Returns random AI detections and generates synthetic video stream frames."""

    def __init__(self) -> None:
        import threading
        self._alert_callback: Callable[[], None] | None = None
        self._lock = threading.Lock()
        self._latest_jpeg_frame: bytes | None = None
        self._current_detection = AIDetection(
            fire=False,
            fire_confidence=0.0,
            smoke=False,
            smoke_confidence=0.0,
        )
        # Start a daemon thread to simulate the camera frame encoding
        threading.Thread(target=self._mock_generator_loop, daemon=True).start()

    def set_alert_callback(self, callback: Callable[[], None]) -> None:
        self._alert_callback = callback

    def get_detection(self) -> AIDetection:
        with self._lock:
            return self._current_detection

    def get_latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg_frame

    def _mock_generator_loop(self) -> None:
        import time
        import cv2
        import numpy as np
        from datetime import datetime

        frame_width, frame_height = 854, 480
        tick = 0

        while True:
            tick += 1
            # Periodically change detection state to simulate a live event
            if tick % 80 == 0:
                # Every 8 seconds under 10 FPS
                fire = random.random() > 0.8
                smoke = random.random() > 0.65 if not fire else False
                
                with self._lock:
                    self._current_detection = AIDetection(
                        fire=fire,
                        fire_confidence=random.uniform(0.75, 0.98) if fire else 0.0,
                        smoke=smoke,
                        smoke_confidence=random.uniform(0.45, 0.78) if smoke else 0.0,
                    )
                
                if fire and self._alert_callback is not None:
                    try:
                        self._alert_callback()
                    except Exception:
                        logger.exception("Error firing alert callback in MockAIProvider")

            # Create a nice canvas: dark grey background
            frame = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)
            # Add a subtle grid
            grid_size = 40
            for y in range(0, frame_height, grid_size):
                cv2.line(frame, (0, y), (frame_width, y), (18, 18, 18), 1)
            for x in range(0, frame_width, grid_size):
                cv2.line(frame, (x, 0), (frame_width, frame_height), (18, 18, 18), 1)

            # Draw bento lines/vignette frame
            cv2.rectangle(frame, (10, 10), (frame_width - 10, frame_height - 10), (30, 30, 30), 1)

            # Draw premium hud text
            cv2.putText(frame, "MOCK_CAM_01 // INTEL_AI_SURVEILLANCE", (25, 45), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1, cv2.LINE_AA)

            # Blinking REC dot
            rec_color = (0, 0, 255) if (tick // 5) % 2 == 0 else (45, 45, 45)
            cv2.circle(frame, (frame_width - 110, 40), 5, rec_color, -1)
            cv2.putText(frame, "REC", (frame_width - 98, 45), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 160), 1, cv2.LINE_AA)

            # Timestamp
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, time_str, (frame_width - 200, frame_height - 25), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 100, 100), 1, cv2.LINE_AA)

            # Get current detection for drawing bounding boxes
            with self._lock:
                det = self._current_detection

            if det.fire:
                # Draw simulated fire box
                cv2.rectangle(frame, (320, 160), (530, 320), (0, 0, 255), 2)
                cv2.rectangle(frame, (320, 130), (430, 160), (0, 0, 255), -1)
                cv2.putText(frame, f"FIRE {det.fire_confidence*100:.0f}%", (325, 150), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            elif det.smoke:
                # Draw simulated smoke box
                cv2.rectangle(frame, (220, 120), (440, 360), (160, 160, 160), 2)
                cv2.rectangle(frame, (220, 90), (340, 120), (160, 160, 160), -1)
                cv2.putText(frame, f"SMOKE {det.smoke_confidence*100:.0f}%", (225, 110), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
            else:
                cv2.putText(frame, "STATUS: ALL CLEAR", (25, frame_height - 25), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 0), 1, cv2.LINE_AA)

            # Encode to JPEG
            ret_enc, jpeg_buf = cv2.imencode(".jpg", frame)
            if ret_enc:
                with self._lock:
                    self._latest_jpeg_frame = jpeg_buf.tobytes()

            time.sleep(0.1)  # 10 FPS
