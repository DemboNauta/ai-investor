# Añadir dominio al VPS

## Contexto del proyecto

- Web principal: `generate_report.py` genera `web/index.html` (HTML estático)
- Chat API: `chat_server.py` corre en puerto **5001** (configurable con `CHAT_PORT`)
- Caddy sirve los estáticos Y proxea el chat — todo por el mismo dominio/puerto 443

---

## Arquitectura objetivo

```
Internet (HTTPS)
       │
       ▼
  Caddy :443
       │
       ├── dominio.com/*        → archivos estáticos de web/
       └── dominio.com/api/*    → localhost:5001 (chat_server.py)
```

> El frontend en generate_report.py usa `window.location.hostname` para construir
> la URL del chat — al ir todo por el mismo dominio/puerto funciona sin cambios de CORS.
> **PENDIENTE antes de activar dominio:** cambiar línea 1434 de generate_report.py:
> `const CHAT_API = window.location.protocol + '//' + window.location.hostname + ':5001';`
> → `const CHAT_API = window.location.protocol + '//' + window.location.hostname;`

---

## Paso 1: Comprar dominio en Dondominio

1. Ir a [dondominio.com](https://www.dondominio.com)
2. Buscar dominio → comprar (plan básico, sin extras)
3. No tocar DNS aún — se configura en Paso 2

---

## Paso 2: Configurar DNS

### Opción A — DNS directo en Dondominio (simple)

Panel Dondominio → Dominios → tu dominio → **Gestionar DNS** → añadir:

| Tipo | Nombre | Valor | TTL |
|------|--------|-------|-----|
| A | `@` | `<IP_VPS>` | 300 |
| A | `www` | `<IP_VPS>` | 300 |

> IP del VPS: `curl ifconfig.me` desde el servidor

### Opción B — Cloudflare como DNS (recomendado)

Ventajas: DDoS protection, oculta IP real, cache, SSL extra.

1. Crear cuenta en [cloudflare.com](https://www.cloudflare.com)
2. Añadir dominio → Cloudflare escanea DNS existente
3. En Dondominio → **Nameservers** → cambiar a los que da Cloudflare
4. En Cloudflare añadir registros A:

| Tipo | Nombre | Valor | Proxy |
|------|--------|-------|-------|
| A | `@` | `<IP_VPS>` | Nube naranja ✓ |
| A | `www` | `<IP_VPS>` | Nube naranja ✓ |

5. Cloudflare SSL/TLS → modo **Full**

> Propagación: minutos con Cloudflare, hasta 24h con DNS directo

---

## Paso 3: Instalar Caddy en el VPS

```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install caddy
```

---

## Paso 4: Configurar Caddy

Editar `/etc/caddy/Caddyfile`:

```
tudominio.com, www.tudominio.com {
    # Sirve el HTML estático generado por generate_report.py
    root * /ruta/al/proyecto/web
    file_server

    # Proxea el chat al servidor Python
    reverse_proxy /api/* localhost:5001
}
```

> Reemplazar `/ruta/al/proyecto/web` con la ruta real en el VPS (ej: `/root/ai-investor/web`)

Aplicar:

```bash
systemctl enable caddy
systemctl start caddy
# o si ya corría:
systemctl reload caddy
```

SSL de Let's Encrypt se obtiene automáticamente en el primer request.

---

## Paso 5: Modificar generate_report.py antes de activar

En `generate_report.py` línea 1434, cambiar:

```js
// ANTES (solo funciona con IP directa)
const CHAT_API = window.location.protocol + '//' + window.location.hostname + ':5001';

// DESPUÉS (funciona con dominio vía Caddy)
const CHAT_API = window.location.protocol + '//' + window.location.hostname;
```

Regenerar el HTML tras el cambio:

```bash
python generate_report.py
```

---

## Paso 6: Verificar

```bash
# Logs de Caddy
journalctl -u caddy -f

# Test desde fuera
curl -I https://tudominio.com          # debe devolver 200
curl https://tudominio.com/api/chat/moderate -X POST \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'              # debe devolver respuesta JSON
```

---

## Añadir más dominios/subdominios (flujo rápido)

1. Añadir registro A en DNS → IP VPS
2. Añadir bloque en `/etc/caddy/Caddyfile`
3. `systemctl reload caddy`
4. SSL automático

---

## Notas

- `chat_server.py` debe estar corriendo en el VPS cuando lleguen peticiones al chat
- `generate_report.py` se ejecuta vía cron — el HTML se regenera automáticamente
- Caddy renueva certificados Let's Encrypt cada ~60 días (expiran a los 90)
- Para ver IP del VPS: `curl ifconfig.me` desde el servidor
