import logging

from Adafruit_IO import MQTTClient

from src.config import load_credentials
from src.gateway import Gateway
from src.providers import MockAIProvider, MockSensorProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    username, key = load_credentials()
    client = MQTTClient(username, key)

    gateway = Gateway(
        mqtt_client=client,
        sensor_provider=MockSensorProvider(),
        ai_provider=MockAIProvider(),
    )
    gateway.start()


if __name__ == "__main__":
    main()
