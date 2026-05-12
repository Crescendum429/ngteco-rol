# Auditoria financiera v4.2.3 → v4.2.8

Resumen de los 8 bugs criticos detectados y resueltos en este ciclo.

## Bugs corregidos

### 1. Banco compensatorio podia ir negativo silenciosamente
- **Antes**: marcar `cubrir_banco=True` sin saldo causaba pago indebido sin alerta.
- **Ahora**: el endpoint `/api/nomina/corregir` valida saldo del banco antes de
  aplicar la cobertura. Si el banco es insuficiente, emite alerta clara en la
  respuesta (no bloquea pero documenta para revision).
- Tests: `tests/test_calcular_nomina_e2e.py::test_e2e_dia_completo_cubierto_sin_timbres`

### 2. Transporte se pagaba por dias cubiertos sin asistencia
- **Antes**: `dias` se incrementaba aun si el dia se cubrio con banco sin
  timbres reales. Resultado: pagar transporte ($1.50-$3) cada dia que el
  empleado no fue al lugar.
- **Ahora**: separados `dias` (con timbres reales — usado para transporte
  Art. 42 CT) y `dias_pagados` (incluye banco — solo para reporting).
- Tests: `test_e2e_dias_trabajados_vs_pagados_transporte`

### 3. Horas suplementarias sin tope semanal (Art. 55)
- **Antes**: 4h diarias cap respetado, pero 4×6 dias = 24h/sem se pagaban
  todas al 50%. Legalmente las suplementarias no exceden 12h/semana.
- **Ahora**: cuando una semana ISO supera 12h, el sistema PAGA todas al 50%
  (politica conservadora) pero EMITE ALERTA explicita en `alertas` para
  que el contador decida caso por caso. Configurable via env var
  `POLITICA_EXCESO_SEMANAL=alertar_pero_pagar|reclasificar_100`.
- Tests: `test_e2e_tope_semanal_12h_genera_alerta`

### 4. Decimo 13ro y 14to no se calculaban segun ley
- **Antes**: 13ro = salario base flat. 14to = SBU flat. Sin proporcionalidad
  para empleados que entraron a mitad de anio.
- **Ahora**:
  - `decimo_14to_proporcional(fecha_ingreso, periodo, sbu)` calcula
    proporcional al ciclo 1-ago a 31-jul para Sierra/Amazonia.
  - `decimo_13ro_acumulado()` calcula desde historial de 12 meses
    (1 dic anio-1 al 30 nov anio actual). Si no hay historial completo,
    cae al fallback flat con alerta.
- Tests: `test_decimo_14to_proporcional_*`

### 5. transf_fin podia quedar negativa silenciosamente
- **Antes**: si `valor_recibir - quincena + fondos < 0` el numero negativo
  pasaba sin aviso. El contador no sabia que algo estaba mal.
- **Ahora**: la funcion emite alerta clara: `transf_fin NEGATIVA (...).
  Descuentos exceden 2da quincena.`
- Tests: `test_e2e_nomina_transferencia_fin_negativa`

### 6. IESS y fondos aplicaban sobre transporte sin opcion
- **Antes**: la base imponible (`total_ingresos`) siempre incluia transporte.
  Para empleados con transporte como bonificacion no salarial, esto era
  legalmente incorrecto.
- **Ahora**: campo `transporte_gravable` por empleado. Default `True`
  (conservador, preserva comportamiento legacy). Si `False`, IESS y fondos
  excluyen transporte de la base imponible.
- Tests: `test_e2e_transporte_no_gravable_para_iess`

### 7. IVA hardcodeado al 15% en todas las facturas
- **Antes**: factura desde OC siempre aplicaba 15%. Productos de tarifa 0%
  (medicinas, exportaciones) o 5% (insumos agro) facturaban mal.
- **Ahora**:
  - Campo `iva_pct` por producto en catalogo. Valores admitidos: 0, 5, 15.
  - Generacion de factura calcula IVA por linea con su tarifa correspondiente.
  - Verificacion de reconciliacion: `sum(iva_linea) == iva_total`. Si rompe,
    aborta la creacion con error claro.
- Tests: `test_xml_reconciliacion_subtotal_lineas`

### 8. Fondos de reserva no respetaba el primer anio
- **Antes**: `tiene_fondos` era flag boolean en empleado. Si se marcaba en
  un empleado nuevo, se pagaban fondos desde el primer mes — incorrecto.
  El Art. 196 CT solo otorga fondos despues del primer anio.
