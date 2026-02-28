import os
import json
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import time

app = Flask(__name__)

# Rutas a los ficheros
NOTEBOOK_PATH = os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'write_to_opcua.ipynb')
PRODUCT_NOTEBOOK_PATH = os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'write_product_config.ipynb')
PYTHON_EXEC = os.path.join(os.path.dirname(__file__), '..', 'venv', 'Scripts', 'python.exe')
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'datos.db')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'images')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Utility Functions ---

@contextmanager
def get_db_connection():
    """Maneja la conexión a SQLite en un bloque con soporte para diccionarios."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        yield conn, cursor
        conn.commit()
    finally:
        conn.close()

def execute_notebook(notebook_path, success_message):
    """Ejecuta un notebook Jupyter usando subprocess y devuelve la respuesta JSON."""
    try:
        cmd = [PYTHON_EXEC, "-m", "jupyter", "nbconvert", "--execute", "--inplace", notebook_path]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return jsonify({'success': True, 'message': success_message})
    except subprocess.CalledProcessError as e:
        print(f"Error stdout:\n{e.stdout}")
        print(f"Error stderr:\n{e.stderr}")
        return jsonify({'success': False, 'error': 'Error al ejecutar el notebook: Revisa la consola'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error inesperado al ejecutar: {str(e)}'}), 500

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cajas_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Description_Type TEXT UNIQUE,
            box_type INTEGER,
            altura INTEGER,
            anchura INTEGER,
            largo INTEGER,
            image_path TEXT,
            fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Intento de añadir columna si la tabla ya existía de antes
    try:
        cursor.execute("ALTER TABLE cajas_config ADD COLUMN box_type INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass # La columna ya existe
        
    try:
        cursor.execute("ALTER TABLE cajas_config ADD COLUMN image_path TEXT")
    except sqlite3.OperationalError:
        pass # La columna ya existe
    
    # Intento de renombrar la columna si existe como tipo_caja
    try:
        cursor.execute("ALTER TABLE cajas_config RENAME COLUMN tipo_caja TO Description_Type")
    except sqlite3.OperationalError:
        pass # Quizas ya ha sido renombrada o no existia antigua

    # Insert default data if table is empty
    cursor.execute('SELECT COUNT(*) FROM cajas_config')
    if cursor.fetchone()[0] == 0:
        default_boxes = [
            ('Pequeña', 1, 1, 1, 1),
            ('Mediana', 2, 2, 2, 2),
            ('Grande', 3, 3, 4, 5)
        ]
        cursor.executemany('''
            INSERT INTO cajas_config (Description_Type, box_type, altura, anchura, largo)
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
        with get_db_connection() as (conn, cursor):
            cursor.execute('SELECT * FROM cajas_config ORDER BY id ASC')
            rows = cursor.fetchall()
        boxes = [dict(row) for row in rows]
        return jsonify(boxes)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/boxes', methods=['POST'])
def create_box():
    try:
        description_type = request.form.get('Description_Type')
        box_type_str = request.form.get('box_type')
        altura_str = request.form.get('altura')
        anchura_str = request.form.get('anchura')
        largo_str = request.form.get('largo')
        
        if not all([description_type, box_type_str, altura_str, anchura_str, largo_str]):
            return jsonify({'success': False, 'error': 'Faltan parámetros (Description_Type, box_type, altura, anchura, largo)'}), 400

        box_type = int(box_type_str)
        altura = int(altura_str)
        anchura = int(anchura_str)
        largo = int(largo_str)
        
        image_path = None
        file = request.files.get('image')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            unique_filename = f"{int(time.time())}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)
            image_path = f"/static/images/{unique_filename}"
        
        with get_db_connection() as (conn, cursor):
            cursor.execute('''
                INSERT INTO cajas_config (Description_Type, box_type, altura, anchura, largo, image_path)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (description_type, box_type, altura, anchura, largo, image_path))
            
        return jsonify({'success': True, 'message': f'Caja {description_type} creada correctamente'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': f'La caja con nombre {description_type} ya existe'}), 400
    except ValueError:
         return jsonify({'success': False, 'error': 'Altura, anchura y largo deben ser números enteros'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json()
    if not data or 'valor' not in data:
        return jsonify({'success': False, 'error': 'No se proporcionó ningún valor'}), 400

    try:
        nuevo_valor = int(data['valor'])
    except ValueError:
         return jsonify({'success': False, 'error': 'El valor debe ser un número entero'}), 400

    # 1. Leer el notebook
    try:
        with open(NOTEBOOK_PATH, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
    except FileNotFoundError:
        return jsonify({'success': False, 'error': f'No se encontró el archivo {NOTEBOOK_PATH}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al leer el notebook: {str(e)}'}), 500

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
         return jsonify({'success': False, 'error': 'No se encontró "variable_recibida =" en el notebook'}), 500

    # 3. Guardar el notebook modificado
    try:
        with open(NOTEBOOK_PATH, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=1)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al guardar el notebook: {str(e)}'}), 500

    # 4. Ejecutar el notebook usando el helper
    return execute_notebook(NOTEBOOK_PATH, 'Comando enviado correctamente')

@app.route('/submit_box', methods=['POST'])
def submit_box():
    data = request.get_json()
    if not data or 'Description_Type' not in data:
        return jsonify({'success': False, 'error': 'No se proporcionó ningún tipo de caja (Description_Type)'}), 400

    description_type = data['Description_Type']
    
    # 1. Get box dimensions from DB
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute('SELECT box_type, altura, anchura, largo FROM cajas_config WHERE Description_Type = ?', (description_type,))
            row = cursor.fetchone()
        
        if not row:
            return jsonify({'success': False, 'error': f'Caja {description_type} no encontrada en la base de datos'}), 404
            
        box_type_val = row['box_type']
        altura_val = row['altura']
        anchura_val = row['anchura']
        largo_val = row['largo']
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al consultar la base de datos: {str(e)}'}), 500

    # 2. Modify `write_product_config.ipynb`
    try:
        with open(PRODUCT_NOTEBOOK_PATH, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
            
        modificado_description_type = False
        modificado_box_type = False
        modificado_altura = False
        modificado_anchura = False
        modificado_largo = False
        
        for cell in notebook.get('cells', []):
            if cell.get('cell_type') == 'code':
                source = cell.get('source', [])
                for i, line in enumerate(source):
                    if line.startswith('description_type_val ='):
                        source[i] = f'description_type_val = "{description_type}"\n'
                        modificado_description_type = True
                    elif line.startswith('box_type_val ='):
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
        
        if not (modificado_description_type and modificado_box_type and modificado_altura and modificado_anchura and modificado_largo):
             return jsonify({'success': False, 'error': 'No se encontraron las variables en el notebook'}), 500
             
        with open(PRODUCT_NOTEBOOK_PATH, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=1)
            
    except FileNotFoundError:
        return jsonify({'success': False, 'error': f'No se encontró {PRODUCT_NOTEBOOK_PATH}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al modificar el notebook: {str(e)}'}), 500

    # 3. Execute `write_product_config.ipynb`
    return execute_notebook(PRODUCT_NOTEBOOK_PATH, f'Configuración de la caja {description_type} ({altura_val}x{anchura_val}x{largo_val}) enviada')

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Devuelve el histórico de las últimas 100 lecturas para el dashboard."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute('SELECT * FROM mes_data ORDER BY id DESC LIMIT 100')
            rows = cursor.fetchall()
        
        stats = [dict(row) for row in reversed(rows)]
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/kpi', methods=['GET'])
def get_kpi():
    """Devuelve la lectura más reciente para visualizar los KPIs en tiempo real."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute('SELECT * FROM mes_data ORDER BY id DESC LIMIT 1')
            row = cursor.fetchone()
        
        if row:
            return jsonify({'success': True, 'data': dict(row)})
        return jsonify({'success': False, 'error': 'No data'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
