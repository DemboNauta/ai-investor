# Sube generate_report.py al VPS y levanta el servidor web si no está corriendo
$VPS_IP   = "178.104.140.243"
$VPS_USER = "root"
$SSH_KEY  = "$env:USERPROFILE\.ssh\id_ed25519"

$REMOTE_DIR = "/root/ai-investor"
$SSH_ARGS   = @("-o", "StrictHostKeyChecking=no", "-i", $SSH_KEY)
$SSH_TARGET = "${VPS_USER}@${VPS_IP}"

Write-Host "==> Subiendo archivos modificados..." -ForegroundColor Cyan
scp @SSH_ARGS "$PSScriptRoot\generate_report.py" "${SSH_TARGET}:${REMOTE_DIR}/generate_report.py"
scp @SSH_ARGS "$PSScriptRoot\run_once.py"        "${SSH_TARGET}:${REMOTE_DIR}/run_once.py"

Write-Host "==> Ejecutando en VPS..." -ForegroundColor Cyan
ssh @SSH_ARGS $SSH_TARGET @"
set -e
cd $REMOTE_DIR
source venv/bin/activate

# Generar HTML inicial
python generate_report.py

# Levantar servidor si no está ya corriendo en :8080
if ! lsof -i :8080 -t > /dev/null 2>&1; then
    mkdir -p web
    nohup python3 -m http.server 8080 --directory web > logs/web.log 2>&1 &
    echo "Servidor arrancado PID $!"
else
    echo "Servidor ya corriendo en :8080"
fi

# Añadir cron para regenerar el HTML cada 5 min (si no existe ya)
(crontab -l 2>/dev/null | grep -v "generate_report") | crontab - 2>/dev/null || true
(crontab -l 2>/dev/null; echo "*/5 * * * * cd $REMOTE_DIR && venv/bin/python generate_report.py >> logs/web.log 2>&1") | crontab -

echo "DONE"
"@

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Dashboard: http://${VPS_IP}:8080" -ForegroundColor Green
Write-Host " HTML regenera cada 5 min via cron" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
