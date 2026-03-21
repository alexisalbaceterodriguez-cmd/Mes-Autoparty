import asyncio
import sqlite3
import logging
import os
import json
from datetime import datetime
from asyncua import Client, ua

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "../../config.json")
ENDPOINT = "opc.tcp://192.168.0.20:4840"
FOLDER_NAME = "MES"

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            ENDPOINT = config.get("OPCUA_ENDPOINT", ENDPOINT)
            FOLDER_NAME = config.get("OPCUA_FOLDER", FOLDER_NAME)
    except Exception as e:
        print(f"Error loading config.json: {e}")

DB_PATH = os.path.join(os.path.dirname(__file__), "../../database/datos.db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('opcua_engine')

# Caché global: guardamos los NODE_IDs como strings para que funcionen con nuevos clientes
_cached_ids = {} # Estructura: {"FOLDER": "ns=X;i=Y", "VarName": "ns=X;s=Z"}

async def get_target_nodes(client, folder_name, var_names=None):
    """Busca y resuelve los NodeIDs. Usa caché persistente de strings para máxima velocidad."""
    global _cached_ids
    found_nodes = {}
    
    # 1. Intentar resolver la carpeta desde el caché
    folder_id = _cached_ids.get("__FOLDER__")
    folder_node = None
    if folder_id:
        try:
            folder_node = client.get_node(folder_id)
            # Validar si sigue siendo el mismo browse name
            bname = await folder_node.read_browse_name()
            if bname.Name != folder_name:
                folder_node = None
        except:
            folder_node = None

    # 2. Si no hay carpeta en caché, buscarla recursivamente (Lento VPN)
    if not folder_node:
        async def walk(node, depth):
            if depth > 5: return None
            try: children = await node.get_children()
            except: return None
            for child in children:
                try: 
                    bname = await child.read_browse_name()
                    if bname.Name == folder_name: return child
                except: continue
                res = await walk(child, depth + 1)
                if res: return res
            return None
        folder_node = await walk(client.nodes.objects, 0)
        if folder_node:
            _cached_ids["__FOLDER__"] = folder_node.nodeid.to_string()

    if not folder_node:
        return None, {}

    # 3. Localizar variables
    var_names = var_names or []
    for vname in var_names:
        # Intentar desde caché
        vid = _cached_ids.get(vname)
        if vid:
            try:
                found_nodes[vname] = client.get_node(vid)
                continue
            except: pass
            
        # Si no, buscar en los hijos de la carpeta
        for child in await folder_node.get_children():
            bname = await child.read_browse_name()
            if bname.Name == vname:
                _cached_ids[vname] = child.nodeid.to_string()
                found_nodes[vname] = child
                break
                
    return folder_node, found_nodes

async def write_opcua_value(var_name, value, variant_type=None):
    """Escribe un valor asíncrono usando caché persistente."""
    try:
        async with Client(url=ENDPOINT, timeout=10) as client:
            _, nodes = await get_target_nodes(client, FOLDER_NAME, [var_name])
            target_node = nodes.get(var_name)
            if not target_node:
                return False, f"No se encontró: {var_name}"
            
            if variant_type:
                dv = ua.DataValue(ua.Variant(value, variant_type))
                await target_node.write_value(dv)
            else:
                await target_node.write_value(value)
            return True, f"Actualizado: {var_name} = {value}"
    except Exception as e:
        return False, str(e)

async def write_opcua_multiple(variables_dict):
    """Escribe múltiples valores asíncronos usando caché persistente."""
    try:
        results = []
        async with Client(url=ENDPOINT, timeout=10) as client:
            _, nodes = await get_target_nodes(client, FOLDER_NAME, list(variables_dict.keys()))
            for name, value in variables_dict.items():
                node = nodes.get(name)
                if not node:
                    results.append(f"❌ '{name}' no encontrado")
                    continue
                vtype = ua.VariantType.String if isinstance(value, str) else ua.VariantType.Int16
                dv = ua.DataValue(ua.Variant(value, vtype))
                await node.write_value(dv)
                results.append(f"✅ '{name}' -> {value}")
        return True, "\n".join(results)
    except Exception as e:
        return False, str(e)

class DataCollector:
    def __init__(self, var_names):
        self.var_names = var_names
        self.running = False

    def init_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mes_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                Machine_State INTEGER,
                Heartbeat INTEGER,
                Target_Speed REAL,
                Total_Parts_Produced INTEGER,
                Parts_OK INTEGER,
                Parts_NOK INTEGER,
                Last_Cycle_Time DECIMAL(5,3),
                Availability DECIMAL(5,3),
                Performance DECIMAL(5,3),
                Quality DECIMAL(5,3),
                Initial_Timestamp char(50),
                Final_Timestamp char(50)
            )
        ''')
        conn.commit()
        return conn

    async def collect_forever(self, interval=1):
        self.running = True
        conn = self.init_db()
        while self.running:
            try:
                async with Client(url=ENDPOINT, timeout=10) as client:
                    _, nodes = await get_target_nodes(client, FOLDER_NAME, self.var_names)
                    if not nodes:
                        logger.error("Browsing nodes failed. Reintento en 5s...")
                        await asyncio.sleep(5)
                        continue
                        
                    while self.running:
                        # Leer todos los nodos en paralelo para evitar acumular latencia de red (VPN)
                        node_list = list(nodes.items()) # [(name, node), ...]
                        read_tasks = [node.read_value() for _, node in node_list]
                        results = await asyncio.gather(*read_tasks)
                        
                        data = {}
                        for i, (name, _) in enumerate(node_list):
                            val = results[i]
                            if name in ["Initial_Timestamp", "Final_Timestamp"] and isinstance(val, str):
                                try:
                                    dt_obj = datetime.strptime(val, "%H:%M:%S - %Y-%m-%d")
                                    val = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                                except: pass
                            data[name] = val
                        
                        if data:
                            cursor = conn.cursor()
                            cols = ', '.join(data.keys())
                            vals = list(data.values())
                            placeholders = ', '.join(['?'] * len(vals))
                            cursor.execute(f"INSERT INTO mes_data ({cols}) VALUES ({placeholders})", vals)
                            conn.commit()
                            logger.info(f"💾 Registro 100ms | {datetime.now()}")
                        await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Error colector: {e}. Reintentando en 5s...")
                await asyncio.sleep(5)
