import os
import json
import subprocess
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Rutas a los ficheros
NOTEBOOK_PATH = os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'write_to_opcua.ipynb')
PYTHON_EXEC = os.path.join(os.path.dirname(__file__), '..', 'venv', 'Scripts', 'python.exe')

@app.route('/')
def index():
    return render_template('index.html')

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
        # Usamos el python del entorno virtual para invocar nbconvert
        # '--execute' ejecuta el notebook
        # '--inplace' sobrescribe el notebook actual con los resultados de la ejecución
        cmd = [PYTHON_EXEC, "-m", "jupyter", "nbconvert", "--execute", "--inplace", NOTEBOOK_PATH]
        
        # Ejecutamos el comando y capturamos la salida
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Opcional: imprimir el log en la consola de Flask para debugging
        print("--- Resultado de nbconvert ---")
        print(result.stdout)
        print("------------------------------")

        return jsonify({'message': f'Valor {nuevo_valor} enviado correctamente mediante nbconvert'})

    except subprocess.CalledProcessError as e:
        print(f"Error stdout:\n{e.stdout}")
        print(f"Error stderr:\n{e.stderr}")
        return jsonify({'error': f'Error al ejecutar el notebook: Revisa la consola'}), 500
    except Exception as e:
        return jsonify({'error': f'Error inesperado al ejecutar: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
