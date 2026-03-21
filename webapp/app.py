import os
import sqlite3
import asyncio
from contextlib import contextmanager
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import time
from logic.opcua_engine import write_opcua_value, write_opcua_multiple, ua

app = Flask(__name__)

# Rutas a los ficheros
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
        # Puente Sincrónico -> Asíncrono para Flask nativo
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success, message = loop.run_until_complete(write_opcua_value("Machine_State", nuevo_valor, ua.VariantType.Int16))
        loop.close()
        
        return jsonify({'success': success, 'message': message if success else None, 'error': None if success else message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/submit_box', methods=['POST'])
def submit_box():
    data = request.get_json()
    if not data or 'Description_Type' not in data:
        return jsonify({'success': False, 'error': 'No se proporcionó ningún tipo de caja (Description_Type)'}), 400

    description_type = data['Description_Type']
    
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute('SELECT box_type, altura, anchura, largo FROM cajas_config WHERE Description_Type = ?', (description_type,))
            row = cursor.fetchone()
        
        if not row:
            return jsonify({'success': False, 'error': f'Caja {description_type} no encontrada en la base de datos'}), 404
            
        variables = {
            "Description_Type": description_type,
            "Box_Type": row['box_type'],
            "Altura": row['altura'],
            "Anchura": row['anchura'],
            "Largo": row['largo']
        }
        
        # Puente Sincrónico -> Asíncrono
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success, message = loop.run_until_complete(write_opcua_multiple(variables))
        loop.close()
        
        return jsonify({'success': success, 'message': message if success else None, 'error': None if success else message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
