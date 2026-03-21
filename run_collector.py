import asyncio
import sys
import os
import json

# Añadir la carpeta webapp al path para poder importar logic
sys.path.append(os.path.join(os.path.dirname(__file__), 'webapp'))

from logic.opcua_engine import DataCollector

VAR_NAMES = [
    "Machine_State", "Heartbeat", "Target_Speed", "Total_Parts_Produced",
    "Parts_OK", "Parts_NOK", "Last_Cycle_Time", "Availability",
    "Performance", "Quality", "Initial_Timestamp", "Final_Timestamp"
]

async def main():
    # Cargar el intervalo desde config.json
    interval = 0.1
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                interval = config.get("COLLECTOR_INTERVAL", interval)
        except: pass

    collector = DataCollector(VAR_NAMES)
    print(f"🚀 Iniciando colector de datos nativo (Intervalo: {interval}s)...")
    print("El panel de mandos web ahora funcionará de forma independiente.")
    print("Presiona Ctrl+C para detener la recolección.")
    await collector.collect_forever(interval=interval)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Colector detenido por el usuario.")
