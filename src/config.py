from enum import StrEnum

import dotenv


class FeedKey(StrEnum):
    AI_RESULTS = "sfs-mqtt.ai-slash-results"
    CMD_FAN_PUMP = "sfs-mqtt.cmd-slash-fan-pump"
    CMD_SYSTEM = "sfs-mqtt.cmd-slash-system"
    CMD_TEST_RUN = "sfs-mqtt.cmd-slash-test-run"
    EVENT_ALERT = "sfs-mqtt.event-slash-alert-level-alarm-reason"
    SENSOR_DEVICE_STATUS = "sfs-mqtt.sensor-slash-device-status"
    SENSOR_RESULTS = "sfs-mqtt.sensor-slash-results"
    TEST = "sfs-mqtt.test"


SUBSCRIBE_FEEDS = [
    FeedKey.CMD_SYSTEM,
    FeedKey.CMD_FAN_PUMP,
    FeedKey.CMD_TEST_RUN,
]

PUBLISH_INTERVAL_SEC = 10

WARNING_TEMP_THRESHOLD = 40.0
ALARM_TEMP_THRESHOLD = 55.0

AI_TARGET_FPS = 30
AI_CONFIDENCE_THRESHOLD = 0.5

# AI Pipeline – N-out-of-M rolling window params
AI_WINDOW_SIZE = 15  # M: total frames in the rolling window
AI_ALARM_THRESHOLD = 5  # N: consistent-positive frames required to trigger alarm

# AI Pipeline – Bounding box IoU tracking params
AI_IOU_THRESHOLD = 0.25  # Minimum IoU for spatial consistency
AI_TRACKING_GAP_RESET = 5  # Consecutive no-detection frames before resetting tracker

# AI Pipeline – Logging
AI_LOG_FREQUENCY = 15  # Log batch stats every N frames

SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT_SEC = 2.0
SERIAL_RECONNECT_DELAY_SEC = 3.0


def load_credentials(env_path: str = ".env") -> tuple[str, str]:
    username = dotenv.get_key(env_path, "AIO_USERNAME")
    key = dotenv.get_key(env_path, "AIO_KEY")
    if not username or not key:
        raise ValueError("AIO_USERNAME and AIO_KEY must be set in the .env file")
    return username, key
