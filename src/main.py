import argparse
import logging
import sys

from Adafruit_IO import MQTTClient

from src.config import load_credentials
from src.gateway import Gateway
from src.providers import MockAIProvider, MockSensorProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Fire System Gateway")
    parser.add_argument(
        "--serial",
        metavar="PORT",
        help="Serial port for Yolo:Bit (e.g. COM3). Uses mock data if omitted.",
    )

    parser.add_argument(
        "--camera-id",
        metavar="ID",
        default="mock",
        help="Camera ID (e.g., 0 for default, 1 for external USB). Uses Mock AI if 'mock' is specified.",
    ) 

    parser.add_argument(
        "--model",
        default="model/best.pt",
        help="Path to the YOLO model weights.",
    )

    args = parser.parse_args()

    if args.serial:
        from src.serial_provider import SerialSensorProvider

        sensor_provider = SerialSensorProvider(port=args.serial)
    else:
        sensor_provider = MockSensorProvider()

    username, key = load_credentials()
    client = MQTTClient(username, key)

    if args.camera_id.lower() == "mock":
        ai_provider = MockAIProvider()
    else:
        from src.ai_provider import YoloAIProvider
        try:
            cam_id = int(args.camera_id)
            ai_provider = YoloAIProvider(model_path=args.model, camera_id=cam_id)
        except ValueError:
            logger.error("Error: --camera-id must be an integer (e.g. 0, 1) or 'mock'.")
            sys.exit(1)
    
    try:
        username, key = load_credentials()
        client = MQTTClient(username, key)
    except ValueError as e:
        logger.error(f"Error loading Adafruit IO credentials: {e}")
        sys.exit(1)

    gateway = Gateway(
        mqtt_client=client,
        sensor_provider=sensor_provider,
        ai_provider=MockAIProvider(),
    )
    gateway.start()


if __name__ == "__main__":
    main()
