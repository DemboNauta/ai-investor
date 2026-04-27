# Acceso Escritorio Remoto (VPS)

## Conexión rápida

```powershell
.\setup_rdp.ps1
```

Abre túnel SSH + lanza mstsc automáticamente. Credenciales xrdp: usuario `root`, contraseña del servidor.

**Ctrl+C** para cerrar túnel cuando termines.

## Cómo funciona

Puerto 3389 bloqueado en firewall del servidor (no expuesto a internet).  
El script abre túnel SSH: `localhost:3389 → servidor:3389`.  
mstsc conecta a `localhost:3389` — tráfico va cifrado por SSH.

## Requisitos

- Clave SSH en `~/.ssh/id_ed25519`
- xrdp instalado y activo en servidor
- UFW bloqueando 3389 desde exterior

## Setup inicial (ya hecho, solo referencia)

```bash
# En servidor
apt install -y xrdp xfce4 xfce4-goodies
echo "startxfce4" >> ~/.xsession
systemctl enable xrdp
passwd root          # contraseña para login xrdp
ufw deny 3389/tcp
ufw allow OpenSSH
ufw enable
```

## Conexión manual (sin script)

**PowerShell 1 — mantener abierto:**
```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" -L 3389:localhost:3389 -N root@178.104.140.243
```

**PowerShell 2:**
```powershell
mstsc /v:localhost:3389
```
