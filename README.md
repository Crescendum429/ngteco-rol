# Solplast ERP

Sistema de gestión interno para Solplast: nómina (reloj NGTeco), inventario por piezas/lotes, comercial (cotizaciones, OC, facturas SRI, guías), catálogo, costos.

## Stack

- **Backend**: Flask 3 + Gunicorn (Render)
- **Frontend**: HTML monolítico con React 18 vía Babel Standalone (sin build pipeline)
- **DB**: Supabase (PostgreSQL) — storage key-value en tabla `config` + tabla `reportes`
- **SRI**: módulo `sri.py` con clave de acceso, XML 2.1.0, firma XAdES-BES (requiere cert .p12)

## Estructura

```
.
├── server.py                 # App factory + middleware + _build_data_jsx + _inject_html
├── nomina_logic.py           # Lógica pura de cálculo de nómina
├── app_helpers.py            # Serializers compartidos (emp/mat/prod a JS)
├── procesar_rol.py           # Parser XLS NGTeco + cálculo nómina + write Excel
├── costos.py                 # Cálculo de costos unitarios
├── storage.py                # Wrapper Supabase (key-value en `config` + `reportes`)
├── sri.py                    # SRI Ecuador: clave acceso, XML, firma, PDF RIDE
├── validation.py             # Helpers de validación de inputs
├── logger.py                 # Logging estructurado
├── Solplast-ERP.html         # SPA monolítica (servida con _inject_html)
├── app_routes/
│   ├── _auth.py              # Decorador require_auth compartido
│   ├── auth_bp.py            # /api/auth/* + rate limit login
│   ├── catalogo_bp.py        # empleados, materiales, productos, empaques, gastos
│   ├── comercial_bp.py       # collection genérico + recurrentes
│   ├── health_bp.py          # /api/health, /api/ready
│   ├── inventario_bp.py      # piezas, molido, auxiliar, lotes, BOM, registros v2
│   ├── nomina_bp.py          # upload XLS, corregir, calcular, snapshot, migración
│   ├── observability_bp.py   # /api/metrics, /api/config, /api/admin/backup
│   └── sri_bp.py             # emitir, autorizar, pdf, xml
├── tests/                    # pytest suite
├── docs/                     # documentación arquitectura
├── .github/workflows/test.yml
├── Dockerfile / Procfile
└── requirements.txt / requirements-dev.txt
```

## Variables de entorno

| Var | Requerido | Default | Descripción |
|---|---|---|---|
| `SUPABASE_URL` | Sí prod | `""` | URL del proyecto Supabase |
| `SUPABASE_KEY` | Sí prod | `""` | **Service role key** (bypasea RLS) |
| `SECRET_KEY` | Sí prod | dev-default | Firma de cookies de sesión Flask |
| `APP_PASSWORD` | Recomendado | `""` | Contraseña rol admin |
| `APP_PASSWORD_OP` | Recomendado | `""` | Contraseña rol operario |
| `SRI_AMBIENTE` | No | `1` | `1`=pruebas, `2`=producción |
| `SRI_CERT_PATH` | Solo firma real | `""` | Ruta al `.p12` |
| `SRI_CERT_PASSWORD` | Solo firma real | `""` | Password del `.p12` |
| `SRI_SIMULADO` | No | `true` | `true` devuelve respuestas SRI simuladas |
| `LOG_LEVEL` | No | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `PORT` | Render lo setea | `8080` | Puerto HTTP |
| `FLASK_ENV` | No | `production` | `development` desactiva cookies Secure |

## Endpoints clave

- `GET /` — sirve el HTML con datos reales inyectados
- `GET /api/health` — health check (sin auth)
- `GET /api/ready` — readiness con verificación de DB
- `POST /api/auth/login` — rate limit 10/5min por IP
- `POST /api/nomina/upload` — sube XLS del reloj
- `POST /api/nomina/calcular` — calcula nómina del período
- `POST /api/sri/emitir/<factura_id>` — emite factura al SRI
- `GET /api/metrics` — contadores internos por entidad
- `GET /api/admin/backup` — exporta TODO como JSON

## Versión

`APP_VERSION` en `server.py` línea 86. Semver: MAJOR.MINOR.PATCH.
- **PATCH**: bug fix, ajuste pequeño
- **MINOR**: feature nueva retrocompatible
- **MAJOR**: cambio que rompe compatibilidad

Visible en el sidebar del frontend (`v4.x.x`).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

20 tests cubren nómina lógica, SRI (clave acceso, XML, mod 11), validación, health.
CI corre en cada push a `main` via GitHub Actions.

## Deploy

Push a `main` → Render auto-deploy (~1-3 min). Verifica:
1. Sidebar muestra el `APP_VERSION` esperado
2. `/api/health` responde 200
3. `/api/ready` responde 200 con `db: "ok"`

## Backup

`GET /api/admin/backup` (con auth admin) devuelve JSON con todo el sistema. Para automatizar:

```bash
curl -b cookies.txt https://<tu-app>.onrender.com/api/admin/backup > backup_$(date +%Y%m%d).json
```

## SRI — paso a producción

1. Comprar `.p12` (BCE, Security Data, ANF AC, o Uanataca)
2. Subirlo al servidor / agregarlo como secret de Render
3. Setear:
   - `SRI_CERT_PATH=/path/al/cert.p12`
   - `SRI_CERT_PASSWORD=<password>`
   - `SRI_AMBIENTE=2` (cuando estés listo)
   - `SRI_SIMULADO=false`
4. Agregar a `requirements.txt`: `zeep`, `signxml`, `cryptography`
5. Probar contra `celcer.sri.gob.ec` primero (`SRI_AMBIENTE=1`)

Detalle técnico en `sri.py` y `docs/sri-notes.md`.

## Roadmap

- **Sprint B (pendiente)**: migración key-value JSON → tablas relacionales en Supabase. Plan en `docs/db-migration-proposal.md`.
- **Integración SRI live**: pendiente certificado del usuario.
- **Rediseño de UI** (en proceso con Claude Design): registro diario por piezas, inventario por tabs, pre-despacho con lotes FIFO.

## Histórico

- v4.0: handoff inicial Flask + handoff Design v1
- v4.1.x: SRI infra + banco horas + overrides + inventario v2 + módulos comercial/inventario/imprimibles
- v4.2.x: refactor a blueprints + observability + test suite
