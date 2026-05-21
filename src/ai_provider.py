"""
Robust YOLO-based fire/smoke detection provider.

Combines two false-positive suppression strategies:

1. **N-out-of-M rolling window** – requires N spatially-consistent positive frames within the last M frames before triggering the alarm.
2. **Bounding-box IoU tracking** – rejects "teleporting" detections by requiring spatial overlap between consecutive frames.

A frame counts as "positive" for the rolling window *only* when its bounding boxes pass the IoU consistency check.  This means N *spatially consistent* frames out of M total are required — minimising false positives while detecting fire ASAP.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable

import cv2
import torch
from ultralytics import YOLO

from src.config import (
    AI_ALARM_THRESHOLD,
    AI_CONFIDENCE_THRESHOLD,
    AI_IOU_THRESHOLD,
    AI_LOG_FREQUENCY,
    AI_TARGET_FPS,
    AI_TRACKING_GAP_RESET,
    AI_WINDOW_SIZE,
)
from src.providers import AIDetection

logger = logging.getLogger(__name__)

_FIRE_CLASS_NAMES = frozenset({"flame", "fire"})
_SMOKE_CLASS_NAMES = frozenset({"smoke"})


class YoloAIProvider:
    """YOLO-based fire and smoke detection provider.

    Runs a daemon thread that continuously captures frames from a webcam,
    runs YOLO inference with IoU tracking and a rolling window, and caches
    the smoothed ``AIDetection`` for the gateway to poll via
    ``get_detection()``.

    When the rolling window transitions from safe -> alarm, an optional
    callback (set via ``set_alert_callback``) is invoked so the gateway
    can publish the alert immediately.
    """

    def __init__(
        self,
        model_path: str,
        camera_id: int = 0,
        confidence_threshold: float = AI_CONFIDENCE_THRESHOLD,
        target_fps: float = AI_TARGET_FPS,
        window_size: int = AI_WINDOW_SIZE,
        alarm_threshold: int = AI_ALARM_THRESHOLD,
        iou_threshold: float = AI_IOU_THRESHOLD,
        tracking_gap_reset: int = AI_TRACKING_GAP_RESET,
        log_frequency: int = AI_LOG_FREQUENCY,
    ):
        self._camera_id = camera_id
        self._conf_threshold = confidence_threshold
        self._target_spf = 1.0 / target_fps if target_fps > 0 else 0.0

        # --- Rolling window (N out of M) ---
        self._window_size = window_size
        self._alarm_threshold = alarm_threshold
        self._rolling_window: deque[bool] = deque(maxlen=window_size)

        # --- IoU tracking ---
        self._iou_threshold = iou_threshold
        self._tracking_gap_reset = tracking_gap_reset
        self._last_consistent_boxes: list[tuple[float, ...]] | None = None
        self._consecutive_no_detection = 0
        self._last_iou = 0.0

        # --- State ---
        self._alarm_active = False
        self._frame_counter = 0
        self._log_frequency = log_frequency

        # --- Thread-safe detection & frame cache ---
        self._lock = threading.Lock()
        self._latest_jpeg_frame: bytes | None = None
        self._latest = AIDetection(
            fire=False,
            fire_confidence=0.0,
            smoke=False,
            smoke_confidence=0.0,
        )

        # --- Alert callback (set by gateway) ---
        self._alert_callback: Callable[[], None] | None = None

        # --- Model setup ---
        cuda_available = torch.cuda.is_available()
        device = torch.cuda.get_device_name(0) if cuda_available else "CPU"
        logger.info("CUDA available: %s  –  device: %s", cuda_available, device)

        logger.info("Loading YOLO model from %s …", model_path)
        self._model = YOLO(model_path)
        self._class_names: dict[int, str] = self._model.names
        logger.info(
            "YOLO model loaded – classes: %s",
            {k: v for k, v in self._class_names.items()},
        )

        # Map class IDs to fire / smoke sets
        self._fire_ids: set[int] = set()
        self._smoke_ids: set[int] = set()
        self._alarm_ids: set[int] = set()  # Union of fire + smoke for rolling window
        for cls_id, name in self._class_names.items():
            if name.lower() in _FIRE_CLASS_NAMES:
                self._fire_ids.add(cls_id)
                self._alarm_ids.add(cls_id)
            elif name.lower() in _SMOKE_CLASS_NAMES:
                self._smoke_ids.add(cls_id)
                self._alarm_ids.add(cls_id)

        logger.info(
            "Starting fire detection "
            "(alarm requires %d/%d consistent frames, IoU ≥ %.2f)",
            self._alarm_threshold,
            self._window_size,
            self._iou_threshold,
        )

        thread = threading.Thread(target=self._inference_loop, daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def get_detection(self) -> AIDetection:
        """Return the latest smoothed detection (thread-safe)."""
        with self._lock:
            return self._latest

    def get_latest_jpeg(self) -> bytes | None:
        """Return the latest annotated JPEG frame bytes (thread-safe)."""
        with self._lock:
            return self._latest_jpeg_frame

    def set_alert_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked on safe → alarm transitions."""
        self._alert_callback = callback

    # ------------------------------------------------------------------
    #  IoU helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _iou(box1: tuple[float, ...], box2: tuple[float, ...]) -> float:
        """Compute Intersection over Union between two (x1, y1, x2, y2) boxes."""
        x1_i = max(box1[0], box2[0])
        y1_i = max(box1[1], box2[1])
        x2_i = min(box1[2], box2[2])
        y2_i = min(box1[3], box2[3])

        inter_w = max(0.0, x2_i - x1_i)
        inter_h = max(0.0, y2_i - y1_i)
        inter_area = inter_w * inter_h

        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union_area = area1 + area2 - inter_area

        if union_area <= 0.0:
            return 0.0
        return inter_area / union_area

    def _is_consistent_detection(self, detections: list[tuple[float, ...]]) -> bool:
        """Return True when detections are spatially consistent with
        previously-tracked boxes (not 'teleporting' around the screen).

        Updates ``_last_consistent_boxes`` and ``_last_iou`` as side effects.
        """
        self._last_iou = 0.0

        # --- No detections this frame ---
        if not detections:
            self._consecutive_no_detection += 1
            if self._consecutive_no_detection >= self._tracking_gap_reset:
                self._last_consistent_boxes = None
            return False

        self._consecutive_no_detection = 0
        current_boxes = [d[:4] for d in detections]

        # --- First detection (or after gap reset) ---
        if self._last_consistent_boxes is None:
            self._last_consistent_boxes = current_boxes
            self._last_iou = 1.0
            return True

        # --- Compare every current box against every previous box ---
        best_iou = 0.0
        matched_boxes: list[tuple[float, ...]] = []

        for cb in current_boxes:
            for pb in self._last_consistent_boxes:
                iou = self._iou(cb, pb)
                if iou > best_iou:
                    best_iou = iou
                if iou >= self._iou_threshold:
                    matched_boxes.append(cb)
                    break

        self._last_iou = best_iou

        if matched_boxes:
            self._last_consistent_boxes = matched_boxes
            return True

        # No spatial match — reset tracker to current boxes
        self._last_consistent_boxes = current_boxes
        return False

    # ------------------------------------------------------------------
    #  Detection extraction
    # ------------------------------------------------------------------

    def _extract_detections(self, results) -> list[tuple[float, ...]]:
        """Pull (x1, y1, x2, y2, confidence, class_id) from YOLO output,
        keeping only alarm-class detections above the confidence threshold.
        """
        detections: list[tuple[float, ...]] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                if conf < self._conf_threshold:
                    continue
                if cls_id not in self._alarm_ids:
                    continue
                coords = box.xyxy[0].tolist()
                detections.append(
                    (
                        float(coords[0]),
                        float(coords[1]),
                        float(coords[2]),
                        float(coords[3]),
                        conf,
                        float(cls_id),
                    )
                )
        return detections

    # ------------------------------------------------------------------
    #  Batch logging
    # ------------------------------------------------------------------

    def _log_batch(
        self,
        detections: list[tuple[float, ...]],
        camera_fps: float,
        inference_fps: float,
    ) -> None:
        """Log a structured detection summary."""
        window_list = list(self._rolling_window)
        window_str = "[" + ",".join("T" if x else "F" for x in window_list) + "]"
        window_count = sum(window_list)

        lines = [
            f"===== Frame #{self._frame_counter}"
            f" | Cam FPS: {camera_fps:.1f}"
            f" | Inf FPS: {inference_fps:.1f} =====",
        ]

        if detections:
            parts = []
            for det in detections:
                cls_id = int(det[5])
                conf = det[4]
                name = self._class_names.get(cls_id, f"cls_{cls_id}")
                parts.append(f"{name} @ {conf:.2f}")
            lines.append(f"  Detections: {len(detections)} ({', '.join(parts)})")
        else:
            lines.append("  Detections: 0")

        lines.append(
            f"  Rolling Window: {window_str} -> {window_count}/{self._window_size}"
        )
        lines.append(f"  Alarm Status: {'ACTIVE' if self._alarm_active else 'SAFE'}")

        if window_list and window_list[-1]:
            lines.append(f"  IoU Consistency: {self._last_iou:.2f} (matched)")
        elif detections:
            lines.append(f"  IoU Consistency: {self._last_iou:.2f} (unmatched)")
        else:
            lines.append("  IoU Consistency: N/A (no boxes)")

        # logger.info("\n".join(lines))

    # ------------------------------------------------------------------
    #  Overlay drawing
    # ------------------------------------------------------------------

    def _draw_overlay(
        self,
        frame,
        detections: list[tuple[float, ...]],
        camera_fps: float,
        inference_fps: float,
    ) -> None:
        """Draw bounding boxes, labels, FPS, alarm status, and rolling
        window bar on the frame."""
        # --- Bounding boxes & labels ---
        for det in detections:
            x1, y1, x2, y2, conf, cls_id_f = det
            cls_id = int(cls_id_f)
            x1_i, y1_i, x2_i, y2_i = int(x1), int(y1), int(x2), int(y2)

            cls_name = self._class_names.get(cls_id, f"cls_{cls_id}")
            label = f"{cls_name} {conf:.2f}"

            if cls_id in self._fire_ids:
                color = (0, 0, 255)  # Red for fire
            elif cls_id in self._smoke_ids:
                color = (180, 180, 180)  # Grey for smoke
            else:
                color = (0, 255, 255)

            cv2.rectangle(frame, (x1_i, y1_i), (x2_i, y2_i), color, 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(
                frame,
                (x1_i, max(y1_i - th - 8, 0)),
                (x1_i + tw + 4, y1_i),
                color,
                cv2.FILLED,
            )
            cv2.putText(
                frame,
                label,
                (x1_i + 2, max(y1_i - 4, th + 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 0),
                2,
            )

        h, w = frame.shape[:2]

        # --- Top-left: camera & inference FPS ---
        fps_str = f"Cam FPS: {camera_fps:.1f}  |  Inf FPS: {inference_fps:.1f}"
        cv2.putText(
            frame,
            fps_str,
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
        )

        # --- Top-right: alarm status ---
        status = "FIRE!" if self._alarm_active else "SAFE"
        color = (0, 0, 255) if self._alarm_active else (0, 255, 0)
        (tw, th), _ = cv2.getTextSize(status, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
        cv2.putText(
            frame,
            status,
            (w - tw - 15, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            color,
            2,
        )

        # --- Bottom-right: rolling window bar ---
        self._draw_rolling_window(frame)

    def _draw_rolling_window(self, frame) -> None:
        """Draw a visual bar showing the last M frame outcomes."""
        h, w = frame.shape[:2]
        bar_w, bar_h, gap = 22, 18, 4
        total_w = self._window_size * bar_w + (self._window_size - 1) * gap
        start_x = w - total_w - 15
        start_y = h - bar_h - 15

        for i in range(self._window_size):
            x = start_x + i * (bar_w + gap)
            if i < len(self._rolling_window):
                val = self._rolling_window[i]
                color = (0, 200, 0) if val else (0, 0, 200)
            else:
                color = (80, 80, 80)
            cv2.rectangle(frame, (x, start_y), (x + bar_w, start_y + bar_h), color, -1)
            cv2.rectangle(
                frame,
                (x, start_y),
                (x + bar_w, start_y + bar_h),
                (200, 200, 200),
                1,
            )

        count = sum(self._rolling_window)
        label = f"{count}/{self._alarm_threshold}"
        cv2.putText(
            frame,
            label,
            (start_x - 55, start_y + bar_h - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )

    # ------------------------------------------------------------------
    #  Main inference loop (daemon thread)
    # ------------------------------------------------------------------

    def _inference_loop(self) -> None:
        logger.info("Opening camera ID %d …", self._camera_id)
        cap = cv2.VideoCapture(self._camera_id)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, self._target_spf and 1.0 / self._target_spf)

        if not cap.isOpened():
            logger.error("Failed to open camera ID %d", self._camera_id)
            return

        prev_camera_time = time.time()

        try:
            while True:
                frame_start = time.time()

                ret, frame = cap.read()
                if not ret:
                    logger.warning("Failed to grab frame – retrying …")
                    time.sleep(1)
                    continue

                camera_fps = 1.0 / max(time.time() - prev_camera_time, 1e-6)
                prev_camera_time = time.time()

                # --- YOLO inference ---
                inf_start = time.time()
                results = self._model(frame, stream=False, verbose=False)
                inf_end = time.time()
                inference_fps = 1.0 / max(inf_end - inf_start, 1e-6)

                # --- Extract alarm-class detections ---
                detections = self._extract_detections(results)

                # --- Spatial consistency (IoU tracking) ---
                is_consistent = self._is_consistent_detection(detections)

                # --- Update rolling window ---
                self._rolling_window.append(is_consistent)

                # --- Check alarm state ---
                was_alarm = self._alarm_active
                self._alarm_active = sum(self._rolling_window) >= self._alarm_threshold

                if self._alarm_active and not was_alarm:
                    logger.warning("*** FIRE ALARM TRIGGERED! ***")
                    if self._alert_callback is not None:
                        self._alert_callback()
                elif not self._alarm_active and was_alarm:
                    logger.info("--- Fire alarm cleared. ---")

                # --- Build per-frame confidence stats for AIDetection ---
                max_fire_conf = 0.0
                max_smoke_conf = 0.0
                raw_smoke = False
                for det in detections:
                    cls_id = int(det[5])
                    conf = det[4]
                    if cls_id in self._fire_ids:
                        max_fire_conf = max(max_fire_conf, conf)
                    elif cls_id in self._smoke_ids:
                        raw_smoke = True
                        max_smoke_conf = max(max_smoke_conf, conf)

                with self._lock:
                    self._latest = AIDetection(
                        fire=self._alarm_active,
                        fire_confidence=max_fire_conf,
                        smoke=raw_smoke,
                        smoke_confidence=max_smoke_conf,
                    )

                # --- Draw overlay ---
                self._draw_overlay(frame, detections, camera_fps, inference_fps)

                # --- Cache latest JPEG frame ---
                ret_enc, jpeg_buf = cv2.imencode(".jpg", frame)
                if ret_enc:
                    with self._lock:
                        self._latest_jpeg_frame = jpeg_buf.tobytes()

                # --- Batch logging ---
                self._frame_counter += 1
                if self._frame_counter % self._log_frequency == 0:
                    self._log_batch(detections, camera_fps, inference_fps)

                # --- Show frame ---
                cv2.imshow("Fire Detection", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    logger.info("Detection window closed by user.")
                    break

                # --- FPS throttle ---
                elapsed = time.time() - frame_start
                sleep_time = self._target_spf - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            cap.release()
            cv2.destroyAllWindows()