- **Ahora**: si el empleado tiene `fecha_ingreso`, el sistema valida que
  hayan transcurrido >=365 dias antes de aplicar fondos. Si no hay fecha,
  asume legacy y aplica (no rompe datos historicos).
- Tests: `test_fondos_aplica_*`

## Cambios estructurales

- **Snapshot inmutable de nomina** (`/api/nomina/calcular`): el resumen
  guardado ahora incluye el detalle completo de cada empleado. Si en el
  futuro se edita el salario, la nomina del mes pasado NO cambia
  retroactivamente — porque el calculo se hace desde el snapshot. Critico
  para auditoria SRI/contable.
- **Audit log append-only** (`/api/audit`): registra `(timestamp, user, ip,
  entity, action, before, after)` de cambios sensibles. Aplicado a:
  - empleados (create, update, delete)
  - facturas (emitir al SRI)
- **No silenciar excepciones financieras**: `banco_por_empleado`,
  `build_horas_por_periodo`, `build_nomina_por_periodo` ahora hacen
  `log.exception` en lugar de `pass` ante errores de carga de reporte.

## Constantes y feriados

- `FERIADOS_ECUADOR` (en `nomina_logic.py`): lista de feriados nacionales
  2025-2026. Trabajar en feriado se trata como 100% (igual que fin de
  semana). Actualizar cada anio cuando el MDT publique el calendario.
- `SBU_2026 = 470` (default), configurable via env var `SBU_VIGENTE`.
  Backend y frontend leen el mismo valor (override inyectado en `data.jsx`).
- `IESS_EMPLEADO = 0.0945`.
- `MAX_SUPLEMENTARIAS_DIA = 4.0`, `MAX_SUPLEMENTARIAS_SEMANA = 12.0`.
- `POLITICA_EXCESO_SEMANAL = "alertar_pero_pagar"` por defecto.

## Lo que falta para 100% compliance

### Alta prioridad (legal)
1. **Vacaciones** (Art. 71 CT): 15 dias pagados/anio. Liquidaciones
   proporcionales. Aun no modelado.
2. **Anticipos parciales** registrados en el sistema (campo creado en
   `calcular_nomina(extras={"anticipo": X})` pero falta UI para
   ingresarlos por periodo).
3. **Vigencia historica del SBU**: si el usuario calcula nomina de 2024
   con SBU 2024 actual, el SBU=470 puede no ser correcto. Implementar
   `SBU_POR_ANIO = {2024: 460, 2025: 470, 2026: ?}`.

### Media prioridad
4. **Calculo estricto de 13ro** integrado al endpoint calcular (helper
   `decimo_13ro_acumulado` existe pero no se invoca desde `calcular_nomina`
   aun — pendiente cablear).
5. **Anticipos en UI**: agregar input en NomStepSueldos para anticipos.
6. **Vacaciones**: planning + endpoint para registrar dias tomados.

### Baja prioridad
7. **Decimal en boundaries criticos** (no migracion total): redondeo en
   `calcular_nomina` y `build_factura_xml`.

## Tests

- 70 tests verdes al cierre de v4.2.8.
- Suite incluye tests de caracterizacion (`test_calcular_nomina_e2e.py`)
  que congelan el comportamiento. Cualquier cambio que afecte estos
  valores debe ser deliberado.

## Decisiones documentadas

- **SBU 2026 = 470** como default conservador. El MDT no habia publicado
  oficial al momento de auditoria. Configurable via env var.
- **Transporte gravable = True** por defecto (conservador, preserva
  comportamiento previo). Cambiar a False solo si convenio colectivo lo
  excluye explicitamente.
- **Politica de exceso semanal = "alertar_pero_pagar"**: pagamos las
  horas al 50% pero alertamos. Es la decision menos invasiva. Si el
  contador prefiere "reclasificar_100", se cambia con env var.
- **Fecha de ingreso vacia = legacy permisivo**: empleados sin fecha
  conservan comportamiento previo (fondos aplica si flag esta on). Solo
  empleados con fecha real entran en la logica nueva.

Estado v4.2.8: el sistema es notablemente mas robusto contra pagos
incorrectos. Sigue habiendo trabajo (vacaciones, anticipos UI), pero los
8 bugs criticos confirmados estan resueltos o tienen alertas para
revision humana.
