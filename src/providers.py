from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol


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
    def get_readings(self) -> SensorReading: ...


class AIProvider(Protocol):
    def get_detection(self) -> AIDetection: ...


class MockSensorProvider:
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

    def get_readings(self) -> SensorReading:
        offset = self._tick * self._step
        self._tick += 1
        return SensorReading(
            temperature=self._base_temp + offset,
            humidity=self._base_humidity + offset,
        )


class MockAIProvider:
    def get_detection(self) -> AIDetection:
        return AIDetection(
            fire=random.random() > 0.5,
            fire_confidence=random.random(),
            smoke=random.random() > 0.5,
            smoke_confidence=random.random(),
        )
