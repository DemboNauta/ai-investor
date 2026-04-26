# ================================================================
# RELLENA ESTOS VALORES ANTES DE EJECUTAR
# ================================================================
$VPS_IP      = "178.104.140.243"          # IP del VPS
$VPS_USER    = "root"              # Usuario SSH (root, ubuntu, etc.)
$SSH_KEY     = "$env:USERPROFILE\.ssh\id_ed25519"                  # Ruta a tu clave privada .pem/.key
                                   # Ej: "C:\Users\edgar\.ssh\id_rsa"
                                   # Deja "" para usar contraseña
# ================================================================

$ErrorActionPreference = "Stop"
$PROJECT_DIR  = $PSScriptRoot
$REMOTE_DIR   = "/home/$VPS_USER/ai-investor"
if ($VPS_USER -eq "root") { $REMOTE_DIR = "/root/ai-investor" }

# Validaciones básicas
if ($VPS_IP -eq "0.0.0.0") { Write-Error "Pon la IP del VPS"; exit 1 }
$ENV_FILE = Join-Path $PROJECT_DIR ".env"
if (-not (Test-Path $ENV_FILE)) { Write-Error ".env no encontrado en $PROJECT_DIR"; exit 1 }

# Construir args SSH/SCP
$SSH_ARGS = @("-o", "StrictHostKeyChecking=no")
if ($SSH_KEY -ne "") { $SSH_ARGS += @("-i", $SSH_KEY) }
$SSH_TARGET = "${VPS_USER}@${VPS_IP}"

Write-Host ""
Write-Host "==> [1/4] Copiando archivos al VPS..." -ForegroundColor Cyan

# Copiar a carpeta temporal excluyendo basura
$TMP = "$env:TEMP\ai-investor-deploy"
if (Test-Path $TMP) { Remove-Item $TMP -Recurse -Force }
New-Item -ItemType Directory -Path $TMP | Out-Null

# robocopy: exit codes 0-7 son OK (no errores reales)
robocopy $PROJECT_DIR $TMP /E /XD __pycache__ .git /XF "*.pyc" "*.bat" ".env" "deploy.ps1" | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Error "robocopy falló (código $LASTEXITCODE)"; exit 1 }

# Crear carpeta remota y subir archivos + .env local
ssh @SSH_ARGS $SSH_TARGET "mkdir -p $REMOTE_DIR"
scp @SSH_ARGS -r "$TMP\*" "${SSH_TARGET}:${REMOTE_DIR}/"
scp @SSH_ARGS $ENV_FILE "${SSH_TARGET}:${REMOTE_DIR}/.env"
Remove-Item $TMP -Recurse -Force

Write-Host "==> [2/4] Configurando entorno..." -ForegroundColor Cyan

# Script de setup remoto — escrito a fichero para evitar infierno de comillas
$SETUP_SH = "$env:TEMP\ai_investor_setup.sh"
$setupContent = @"
#!/bin/bash
set -e

cd $REMOTE_DIR

# Python venv + dependencias
apt-get install -y python3-venv python3-pip > /dev/null 2>&1
python3 -m venv venv
source venv/bin/activate
pip install --quiet -r requirements.txt

# Carpeta de logs
mkdir -p logs

echo "ENTORNO_OK"
"@
$setupContent = $setupContent -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($SETUP_SH, $setupContent, [System.Text.UTF8Encoding]::new($false))

scp @SSH_ARGS $SETUP_SH "${SSH_TARGET}:/tmp/ai_investor_setup.sh"
$result = ssh @SSH_ARGS $SSH_TARGET "bash /tmp/ai_investor_setup.sh && rm /tmp/ai_investor_setup.sh"
if ($result -notcontains "ENTORNO_OK") {
    Write-Host $result
    Write-Error "Setup remoto falló"
    exit 1
}

Write-Host "==> [3/3] Configurando cron..." -ForegroundColor Cyan

$CRON_SH = "$env:TEMP\ai_investor_cron.sh"
$cronContent = @"
#!/bin/bash
set -e

REMOTE_DIR="$REMOTE_DIR"
PYTHON="`$REMOTE_DIR/venv/bin/python"
LOGS="`$REMOTE_DIR/logs"

# Eliminar entradas anteriores del proyecto si existen
(crontab -l 2>/dev/null | grep -v "ai-investor") | crontab - 2>/dev/null || true

# Añadir nuevas entradas
(crontab -l 2>/dev/null; cat << CRONEOF
0  * * * * cd `$REMOTE_DIR && `$PYTHON run_once.py moderate   >> `$LOGS/moderate.log   2>&1
5  * * * * cd `$REMOTE_DIR && `$PYTHON run_once.py aggressive >> `$LOGS/aggressive.log 2>&1
10 * * * * cd `$REMOTE_DIR && `$PYTHON run_once.py degen      >> `$LOGS/degen.log      2>&1
CRONEOF
) | crontab -

echo "CRON_OK"
"@
$cronContent = $cronContent -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($CRON_SH, $cronContent, [System.Text.UTF8Encoding]::new($false))

scp @SSH_ARGS $CRON_SH "${SSH_TARGET}:/tmp/ai_investor_cron.sh"
$result = ssh @SSH_ARGS $SSH_TARGET "bash /tmp/ai_investor_cron.sh && rm /tmp/ai_investor_cron.sh"
if ($result -notcontains "CRON_OK") {
    Write-Host $result
    Write-Error "Cron setup falló"
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Deploy completado." -ForegroundColor Green
Write-Host " Moderate:   cada hora en :00" -ForegroundColor Green
Write-Host " Aggressive: cada hora en :05" -ForegroundColor Green
Write-Host " Degen:      cada hora en :10" -ForegroundColor Green
Write-Host ""
Write-Host " Test manual en VPS:" -ForegroundColor Yellow
Write-Host "   source ~/ai-investor/venv/bin/activate" -ForegroundColor Yellow
Write-Host "   python run_once.py moderate" -ForegroundColor Yellow
Write-Host ""
Write-Host " Ver logs en VPS:" -ForegroundColor Yellow
Write-Host "   tail -f ~/ai-investor/logs/moderate.log" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Green
