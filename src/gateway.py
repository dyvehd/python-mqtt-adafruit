from __future__ import annotations

import logging
import sys
import time

from src.alert import evaluate_alert
from src.config import PUBLISH_INTERVAL_SEC, SUBSCRIBE_FEEDS, FeedKey
from src.providers import AIProvider, SensorProvider

logger = logging.getLogger(__name__)


class Gateway:
    """Orchestrates MQTT communication between data providers and Adafruit IO.
    Accepts an Adafruit_IO MQTTClient and sensor/AI providers.
    """

    def __init__(
        self,
        mqtt_client,
        sensor_provider: SensorProvider,
        ai_provider: AIProvider,
        publish_interval: float = PUBLISH_INTERVAL_SEC,
    ):
        self._client = mqtt_client
        self._sensor = sensor_provider
        self._ai = ai_provider
        self._publish_interval = publish_interval

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def _on_connect(self, client) -> None:
        logger.info("Connected to Adafruit IO. Subscribing to command feeds...")
        for feed in SUBSCRIBE_FEEDS:
            client.subscribe(feed)

    def _on_disconnect(self, client) -> None:
        logger.warning("Disconnected from Adafruit IO. Exiting...")
        sys.exit(1)

    def _on_message(self, client, feed_key: str, payload: str) -> None:
        logger.info("Received message on %s: %s", feed_key, payload)

        # Create an empty dictionary to hold the command
        command_data = {}

        # Check which channel the message came from
        if feed_key == FeedKey.CMD_FAN_PUMP:
            if payload == "1":
                command_data = {"device": "FAN_PUMP", "status": "ON"}
            elif payload == "0":
                command_data = {"device": "FAN_PUMP", "status": "OFF"}

        elif feed_key == FeedKey.CMD_TEST_RUN:
            if payload == "1":
                command_data = {"device": "SYSTEM", "cmd": "TEST_ALARM"}

        if command_data:
            if hasattr(self._sensor, "send_command"):
                self._sensor.send_command(command_data)
        else:
            logger.debug("No action has been assigned to this command.")

    def start(self) -> None:
        self._client.connect()
        self._client.loop_background()
        logger.info("Gateway started. Publishing every %ss", self._publish_interval)

        while True:
            self.publish_cycle()
            time.sleep(self._publish_interval)

    def publish_cycle(self) -> None:
        """Run one publish iteration: read providers, evaluate alert, publish."""
        try:
            reading = self._sensor.get_readings()
        except RuntimeError as exc:
            logger.warning("Sensor unavailable: %s", exc)
            self._client.publish(FeedKey.SENSOR_DEVICE_STATUS, "offline")
            return

        self._client.publish(FeedKey.SENSOR_DEVICE_STATUS, "online")

        detection = self._ai.get_detection()
        alert_level, alarm_reason = evaluate_alert(reading, detection)

        self._client.publish(FeedKey.SENSOR_RESULTS, str(reading))
        self._client.publish(FeedKey.AI_RESULTS, str(detection))
        self._client.publish(FeedKey.EVENT_ALERT_LEVEL, str(alert_level))
        self._client.publish(FeedKey.EVENT_ALARM_REASON, str(alarm_reason))

        logger.info(
            "Published | %s | %s | alert=%s reason=%s",
            reading,
            detection,
            alert_level,
            alarm_reason,
        )
