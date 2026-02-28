import os
import json
import sqlite3
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Rutas a los ficheros
NOTEBOOK_PATH = os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'write_to_opcua.ipynb')
PRODUCT_NOTEBOOK_PATH = os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'write_product_config.ipynb')
PYTHON_EXEC = os.path.join(os.path.dirname(__file__), '..', 'venv', 'Scripts', 'python.exe')
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'datos.db')

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cajas_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_caja TEXT UNIQUE,
            box_type INTEGER,
            altura INTEGER,
            anchura INTEGER,
            largo INTEGER,
            fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Intento de añadir columna si la tabla ya existía de antes
    try:
        cursor.execute("ALTER TABLE cajas_config ADD COLUMN box_type INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass # La columna ya existe
    
    # Insert default data if table is empty
    cursor.execute('SELECT COUNT(*) FROM cajas_config')
    if cursor.fetchone()[0] == 0:
        default_boxes = [
            ('Pequeña', 1, 1, 1, 1),
            ('Mediana', 2, 2, 2, 2),
            ('Grande', 3, 3, 4, 5)
        ]
        cursor.executemany('''
            INSERT INTO cajas_config (tipo_caja, box_type, altura, anchura, largo)
            VALUES (?, ?, ?, ?, ?)
        ''', default_boxes)
        
    conn.commit()
    conn.close()

# Initialize DB on startup
init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/boxes', methods=['GET'])
def get_boxes():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM cajas_config ORDER BY id ASC')
        rows = cursor.fetchall()
        boxes = [dict(row) for row in rows]
        conn.close()
        return jsonify(boxes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/boxes', methods=['POST'])
def create_box():
    data = request.get_json()
    if not data or not all(k in data for k in ('tipo_caja', 'box_type', 'altura', 'anchura', 'largo')):
        return jsonify({'error': 'Faltan parámetros (tipo_caja, box_type, altura, anchura, largo)'}), 400
        
    try:
        tipo_caja = data['tipo_caja']
        box_type = int(data['box_type'])
        altura = int(data['altura'])
        anchura = int(data['anchura'])
        largo = int(data['largo'])
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO cajas_config (tipo_caja, box_type, altura, anchura, largo)
            VALUES (?, ?, ?, ?, ?)
        ''', (tipo_caja, box_type, altura, anchura, largo))
        conn.commit()
        conn.close()
        return jsonify({'message': f'Caja {tipo_caja} creada correctamente'})
    except sqlite3.IntegrityError:
        return jsonify({'error': f'La caja con nombre {tipo_caja} ya existe'}), 400
    except ValueError:
         return jsonify({'error': 'Altura, anchura y largo deben ser números enteros'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json()
    if not data or 'valor' not in data:
        return jsonify({'error': 'No se proporcionó ningún valor'}), 400

    try:
        nuevo_valor = int(data['valor'])
    except ValueError:
         return jsonify({'error': 'El valor debe ser un número entero'}), 400

    # 1. Leer el notebook
    try:
        with open(NOTEBOOK_PATH, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
    except FileNotFoundError:
        return jsonify({'error': f'No se encontró el archivo {NOTEBOOK_PATH}'}), 500
    except Exception as e:
        return jsonify({'error': f'Error al leer el notebook: {str(e)}'}), 500

    # 2. Modificar la celda con "variable_recibida ="
    modificado = False
    for cell in notebook.get('cells', []):
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            for i, line in enumerate(source):
                if line.startswith('variable_recibida ='):
                    source[i] = f'variable_recibida = {nuevo_valor}\n'
                    modificado = True
                    break
            if modificado:
                break

    if not modificado:
         return jsonify({'error': 'No se encontró "variable_recibida =" en el notebook'}), 500

    # 3. Guardar el notebook modificado
    try:
        with open(NOTEBOOK_PATH, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=1)
    except Exception as e:
        return jsonify({'error': f'Error al guardar el notebook: {str(e)}'}), 500

    # 4. Ejecutar el notebook usando nbconvert a través subprocess y el entorno virtual
    try:
        cmd = [PYTHON_EXEC, "-m", "jupyter", "nbconvert", "--execute", "--inplace", NOTEBOOK_PATH]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return jsonify({'message': f'Comando enviado correctamente'})
    except subprocess.CalledProcessError as e:
        print(f"Error stdout:\n{e.stdout}")
        print(f"Error stderr:\n{e.stderr}")
        return jsonify({'error': f'Error al ejecutar el notebook: Revisa la consola'}), 500
    except Exception as e:
        return jsonify({'error': f'Error inesperado al ejecutar: {str(e)}'}), 500

@app.route('/submit_box', methods=['POST'])
def submit_box():
    data = request.get_json()
    if not data or 'tipo_caja' not in data:
        return jsonify({'error': 'No se proporcionó ningún tipo de caja'}), 400

    tipo_caja = data['tipo_caja']
    
    # 1. Get box dimensions from DB
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT box_type, altura, anchura, largo FROM cajas_config WHERE tipo_caja = ?', (tipo_caja,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'error': f'Caja {tipo_caja} no encontrada en la base de datos'}), 404
            
        box_type_val = row['box_type']
        altura_val = row['altura']
        anchura_val = row['anchura']
        largo_val = row['largo']
    except Exception as e:
        return jsonify({'error': f'Error al consultar la base de datos: {str(e)}'}), 500

    # 2. Modify `write_product_config.ipynb`
    try:
        with open(PRODUCT_NOTEBOOK_PATH, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
            
        modificado_box_type = False
        modificado_altura = False
        modificado_anchura = False
        modificado_largo = False
        
        for cell in notebook.get('cells', []):
            if cell.get('cell_type') == 'code':
                source = cell.get('source', [])
                for i, line in enumerate(source):
                    if line.startswith('box_type_val ='):
                        source[i] = f'box_type_val = {box_type_val}\n'
                        modificado_box_type = True
                    elif line.startswith('altura_val ='):
                        source[i] = f'altura_val = {altura_val}\n'
                        modificado_altura = True
                    elif line.startswith('anchura_val ='):
                        source[i] = f'anchura_val = {anchura_val}\n'
                        modificado_anchura = True
                    elif line.startswith('largo_val ='):
                        source[i] = f'largo_val = {largo_val}\n'
                        modificado_largo = True
        
        if not (modificado_box_type and modificado_altura and modificado_anchura and modificado_largo):
             return jsonify({'error': 'No se encontraron las variables en el notebook'}), 500
             
        with open(PRODUCT_NOTEBOOK_PATH, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=1)
            
    except FileNotFoundError:
        return jsonify({'error': f'No se encontró {PRODUCT_NOTEBOOK_PATH}'}), 500
    except Exception as e:
        return jsonify({'error': f'Error al modificar el notebook: {str(e)}'}), 500

    # 3. Execute `write_product_config.ipynb`
    try:
        cmd = [PYTHON_EXEC, "-m", "jupyter", "nbconvert", "--execute", "--inplace", PRODUCT_NOTEBOOK_PATH]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return jsonify({'message': f'Configuración de la caja {tipo_caja} ({altura_val}x{anchura_val}x{largo_val}) enviada correctamente'})
    except subprocess.CalledProcessError as e:
        print(f"Error stdout:\n{e.stdout}")
        print(f"Error stderr:\n{e.stderr}")
        return jsonify({'error': f'Error al ejecutar el notebook: Revisa la consola'}), 500
    except Exception as e:
        return jsonify({'error': f'Error inesperado al ejecutar: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
