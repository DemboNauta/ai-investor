# Sube check_prod.sh al VPS y lo ejecuta, mostrando el resultado en consola
$VPS_IP   = "178.104.140.243"
$VPS_USER = "root"
$SSH_KEY  = "$env:USERPROFILE\.ssh\id_ed25519"

$SSH_ARGS = @("-o", "StrictHostKeyChecking=no")
if ($SSH_KEY -ne "") { $SSH_ARGS += @("-i", $SSH_KEY) }
$SSH_TARGET = "${VPS_USER}@${VPS_IP}"
$REMOTE_DIR = "/root/ai-investor"

Write-Host ""
Write-Host "==> Subiendo check_prod.sh..." -ForegroundColor Cyan
scp @SSH_ARGS (Join-Path $PSScriptRoot "check_prod.sh") "${SSH_TARGET}:${REMOTE_DIR}/check_prod.sh"

Write-Host "==> Ejecutando diagnóstico en producción..." -ForegroundColor Cyan
Write-Host ""
ssh @SSH_ARGS $SSH_TARGET "bash ${REMOTE_DIR}/check_prod.sh"
