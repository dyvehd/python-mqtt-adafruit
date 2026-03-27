from __future__ import annotations

import logging
import threading
import time

import cv2
import torch
from ultralytics import YOLO

from src.config import AI_CONFIDENCE_THRESHOLD, AI_TARGET_FPS
from src.providers import AIDetection

logger = logging.getLogger(__name__)

_FIRE_CLASS_NAMES = frozenset({"flame", "fire"})
_SMOKE_CLASS_NAMES = frozenset({"smoke"})


class YoloAIProvider:
    """YOLO-based fire and smoke detection provider.

    Runs a daemon thread that continuously captures frames from a webcam,
    runs YOLO inference, and caches the latest AIDetection for the gateway
    to poll via ``get_detection()``.
    """

    def __init__(
        self,
        model_path: str,
        camera_id: int = 0,
        confidence_threshold: float = AI_CONFIDENCE_THRESHOLD,
        target_fps: float = AI_TARGET_FPS,
    ):
        self._camera_id = camera_id
        self._conf_threshold = confidence_threshold
        self._target_spf = 1.0 / target_fps if target_fps > 0 else 0.0

        self._lock = threading.Lock()
        self._latest = AIDetection(
            fire=False,
            fire_confidence=0.0,
            smoke=False,
            smoke_confidence=0.0,
        )

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

        self._fire_ids: set[int] = set()
        self._smoke_ids: set[int] = set()
        for cls_id, name in self._class_names.items():
            if name.lower() in _FIRE_CLASS_NAMES:
                self._fire_ids.add(cls_id)
            elif name.lower() in _SMOKE_CLASS_NAMES:
                self._smoke_ids.add(cls_id)

        thread = threading.Thread(target=self._inference_loop, daemon=True)
        thread.start()

    def get_detection(self) -> AIDetection:
        with self._lock:
            return self._latest

    def _inference_loop(self) -> None:
        logger.info("Opening camera ID %d …", self._camera_id)
        cap = cv2.VideoCapture(self._camera_id)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        if not cap.isOpened():
            logger.error("Failed to open camera ID %d", self._camera_id)
            return

        prev_time = time.time()

        while True:
            frame_start = time.time()

            ret, frame = cap.read()
            if not ret:
                logger.warning("Failed to grab frame – retrying …")
                time.sleep(1)
                continue

            results = self._model(frame, stream=True, verbose=False)

            fire_detected = False
            smoke_detected = False
            max_fire_conf = 0.0
            max_smoke_conf = 0.0

            for r in results:
                for box in r.boxes:
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])

                    if conf < self._conf_threshold:
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cls_name = self._class_names.get(cls_id, str(cls_id))
                    label = f"{cls_name} {conf:.2f}"

                    if cls_id in self._fire_ids:
                        fire_detected = True
                        max_fire_conf = max(max_fire_conf, conf)
                        color = (0, 0, 255)
                    elif cls_id in self._smoke_ids:
                        smoke_detected = True
                        max_smoke_conf = max(max_smoke_conf, conf)
                        color = (180, 180, 180)
                    else:
                        color = (0, 255, 255)

                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    (tw, th), _ = cv2.getTextSize(
                        label,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        2,
                    )
                    cv2.rectangle(
                        frame,
                        (x1, max(y1 - th - 8, 0)),
                        (x1 + tw + 4, y1),
                        color,
                        cv2.FILLED,
                    )
                    cv2.putText(
                        frame,
                        label,
                        (x1 + 2, max(y1 - 4, th + 4)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 0, 0),
                        2,
                    )

            with self._lock:
                self._latest = AIDetection(
                    fire=fire_detected,
                    fire_confidence=max_fire_conf,
                    smoke=smoke_detected,
                    smoke_confidence=max_smoke_conf,
                )

            now = time.time()
            fps = 1.0 / (now - prev_time) if now != prev_time else 0.0
            prev_time = now

            cv2.putText(
                frame,
                f"FPS: {fps:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )
            cv2.imshow("Fire Detection", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                logger.info("Detection window closed by user.")
                break

            elapsed = time.time() - frame_start
            sleep_time = self._target_spf - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        cap.release()
        cv2.destroyAllWindows()
