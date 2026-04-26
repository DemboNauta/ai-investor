# Despliega la última versión de main al VPS
# Uso: .\update_prod.ps1

$VPS_IP     = "178.104.140.243"
$VPS_USER   = "root"
$SSH_KEY    = "$env:USERPROFILE\.ssh\id_ed25519"
$REMOTE_DIR = "/root/ai-investor"

$SSH_ARGS   = @("-o", "StrictHostKeyChecking=no", "-i", $SSH_KEY)
$SSH_TARGET = "${VPS_USER}@${VPS_IP}"

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==> [1/3] Subiendo archivos Python al VPS..." -ForegroundColor Cyan

$FILES = @(
    "agent.py", "config.py", "data.py", "generate_report.py",
    "main.py", "memory.py", "notifier.py", "portfolio.py",
    "profiles.py", "run_once.py", "view.py"
)

foreach ($f in $FILES) {
    $local = Join-Path $PSScriptRoot $f
    if (Test-Path $local) {
        scp @SSH_ARGS $local "${SSH_TARGET}:${REMOTE_DIR}/${f}"
        Write-Host "   OK $f" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "==> [2/3] Regenerando informe web..." -ForegroundColor Cyan

ssh @SSH_ARGS $SSH_TARGET @"
set -e
cd $REMOTE_DIR
source venv/bin/activate

python generate_report.py && echo "REPORT_OK"
"@

Write-Host ""
Write-Host "==> [3/3] Verificando servidor web en :8080..." -ForegroundColor Cyan

ssh @SSH_ARGS $SSH_TARGET @"
mkdir -p $REMOTE_DIR/logs

if lsof -i :8080 -t > /dev/null 2>&1; then
    echo "  Servidor ya corriendo en :8080"
else
    nohup python3 -m http.server 8080 --directory $REMOTE_DIR/web > $REMOTE_DIR/logs/web.log 2>&1 &
    echo "  Servidor arrancado (PID \$!)"
fi
"@

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Deploy completado." -ForegroundColor Green
Write-Host " Dashboard: http://${VPS_IP}:8080" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
