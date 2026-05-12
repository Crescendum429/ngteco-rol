# Propuesta de migración DB: key-value → tablas relacionales

## Estado actual

Todo el storage usa dos tablas en Supabase:

- `config` — `(key TEXT PRIMARY KEY, value JSONB)` — blobs JSON por entidad
- `reportes` — `(id TEXT PRIMARY KEY, periodo TEXT, data JSONB, cls JSONB, uploaded_at TIMESTAMPTZ)`

Las entidades grandes (empleados, productos, clientes, lotes, mov_inventario, facturas) viven como un solo blob JSON cada una en `config`. Funciona pero tiene tres problemas reales:

1. **Cada update sobrescribe el blob completo** → race condition si 2 requests simultáneos editan la misma entidad
2. **No hay queries SQL eficientes** → no se puede filtrar/ordenar/agregar desde Supabase Studio ni desde reportes BI
3. **Difícil de escalar** → JSON grandes en una sola fila no escala bien si crecen mucho

## Decisión

Migrar 6 entidades a tablas dedicadas. Mantener `config` para configs reales (overrides, gastos fijos, arrastres, BOM).

## Esquema propuesto

```sql
-- empleados
CREATE TABLE empleados (
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  cargo TEXT,
  salario NUMERIC(10,2) NOT NULL DEFAULT 0,
  horas_base INT NOT NULL DEFAULT 8,
  transporte_dia NUMERIC(10,2) DEFAULT 0,
  region TEXT DEFAULT 'Sierra/Amazonia',
  fondos_reserva BOOLEAN DEFAULT FALSE,
  prestamo_iess NUMERIC(10,2) DEFAULT 0,
  descuento_iess BOOLEAN DEFAULT TRUE,
  ocultar BOOLEAN DEFAULT FALSE,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- productos
CREATE TABLE productos (
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  kind TEXT DEFAULT 'vaso',
  unidades_caja INT DEFAULT 1000,
  peso_g NUMERIC(10,3) DEFAULT 0,
  factor_complejidad NUMERIC(5,2) DEFAULT 1.0,
  costo_unit NUMERIC(10,6) DEFAULT 0,
  costo_caja NUMERIC(10,2) DEFAULT 0,
  desactivado BOOLEAN DEFAULT FALSE,
  cliente_id TEXT REFERENCES clientes(id),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- clientes
CREATE TABLE clientes (
  id TEXT PRIMARY KEY,
  razon_social TEXT NOT NULL,
  nombre_comercial TEXT,
  ruc TEXT,
  tipo TEXT DEFAULT 'Sociedad',
  obligado_contabilidad BOOLEAN DEFAULT TRUE,
  email_fact TEXT,
  email_contacto TEXT,
  telefono TEXT,
  celular TEXT,
  contacto_nombre TEXT,
  contacto_cargo TEXT,
  dir_matriz JSONB,
  dir_sucursal JSONB,
  credito_dias INT DEFAULT 30,
  credito_limite NUMERIC(12,2) DEFAULT 0,
  agente_retencion BOOLEAN DEFAULT FALSE,
  resolucion_retencion TEXT,
  notas TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_clientes_ruc ON clientes(ruc);
CREATE INDEX idx_clientes_razon ON clientes(razon_social);

-- lotes (producto terminado por caja con trazabilidad)
CREATE TABLE lotes (
  id TEXT PRIMARY KEY,
  producto_id TEXT REFERENCES productos(id),
  cliente_id TEXT REFERENCES clientes(id),
  fecha_elaboracion DATE NOT NULL,
  fecha_caducidad DATE,
  cantidad_cajas INT NOT NULL DEFAULT 1,
  unidades_caja INT DEFAULT 0,
  peso_neto NUMERIC(10,2) DEFAULT 0,
  peso_total NUMERIC(10,2) DEFAULT 0,
  responsable TEXT,
  despachado BOOLEAN DEFAULT FALSE,
  despachado_en TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_lotes_producto ON lotes(producto_id) WHERE NOT despachado;
CREATE INDEX idx_lotes_fecha ON lotes(fecha_elaboracion);
CREATE INDEX idx_lotes_fifo ON lotes(producto_id, fecha_elaboracion) WHERE NOT despachado;

-- movimientos de inventario (log inmutable)
CREATE TABLE mov_inventario (
  id BIGSERIAL PRIMARY KEY,
  fecha DATE NOT NULL DEFAULT CURRENT_DATE,
  tipo TEXT NOT NULL,  -- entrada, salida, ajuste, baja, transferencia, produccion, consumo
  clase TEXT NOT NULL, -- mp, pt, pieza, molido, auxiliar, descarte
  item_id TEXT NOT NULL,
  cantidad NUMERIC(12,3) NOT NULL,
  unidad TEXT,
  ref TEXT,
  nota TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mov_inv_clase_item ON mov_inventario(clase, item_id, fecha DESC);
CREATE INDEX idx_mov_inv_fecha ON mov_inventario(fecha DESC);

-- facturas SRI
CREATE TABLE facturas (
  id TEXT PRIMARY KEY,
  cliente_id TEXT REFERENCES clientes(id),
  oc_id TEXT,
  fecha_emision DATE NOT NULL,
  establecimiento TEXT DEFAULT '001',
  punto_emision TEXT DEFAULT '001',
  secuencial TEXT NOT NULL,
  clave_acceso TEXT,
  autorizacion_sri TEXT,
  fecha_autorizacion TIMESTAMPTZ,
  estado_sri TEXT DEFAULT 'pendiente',
  subtotal_12 NUMERIC(12,2),
  subtotal_0 NUMERIC(12,2),
  iva NUMERIC(12,2),
  total NUMERIC(12,2),
  forma_pago TEXT,
  forma_pago_codigo TEXT,
  fecha_vencimiento DATE,
  pagada BOOLEAN DEFAULT FALSE,
  items JSONB,
  sri_mensajes JSONB,
  xml_firmado TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_facturas_cliente ON facturas(cliente_id);
CREATE INDEX idx_facturas_estado ON facturas(estado_sri);
CREATE INDEX idx_facturas_clave ON facturas(clave_acceso);

-- RLS: habilitar y crear policy bloqueando anon (service_role bypassea)
ALTER TABLE empleados ENABLE ROW LEVEL SECURITY;
ALTER TABLE productos ENABLE ROW LEVEL SECURITY;
ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE lotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE mov_inventario ENABLE ROW LEVEL SECURITY;
ALTER TABLE facturas ENABLE ROW LEVEL SECURITY;
```

