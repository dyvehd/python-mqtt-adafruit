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
    """Returns random AI detections for development without a camera."""

    def __init__(self) -> None:
        self._alert_callback: Callable[[], None] | None = None

    def set_alert_callback(self, callback: Callable[[], None]) -> None:
        self._alert_callback = callback

    def get_detection(self) -> AIDetection:
        return AIDetection(
            fire=False,
            fire_confidence=0.0,
            smoke=random.random() > 0.8,
            smoke_confidence=random.random() * 0.3,
        )
