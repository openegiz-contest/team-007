#!/usr/bin/env python3
"""
Симулятор подсистемы газового контроля (CH4, CO, пыль) и автоматической вентиляции (ГВУ)
для платформы OpenEgiz. Полностью совместим с пайплайном MQTT -> Ditto -> Telegraf -> InfluxDB -> Grafana.
"""

import base64
import json
import math
import os
import random
import signal
import sys
import time
import urllib.error
import urllib.request

import paho.mqtt.client as mqtt

# ==============================================================================
# 1. АВТОМАТИЧЕСКОЕ ЧТЕНИЕ ПАРОЛЕЙ ИЗ DEPLOY/COMPOSE/.ENV
# ==============================================================================
def get_ditto_credentials():
    env_path = os.path.join(os.path.expanduser("~"), "team-007", "deploy", "compose", ".env")
    user = "ditto"
    password = "1VVizla9BZBLHV9D6i0kePdT"

    if os.path.exists(env_path):
        try:
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("DITTO_USER="):
                        user = line.strip().split("=", 1)[1]
                    elif line.startswith("DITTO_PASSWORD="):
                        password = line.strip().split("=", 1)[1]
        except Exception:
            pass
    return user, password

DITTO_USER, DITTO_PASSWORD = get_ditto_credentials()
DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080").rstrip("/")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

NAMESPACE = "org.openegiz.mine"
TOPIC_PREFIX = "telemetry"

SECTION_NAME = "horizon-1-section-a"
FAN_NAME = "ventilation-fan-01"

# ==============================================================================
# 2. РЕГИСТРАЦИЯ ДВОЙНИКОВ В DITTO (КАК В SETUP_TWINS.PY)
# ==============================================================================
INITIAL_TWINS = {
    f"{NAMESPACE}:{SECTION_NAME}": {
        "policyId": "default:basic_policy",
        "attributes": {
            "name": "Участок газового контроля (Горизонт -200м)",
            "_isType": False,
            "_parents": "org.openegiz.mine:mine-01",
            "kind": "safety-section",
            "location": "Horizon -200m, Section A"
        },
        "features": {
            "ch4_sensor": {"properties": {"value": 0.35, "unit": "%", "status": "NORMAL", "alarm": 0}},
            "co_sensor": {"properties": {"value": 12.0, "unit": "ppm", "status": "NORMAL"}},
            "dust_sensor": {"properties": {"value": 8.5, "unit": "mg/m3", "status": "NORMAL"}},
            "airflow_sensor": {"properties": {"value": 6.5, "unit": "m/s"}}
        }
    },
    f"{NAMESPACE}:{FAN_NAME}": {
        "policyId": "default:basic_policy",
        "attributes": {
            "name": "Главная вентиляторная установка (ГВУ ВЦД-31.5)",
            "_isType": False,
            "_parents": "org.openegiz.mine:mine-01",
            "kind": "ventilation-fan",
            "model": "VCD-3.15 Underground Blower"
        },
        "features": {
            "fan_status": {"properties": {"value": "RUNNING", "mode_code": 1}},
            "rpm": {"properties": {"value": 1200, "unit": "rpm"}},
            "power_kw": {"properties": {"value": 45.0, "unit": "kW"}}
        }
    }
}

