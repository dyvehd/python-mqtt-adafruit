from __future__ import annotations

from enum import StrEnum

from src.config import ALARM_TEMP_THRESHOLD, WARNING_TEMP_THRESHOLD
from src.providers import AIDetection, SensorReading


class AlertLevel(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ALARM = "ALARM"


class AlarmReason(StrEnum):
    NONE = "NONE"
    HIGH_TEMP = "HIGH_TEMP"
    FIRE = "FIRE"
    TEST = "TEST"


# Very simple evaluation logic for now.
# Evaluation needs to be done on a series of readings, not just a single reading.
def evaluate_alert(
    reading: SensorReading,
    detection: AIDetection,
) -> tuple[AlertLevel, AlarmReason]:
    """Evaluate the alert level based on sensor readings and AI detection.

    Thresholds:
      - Temperature > ALARM_TEMP_THRESHOLD or fire detected  -> ALARM
      - Temperature > WARNING_TEMP_THRESHOLD                 -> WARNING
      - Otherwise                                            -> NORMAL
    """
    if detection.fire:
        return AlertLevel.ALARM, AlarmReason.FIRE

    if reading.temperature > ALARM_TEMP_THRESHOLD:
        return AlertLevel.ALARM, AlarmReason.HIGH_TEMP

    if reading.temperature > WARNING_TEMP_THRESHOLD:
        return AlertLevel.WARNING, AlarmReason.HIGH_TEMP

    return AlertLevel.NORMAL, AlarmReason.NONE
