from __future__ import annotations

import json
import logging
import sys
import threading
import time

from src.alert import evaluate_alert
from src.config import (
    ALARM_CLEAR_DELAY_SEC,
    AUTO_CLEAR_ALARM,
    FEED_TO_COMMAND,
    PUBLISH_INTERVAL_SEC,
    SUBSCRIBE_FEEDS,
    FeedKey,
)
from src.providers import AIDetection, AIProvider, SensorProvider, SensorReading

logger = logging.getLogger(__name__)


class Gateway:
    """Orchestrates MQTT communication between data providers and Adafruit IO.

    Uses an event-driven main loop: normally publishes batched sensor data
    every ``publish_interval`` seconds, but wakes up immediately when the
    AI provider signals an urgent alarm transition.
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

        # Event-driven alarm bypass
        self._urgent_event = threading.Event()

        # Cache the last known sensor reading for alert evaluation
        # when the buffer happens to be empty between polls.
        self._last_reading: SensorReading | None = None

        # Fire alarm state machine variables
        self._fire_alarm_active = False
        self._last_fire_time = 0.0

        # Configuration options
        self._auto_clear_alarm = AUTO_CLEAR_ALARM
        self._alarm_clear_delay = ALARM_CLEAR_DELAY_SEC

        # Wire MQTT callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Wire AI alert callback
        self._ai.set_alert_callback(self._on_ai_alert)

    def reset_fire_alarm(self) -> None:
        """Reset the latched fire alarm state and timestamp."""
        if self._fire_alarm_active:
            logger.info("Resetting fire alarm active state to NORMAL")
        self._fire_alarm_active = False
        self._last_fire_time = 0.0

    # ------------------------------------------------------------------
    #  MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client) -> None:
        logger.info("Connected to Adafruit IO. Subscribing to command feeds...")
        for feed in SUBSCRIBE_FEEDS:
            client.subscribe(feed)

    def _on_disconnect(self, client) -> None:
        logger.warning("Disconnected from Adafruit IO. Exiting...")
        sys.exit(1)

    def _on_message(self, client, feed_key: str, payload: str) -> None:
        logger.info("Received message on %s: %s", feed_key, payload)
        self._forward_command(feed_key, payload)

    def _forward_command(self, feed_key: str, payload: str) -> None:
        """Translate an Adafruit IO message into the standardized command
        schema and forward it to the microcontroller via serial.
        """
        payload = payload.strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            # Fallback for plain strings if the dashboard sends raw text
            data = payload.lower()

        # --- Simple 1:1 feeds ---
        if feed_key in FEED_TO_COMMAND:
            cmd_name = FEED_TO_COMMAND[feed_key]
            if isinstance(data, dict):
                val = str(data.get("action", "")).lower()
            else:
                val = str(data).lower()
                
            if val:
                cmd = json.dumps({"cmd": cmd_name, "val": val})
                self._sensor.send_command(cmd)

                # Reset latched fire alarm when system is turned off or fire drill ends
                if cmd_name == "system" and val == "off":
                    logger.info("System turned OFF - resetting fire alarm state")
                    self.reset_fire_alarm()
                elif cmd_name == "test-run" and val == "off":
                    logger.info("Fire drill ended - resetting fire alarm state")
                    self.reset_fire_alarm()
            return

        # --- Fan/pump feed: expects JSON like {"fan": "on", "pump": "off"} ---
        if feed_key == FeedKey.CMD_FAN_PUMP:
            if isinstance(data, dict):
                for actuator, value in data.items():
                    actuator = actuator.lower()
                    if actuator in ("fan", "pump"):
                        cmd = json.dumps({"cmd": actuator, "val": str(value).lower()})
                        self._sensor.send_command(cmd)
                    else:
                        logger.warning("Unknown actuator in fan-pump payload: %r", actuator)
            else:
                logger.warning(
                    "Unexpected fan-pump payload format (expected JSON dict): %r",
                    payload,
                )

    # ------------------------------------------------------------------
    #  AI alert callback
    # ------------------------------------------------------------------

    def _on_ai_alert(self) -> None:
        """Called by the AI provider when alarm state transitions to ALARM.

        Sets the urgent event so the main loop wakes up immediately.
        """
        logger.warning("AI alert callback fired — waking gateway for immediate publish")
        self._urgent_event.set()

    # ------------------------------------------------------------------
    #  Main loop
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._client.connect()
        self._client.loop_background()
        logger.info(
            "Gateway started. Publishing every %ss (urgent alarms bypass interval)",
            self._publish_interval,
        )

        while True:
            woken = self._urgent_event.wait(timeout=self._publish_interval)
            if woken:
                logger.warning("Urgent alarm — publishing immediately!")
                self._urgent_event.clear()
            self.publish_cycle()

    # ------------------------------------------------------------------
    #  Publish cycle
    # ------------------------------------------------------------------

    def publish_cycle(self) -> None:
        """Run one publish iteration: read providers, evaluate alert, publish.

        Sensor readings are published as a JSON array so all data points
        captured since the last cycle are preserved.
        """
        # --- Sensor readings (batched) ---
        try:
            readings = self._sensor.get_readings()
        except RuntimeError as exc:
            logger.warning("Sensor unavailable: %s", exc)
            self._client.publish(FeedKey.SENSOR_DEVICE_STATUS, "offline")
            return

        self._client.publish(FeedKey.SENSOR_DEVICE_STATUS, "online")

        # Pick the reading to use for alert evaluation
        if readings:
            self._last_reading = readings[-1]

        reading_for_alert = self._last_reading

        # --- AI detection (smoothed by rolling window) ---
        raw_detection = self._ai.get_detection()

        # Update fire alarm latching/clearing state machine
        current_time = time.time()
        if raw_detection.fire:
            if not self._fire_alarm_active:
                logger.warning("Fire alarm state activated in Gateway!")
            self._fire_alarm_active = True
            self._last_fire_time = current_time
        else:
            if self._fire_alarm_active:
                if self._auto_clear_alarm:
                    elapsed = current_time - self._last_fire_time
                    if elapsed >= self._alarm_clear_delay:
                        logger.warning(
                            "Fire alarm state automatically cleared after %.1f seconds of no fire",
                            elapsed,
                        )
                        self._fire_alarm_active = False
                    else:
                        logger.info(
                            "Fire alarm active, waiting for auto-clear delay (elapsed: %.1f/%.1f s)",
                            elapsed,
                            self._alarm_clear_delay,
                        )
                else:
                    # Latched indefinitely until manual reset
                    pass

        # Create the effective detection representing the gateway's alarm state
        detection = AIDetection(
            fire=self._fire_alarm_active,
            fire_confidence=raw_detection.fire_confidence,
            smoke=raw_detection.smoke,
            smoke_confidence=raw_detection.smoke_confidence,
        )

        # --- Alert evaluation ---
        if reading_for_alert is not None:
            alert_level, alarm_reason = evaluate_alert(reading_for_alert, detection)
            self._sensor.send_command(
                json.dumps({"cmd": "alert", "val": str(alert_level)})
            )
        else:
            # No sensor data available yet — use detection only
            from src.alert import AlertLevel, AlarmReason

            if detection.fire:
                alert_level, alarm_reason = AlertLevel.ALARM, AlarmReason.FIRE
            else:
                alert_level, alarm_reason = AlertLevel.NORMAL, AlarmReason.NONE

        # --- Publish ---
        sensor_payload = json.dumps(
            [{"temp": r.temperature, "hum": r.humidity} for r in readings]
        )
        self._client.publish(FeedKey.SENSOR_RESULTS, sensor_payload)
        self._client.publish(FeedKey.AI_RESULTS, str(detection))
        self._client.publish(FeedKey.EVENT_ALERT, f"{alert_level}:{alarm_reason}")

        logger.info(
            "Published | readings=%d | %s | alert=%s reason=%s",
            len(readings),
            detection,
            alert_level,
            alarm_reason,
        )