def register_twins_in_ditto():
    auth = "Basic " + base64.b64encode(f"{DITTO_USER}:{DITTO_PASSWORD}".encode()).decode()
    for thing_id, body in INITIAL_TWINS.items():
        req = urllib.request.Request(
            f"{DITTO_URL}/api/2/things/{thing_id}",
            data=json.dumps(body).encode(),
            method="PUT",
            headers={"Authorization": auth, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[DITTO HTTP] {'Создан' if resp.status == 201 else 'Обновлен'} двойник: {thing_id}")
        except urllib.error.URLError as exc:
            print(f"[ОШИБКА DITTO] Не удалось зарегистрировать {thing_id}: {exc}", file=sys.stderr)
            return False
    return True

# ==============================================================================
# 3. ФИЗИЧЕСКАЯ МОДЕЛЬ ГАЗОВОЙ БЕЗОПАСНОСТИ И АВТОМАТИКИ ГВУ
# ==============================================================================
class GasSafetySimulation:
    def __init__(self):
        self.step = 0
        self.phase = "NORMAL"  # NORMAL -> LEAK_SPIKE -> VENTILATING
        self.ch4_percent = 0.35
        self.co_ppm = 12.0
        self.dust_mg_m3 = 8.5
        self.airflow_ms = 6.5
        self.fan_status = "RUNNING"
        self.fan_mode_code = 1
        self.fan_rpm = 1200
        self.fan_power_kw = 45.0

    def update(self):
        self.step += 1

        # Каждые 20 шагов (40 сек) запускаем сценарий выброса метана для демонстрации
        if self.step % 20 == 10 and self.phase == "NORMAL":
            print("\n⚠️ [АВАРИЙНЫЙ СЦЕНАРИЙ] Прорыв метана и рост запыленности в лаве! ⚠️")
            self.phase = "LEAK_SPIKE"

        if self.phase == "NORMAL":
            self.ch4_percent = round(max(0.15, 0.35 + 0.08 * math.sin(self.step * 0.2) + random.uniform(-0.03, 0.03)), 2)
            self.co_ppm = round(max(3.0, 11.0 + 1.5 * math.cos(self.step * 0.15) + random.uniform(-0.5, 0.5)), 1)
            self.dust_mg_m3 = round(max(2.0, 7.5 + random.uniform(-0.8, 0.8)), 1)
            self.airflow_ms = round(6.5 + random.uniform(-0.2, 0.2), 2)

            self.fan_status = "RUNNING"
            self.fan_mode_code = 1
            self.fan_rpm = int(1200 + random.uniform(-15, 15))
            self.fan_power_kw = round(45.0 + random.uniform(-0.8, 0.8), 1)

        elif self.phase == "LEAK_SPIKE":
            # Резкий скачок газов выше порога 1.0% CH4
            self.ch4_percent = round(min(2.25, self.ch4_percent + random.uniform(0.35, 0.55)), 2)
            self.co_ppm = round(min(42.0, self.co_ppm + random.uniform(5.0, 9.0)), 1)
            self.dust_mg_m3 = round(min(28.0, self.dust_mg_m3 + random.uniform(3.5, 6.0)), 1)

            # Как только CH4 превышает 1.0%, автоматика включает форсаж ГВУ
            if self.ch4_percent > 1.0:
                self.fan_status = "EMERGENCY_BOOST"
                self.fan_mode_code = 2
                self.fan_rpm = int(1800 + random.uniform(-20, 20))
                self.fan_power_kw = round(74.5 + random.uniform(-1.0, 1.0), 1)
                self.airflow_ms = round(11.5 + random.uniform(-0.3, 0.3), 2)

            # После достижения пика переходим к фазе продувки шахты
            if self.ch4_percent >= 1.75:
                print("💨 [АВТОМАТИКА ГВУ] Включен режим EMERGENCY_BOOST (1800 об/мин). Идет интенсивная продувка...")
                self.phase = "VENTILATING"

        elif self.phase == "VENTILATING":
            # Форсированная вентиляция постепенно выдувает метан, CO и пыль
            self.ch4_percent = round(max(0.35, self.ch4_percent - random.uniform(0.22, 0.32)), 2)
            self.co_ppm = round(max(11.0, self.co_ppm - random.uniform(4.0, 6.5)), 1)
            self.dust_mg_m3 = round(max(7.5, self.dust_mg_m3 - random.uniform(3.0, 5.0)), 1)

            if self.ch4_percent > 0.8:
                self.fan_status = "EMERGENCY_BOOST"
                self.fan_mode_code = 2
                self.fan_rpm = int(1800 + random.uniform(-20, 20))
                self.fan_power_kw = round(74.0 + random.uniform(-1.0, 1.0), 1)
                self.airflow_ms = round(11.2 + random.uniform(-0.3, 0.3), 2)
            else:
                print("✅ [НОРМАЛИЗАЦИЯ] Концентрация метана снижена до безопасного уровня. ГВУ переведена в штатный режим.\n")
                self.phase = "NORMAL"

    def snapshot(self):
        alarm_flag = 1 if self.ch4_percent > 1.0 else 0
        return {
            SECTION_NAME: {
                "ch4_sensor": {
                    "value": self.ch4_percent,
                    "unit": "%",
                    "status": "CRITICAL" if alarm_flag else "NORMAL",
                    "alarm": alarm_flag
                },
                "co_sensor": {
                    "value": self.co_ppm,
                    "unit": "ppm",
                    "status": "WARNING" if self.co_ppm > 20.0 else "NORMAL"
                },
                "dust_sensor": {
                    "value": self.dust_mg_m3,
                    "unit": "mg/m3",
                    "status": "WARNING" if self.dust_mg_m3 > 15.0 else "NORMAL"
                },
                "airflow_sensor": {
                    "value": self.airflow_ms,
                    "unit": "m/s"
                }
            },
            FAN_NAME: {
                "fan_status": {
                    "value": self.fan_status,
                    "mode_code": self.fan_mode_code
                },
                "rpm": {
                    "value": self.fan_rpm,
                    "unit": "rpm"
                },
                "power_kw": {
                    "value": self.fan_power_kw,
                    "unit": "kW"
                }
            }
        }

def ditto_modify_features(name, features):
    """Формирует команду протокола Ditto для замены всех features через MQTT."""
    return {
        "topic": f"{NAMESPACE}/{name}/things/twin/commands/modify",
        "path": "/features",
        "value": {feat: {"properties": props} for feat, props in features.items()},
    }

# ==============================================================================
# 4. ГЛАВНЫЙ ЦИКЛ (MQTT ПАБЛИШИНГ)
# ==============================================================================
def main():
    print("=== Запуск системы газовой безопасности и вентиляции OpenEgiz ===")
    if not register_twins_in_ditto():
        print("Не удалось зарегистрировать двойников в Ditto. Проверьте, запущен ли стенд.")
        return 1

    client = mqtt.Client(client_id=f"openegiz-gas-sim-{os.getpid()}")
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except OSError as exc:
        print(f"[ОШИБКА MQTT] Не удалось подключиться к {MQTT_HOST}:{MQTT_PORT}: {exc}", file=sys.stderr)
        return 1

    client.loop_start()
    print(f"[MQTT] Подключено к {MQTT_HOST}:{MQTT_PORT}. Отправка телеметрии каждые 2 сек...\n")

    stop = False
    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    sim = GasSafetySimulation()

    while not stop:
        sim.update()
        snap = sim.snapshot()

        for name, features in snap.items():
            msg = json.dumps(ditto_modify_features(name, features))
            client.publish(f"{TOPIC_PREFIX}/{name}", msg, qos=0)

        icon = "🔴 АВАРИЯ" if sim.ch4_percent > 1.0 else "🟢 НОРМА"
        print(
            f"[{icon}] Шаг {sim.step:3d} | CH4: {sim.ch4_percent:4.2f}% | CO: {sim.co_ppm:4.1f} ppm | "
            f"Пыль: {sim.dust_mg_m3:4.1f} мг/м³ | Поток: {sim.airflow_ms:4.2f} м/с | "
            f"ГВУ: {sim.fan_status} ({sim.fan_rpm} RPM, {sim.fan_power_kw} кВт)"
        )
        time.sleep(2.0)

    client.loop_stop()
    client.disconnect()
    print("\nСимулятор остановлен.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
