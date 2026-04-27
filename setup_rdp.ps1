# ================================================================
# Abre túnel SSH seguro para escritorio remoto (xrdp)
# Puerto 3389 NO expuesto — solo accesible via túnel
# ================================================================
$VPS_IP   = "178.104.140.243"
$VPS_USER = "root"
$SSH_KEY  = "$env:USERPROFILE\.ssh\id_ed25519"
# ================================================================

$SSH_ARGS = @("-o", "StrictHostKeyChecking=no", "-o", "ExitOnForwardFailure=yes")
if ($SSH_KEY -ne "") { $SSH_ARGS += @("-i", $SSH_KEY) }
$SSH_TARGET = "${VPS_USER}@${VPS_IP}"

Write-Host ""
Write-Host "==> Verificando xrdp en servidor..." -ForegroundColor Cyan
$status = ssh @SSH_ARGS $SSH_TARGET "systemctl is-active xrdp 2>/dev/null"
if ($status -ne "active") {
    Write-Host "  xrdp no activo. Arrancando..." -ForegroundColor Yellow
    ssh @SSH_ARGS $SSH_TARGET "systemctl start xrdp"
}

Write-Host "==> Abriendo túnel SSH (localhost:3389 → servidor:3389)..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Túnel activo. Conecta con:" -ForegroundColor Green
Write-Host "    mstsc /v:localhost:3389" -ForegroundColor White
Write-Host "    usuario: $VPS_USER" -ForegroundColor White
Write-Host ""
Write-Host "  Ctrl+C para cerrar túnel." -ForegroundColor Yellow
Write-Host ""

# Abre mstsc automáticamente tras 2 segundos
Start-Job { Start-Sleep 2; mstsc /v:localhost:3389 } | Out-Null

ssh @SSH_ARGS -L 3389:localhost:3389 -N $SSH_TARGET

Write-Host ""
Write-Host "  Túnel cerrado." -ForegroundColor Red
