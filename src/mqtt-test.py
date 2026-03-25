from Adafruit_IO import MQTTClient
import dotenv
import sys
import time
import random

AIO_USERNAME = dotenv.get_key(".env", "AIO_USERNAME")
AIO_KEY = dotenv.get_key(".env", "AIO_KEY")


def connected(client):
    print("Connected to Adafruit IO! Listening for changes...")
    client.subscribe("sfs-mqtt.cmd-slash-system")
    client.subscribe("sfs-mqtt.cmd-slash-fan-pump")
    client.subscribe("sfs-mqtt.cmd-test-run")


def disconnected(client):
    print("Disconnected from Adafruit IO!")
    sys.exit(1)


def message(client, feed_key, payload):
    print("\t Feed {0} received new value: {1}".format(feed_key, payload))


def get_fake_sensor_results():
    fake_counter = 0
    while True:
        time.sleep(5)
        temperature = 20.0 + fake_counter
        humidity = 40.0 + fake_counter
        fake_counter += 0.1
        return temperature, humidity


def publish_sensor_data():
    temperature, humidity = get_fake_sensor_results()
    mqttc.publish(
        "sfs-mqtt.sensor-slash-results",
        f"Temperature: {temperature}°C, Humidity: {humidity}%",
    )
    print(f"Published temperature: {temperature}°C, humidity: {humidity}%")


def get_fake_ai_results():
    is_fire = random.randint(0, 1)
    is_fire_confidence = random.randint(0, 100)
    is_smoke = random.randint(0, 1)
    is_smoke_confidence = random.randint(0, 100)
    return is_fire, is_fire_confidence, is_smoke, is_smoke_confidence


def publish_ai_results():
    is_fire, is_fire_confidence, is_smoke, is_smoke_confidence = get_fake_ai_results()
    mqttc.publish(
        "sfs-mqtt.ai-slash-results",
        f"Is Fire: {is_fire}, Confidence: {is_fire_confidence}, Is Smoke: {is_smoke}, Confidence: {is_smoke_confidence}",
    )
    print(
        f"Published is fire: {is_fire}, confidence: {is_fire_confidence}, is smoke: {is_smoke}, confidence: {is_smoke_confidence}"
    )


mqttc = MQTTClient(AIO_USERNAME, AIO_KEY)

mqttc.on_disconnect = disconnected
mqttc.on_message = message
mqttc.on_connect = connected


# Start the connection
mqttc.connect()
mqttc.loop_background()
print("Connecting...")

while True:
    publish_sensor_data()
    publish_ai_results()
    time.sleep(5)
