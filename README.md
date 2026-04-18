# SOLPLAST — Sistema de Gestion ERP

Aplicacion web para la gestion operativa de SOLPLAST (Soluciones Plasticas del Ecuador). Centraliza nomina, costos de produccion, registro diario del operario y metricas historicas en una sola interfaz.

## Problema

La empresa manejaba manualmente cuatro procesos desconectados:

- **Asistencia**: los relojes NGTeco exportan XLS con errores frecuentes (entrada no registrada, missing OUT, fechas cruzadas). Corregirlos en Excel tomaba tiempo y generaba errores.
- **Nomina**: el calculo de quincenas, horas extras, IESS, fondos de reserva y prestamos se hacia en Excel sin formula consistente.
- **Costos**: el costo real por unidad de cada producto (vaso, jeringa, gotero, cuchara) no estaba calculado, dificultando decisiones de precio.
- **Registro diario**: no habia trazabilidad del material usado, desechos ni produccion por dia.

## Modulos

### Roles y Nomina
- Sube el XLS del reloj NGTeco y detecta anomalias automaticamente (entrada faltante, missing OUT, fechas cruzadas).
- Tabla editable por empleado para corregir horas antes de calcular.
- Calculo completo de nomina segun ley ecuatoriana:
  - Horas suplementarias al 50% (dias laborables, max 4h/dia, Art. 55)
  - Horas extraordinarias al 100% (fines de semana o exceso de 12h, Art. 55)
  - Quincenas (primera y segunda)
  - Aporte IESS empleado (9.45%)
  - Prestamo IESS (monto fijo configurable por empleado)
  - Fondos de reserva (1/12 del ingreso, para empleados con mas de 1 año)
  - Transporte/alimentacion por dias trabajados
- Arrastre de horas compensatorias entre meses.
- Exporta Excel de nomina con formato formal (ingresos, egresos, valor a recibir, detalle de transferencias) y PDF.

### Gastos y Costos de Produccion
- Configuracion de materias primas (PP Homopolimero, PP Clarificado, PE Alta/Baja densidad, PVC) con precio por kg editable.
- Configuracion de productos con composicion exacta por componente (peso en gramos, material o mezcla con proporciones).
- Configuracion de empaques (caja, funda individual, funda exterior, cinta, tinta de tampo).
- Calculo de costo unitario real por producto: material + empaque + nomina + gastos indirectos.
- Los gastos indirectos y nomina se distribuyen por factor de complejidad del producto.
- Merma configurable por material (default 3%) o calculada automaticamente desde registros diarios.
- Gastos fijos mensuales editables (electricidad, agua, tinta, solvente, transporte, mantenimiento).

### Registro Diario (Operario)
- Interfaz simplificada para que el operario ingrese al cierre de jornada:
  - Material usado por tipo (kg)
  - Desechos por producto y subproducto
  - Material molido recuperado
  - Cajas producidas por producto
- Con estos datos el sistema calcula la merma real por material mes a mes.

### Metricas
- Indicadores historicos de nomina: total pagado, promedio mensual, delta mes a mes.
- Grafico de evolucion de nomina (area + linea + puntos).
- Detalle de pago por empleado con grafico de barras horizontales (escala secuencial).
- Horas extras por mes con barras agrupadas (50% vs 100%).
- Snapshot de costos por periodo para comparar evolucion del costo unitario.

### Empleados
- Alta, edicion y baja de empleados.
- Campos: nombre, salario, horas base, transporte/dia, region, cargo, prestamo IESS, fondos de reserva.
- Matching automatico por nombre al subir el XLS (sin necesidad de ID del reloj).
- Alertas cuando aparece un nombre nuevo en el reporte o un empleado de la base no aparece.
- Exportacion e importacion JSON para respaldo.

## Usuarios y roles

- **Admin**: acceso completo a todos los modulos.
- **Operario**: acceso exclusivo al Registro Diario.

Las contrasenas se configuran via variables de entorno (`APP_PASSWORD`, `APP_PASSWORD_OP`).

## Stack

- Python 3.11
- Streamlit 1.56 — interfaz web
- Altair — graficos
- xlrd / openpyxl — lectura y escritura de Excel
- fpdf2 — generacion de PDF
- Supabase — base de datos (tabla `config` tipo key-value + tabla `reportes`)
- Docker — empaquetado
- Deploy: Streamlit Cloud con auto-deploy desde GitHub

## Ejecucion local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Variables de entorno necesarias para conectar Supabase:

```
SUPABASE_URL=...
SUPABASE_KEY=...
APP_PASSWORD=...          # contrasena admin (opcional)
APP_PASSWORD_OP=...       # contrasena operario (opcional)
```

Sin variables de entorno el sistema funciona en modo local usando archivos JSON.

## Docker

```bash
docker build -t solplast-erp .
docker run -p 8501:8501 \
  -e SUPABASE_URL=... \
  -e SUPABASE_KEY=... \
  solplast-erp
```
