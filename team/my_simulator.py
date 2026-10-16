import time
import json
import random
import paho.mqtt.client as mqtt

client = mqtt.Client()
client.connect("localhost", 1883)

print("Запуск передачи данных в telemetry/conveyor-02...")

while True:
    speed = round(random.uniform(2.0, 5.0), 2)
    temperature = round(random.uniform(50.0, 85.0), 1)
    weight = round(random.uniform(100, 300), 1)

    payload = {
        "topic": "org.openegiz.team/conveyor-02/things/twin/commands/modify",
        "headers": {},
        "path": "/features",
        "value": {
            "speed": {"properties": {"value": speed}},
            "temperature": {"properties": {"value": temperature}},
            "weight": {"properties": {"value": weight}}
        }
    }

    # Отправка в топик telemetry/conveyor-02
    client.publish("telemetry/conveyor-02", json.dumps(payload))
    print(f"Отправлено: Скорость={speed} м/с | Температура={temperature} °C | Вес={weight} т/ч")
    time.sleep(3)
