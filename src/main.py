import argparse
import logging

from Adafruit_IO import MQTTClient

from src.config import load_credentials
from src.gateway import Gateway
from src.providers import MockAIProvider, MockSensorProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Fire System Gateway")
    parser.add_argument(
        "--serial",
        metavar="PORT",
        help="Serial port for Yolo:Bit (e.g. COM3). Uses mock data if omitted.",
    )
    args = parser.parse_args()

    if args.serial:
        from src.serial_provider import SerialSensorProvider

        sensor_provider = SerialSensorProvider(port=args.serial)
    else:
        sensor_provider = MockSensorProvider()

    username, key = load_credentials()
    client = MQTTClient(username, key)

    gateway = Gateway(
        mqtt_client=client,
        sensor_provider=sensor_provider,
        ai_provider=MockAIProvider(),
    )
    gateway.start()


if __name__ == "__main__":
    main()