## Plan de migración (sin downtime)

### Fase 1 — Crear tablas (sin tocar storage)
1. Correr SQL anterior en Supabase Studio
2. Verificar que `config` y `reportes` siguen funcionando

### Fase 2 — Doble escritura (transición)
1. Cambiar `save_X()` en `storage.py` para escribir a AMBOS lados: key-value (legacy) Y tabla nueva
2. Las lecturas siguen viniendo de key-value
3. Test exhaustivo: cada save → verificar que la tabla nueva tiene el mismo dato

### Fase 3 — Migrar datos históricos
Script `scripts/migrate_to_normalized.py`:
```python
# Para cada entidad legacy en config, escribir a la tabla nueva
for k, v in load_clientes().items() if dict else load_clientes():
    db.table("clientes").upsert({...mapeo...}).execute()
```

### Fase 4 — Switch de lecturas
1. Cambiar `load_X()` para leer de tabla nueva
2. Mantener doble escritura por seguridad
3. Test integral en staging

### Fase 5 — Limpieza
Después de N días sin issues:
1. Quitar doble escritura → solo escribir a tabla nueva
2. Eliminar keys legacy del `config`

## Beneficios concretos

- **`SELECT * FROM clientes WHERE ruc = ?`** en lugar de iterar JSON entero
- **`SELECT * FROM lotes WHERE producto_id=? AND NOT despachado ORDER BY fecha_elaboracion ASC LIMIT 10`** — FIFO real con índice
- **Reportes BI** desde Supabase Studio sin código Python
- **Concurrencia segura** — updates atómicos a nivel de fila

## Riesgos

- **Migración complicada con datos vivos** — necesita coordinación, ventana de mantenimiento
- **Tests insuficientes hoy** — solo 20 tests, deberían cubrir más antes de migrar
- **Backup obligatorio antes** — `/api/admin/backup` antes de cada fase

## Estimación

- Fase 1: 30 min (SQL en Supabase)
- Fase 2: 3h (doble escritura + tests parity)
- Fase 3: 2h (script de migración + ejecución + verificación)
- Fase 4: 1h (switch reads + monitoring)
- Fase 5: 30 min (cleanup tras 1-2 semanas)

Total: ~7h de dev + 1-2 semanas de cohabitación de los dos esquemas.

## ¿Cuándo hacerlo?

**No urgente.** El sistema actual funciona bien para el volumen actual (~10 usuarios, ~100 facturas/mes, ~1000 lotes). Hacer cuando:
- Necesites un reporte SQL que el key-value haga lento
- Empieces a tener race conditions reales en producción
- Quieras BI / dashboards desde Supabase Studio

Hasta entonces, el costo de la migración no se justifica.
