@echo off
title MES Autoparty
echo Iniciando el entorno y la aplicacion...

:: Navegar a la ruta del proyecto
cd /d "C:\Users\alexi\Desktop\Proyectos\Mes Autoparty\Mes-Autoparty"

:: Activar el entorno virtual
call .\venv\Scripts\activate.bat

:: Abrir el navegador web automaticamente
start http://127.0.0.1:5000

:: Ejecutar el servidor web
python webapp\app.py

pause
