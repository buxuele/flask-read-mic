

@echo off



cd flask_app/

echo Starting Background Desktop Agent...
start /B python desktop_agent.py

echo Starting Flask Server...
python app.py
