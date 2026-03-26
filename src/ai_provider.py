from __future__ import annotations

import logging
import threading
import time
import cv2
from ultralytics import YOLO

from src.providers import AIDetection

logger = logging.getLogger(__name__)

class YoloAIProvider:
    def __init__(
        self,
        model_path: str,
        camera_id: int = 0,
        confidence_threshold: float = 0.5,
    ):
        self._model_path = model_path
        self._camera_id = camera_id
        self._conf_threshold = confidence_threshold

        self._lock = threading.Lock()
        self._latest = AIDetection(
            fire=False, fire_confidence=0.0, 
            smoke=False, smoke_confidence=0.0
        )

        logger.info("Loading YOLO model from %s...", self._model_path)
        self._model = YOLO(self._model_path)
        logger.info("YOLO model loaded successfully.")

        thread = threading.Thread(target=self._ai_loop, daemon=True)
        thread.start()

    def get_detection(self) -> AIDetection:
        with self._lock:
            return self._latest

    def _ai_loop(self) -> None:
        logger.info("Opening DIRECT camera, ID: %d", self._camera_id)
        cap = cv2.VideoCapture(self._camera_id)

        if not cap.isOpened():
            logger.error("Failed to open DIRECT camera ID: %d", self._camera_id)
            return

        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Failed to grab frame. Is camera still connected? Retrying...")
                time.sleep(1)
                continue

            results = self._model(frame, verbose=False)
            
            fire_detected = False
            max_fire_conf = 0.0
            processed_frame = results[0].plot() 

            for r in results:
                for box in r.boxes:
                    conf = float(box.conf[0])
                    if conf >= self._conf_threshold: 
                        fire_detected = True
                        max_fire_conf = max(max_fire_conf, conf)
                        
            with self._lock:
                self._latest = AIDetection(
                    fire=fire_detected,
                    fire_confidence=max_fire_conf,
                    smoke=False, 
                    smoke_confidence=0.0
                )

            cv2.imshow("AIoT Direct Camera Feed", processed_frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("Closing AI window...")
                break

        cap.release()
        cv2.destroyAllWindows()


# python main.py --serial COM3 --camera-id 1 (nếu demo bằng camera máy tính thì id là 0)