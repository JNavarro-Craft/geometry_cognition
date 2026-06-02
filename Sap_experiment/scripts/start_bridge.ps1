# Arranca el bridge HTTP de SAP (attach-only) en 127.0.0.1:8766.
# Requiere SAP2000 ya abierto con un modelo. Cualquier agente lo corre con un solo comando.
$env:PYTHONPATH = (Resolve-Path "$PSScriptRoot\..\.."); python -m uvicorn Sap_experiment.sap_bridge.main:app --host 127.0.0.1 --port 8766
