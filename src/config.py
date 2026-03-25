from enum import StrEnum

import dotenv


class FeedKey(StrEnum):
    AI_RESULTS = "sfs-mqtt.ai-slash-results"
    CMD_FAN_PUMP = "sfs-mqtt.cmd-slash-fan-pump"
    CMD_SYSTEM = "sfs-mqtt.cmd-slash-system"
    CMD_TEST_RUN = "sfs-mqtt.cmd-slash-test-run"
    EVENT_ALERT_LEVEL = "sfs-mqtt.event-slash-alert-level"
    EVENT_ALARM_REASON = "sfs-mqtt.event-slash-alarm-trigger-reason"
    SENSOR_DEVICE_STATUS = "sfs-mqtt.sensor-slash-device-status"
    SENSOR_RESULTS = "sfs-mqtt.sensor-slash-results"
    TEST = "sfs-mqtt.test"


SUBSCRIBE_FEEDS = [
    FeedKey.CMD_SYSTEM,
    FeedKey.CMD_FAN_PUMP,
    FeedKey.CMD_TEST_RUN,
]

PUBLISH_INTERVAL_SEC = 5

WARNING_TEMP_THRESHOLD = 40.0
ALARM_TEMP_THRESHOLD = 55.0


def load_credentials(env_path: str = ".env") -> tuple[str, str]:
    username = dotenv.get_key(env_path, "AIO_USERNAME")
    key = dotenv.get_key(env_path, "AIO_KEY")
    if not username or not key:
        raise ValueError(
            "AIO_USERNAME and AIO_KEY must be set in the .env file"
        )
    return username, key
