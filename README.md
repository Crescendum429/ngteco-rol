# NGTeco Rol Processor

Aplicacion web para procesar reportes de asistencia generados por relojes biometricos NGTeco y convertirlos en roles de pago listos para revision.

## Problema

Los relojes NGTeco exportan reportes XLS con errores frecuentes:
- **Entrada de manana no registrada**: el reloj no capta el timbre de llegada, mostrando solo el almuerzo como un bloque corto de ~30 minutos.
- **Missing OUT**: el timbre de salida no queda registrado.
- **Fechas cruzadas**: marcaciones que se asignan al dia equivocado.

Corregir estos errores manualmente en Excel toma tiempo y es propenso a mas errores.

## Solucion

La aplicacion tiene dos modulos:

### Tab Horas
- Sube el archivo `.xls` del NGTeco.
- Detecta automaticamente las anomalias usando reglas de negocio (ventanas horarias esperadas).
- Muestra una tabla editable por empleado donde se pueden corregir las horas directamente.
- Descarga un Excel limpio con las horas corregidas y las anomalias marcadas en amarillo.

### Tab Nomina
- Ingreso de salario base y horas base por empleado (datos efimeros, no se guardan).
- Calculo automatico de horas extras segun la ley ecuatoriana:
  - **Suplementarias (50%)**: horas extra en dias laborables, max 4h/dia (Art. 55).
  - **Extraordinarias (100%)**: fines de semana o exceso de 12h diarias (Art. 55).
- Toggles para incluir Decimo Tercer Sueldo (Art. 111-112) y Decimo Cuarto Sueldo (Art. 113, SBU $482).
- Campo de bono/ajuste con nota por empleado.
- Descarga un Excel de nomina con resumen general y detalle individual.

## Uso

Abrir la URL de la aplicacion, subir el archivo XLS, corregir anomalias si las hay, ingresar salarios, descargar los reportes.

### Ejecucion local

```bash
pip install -r requirements.txt
streamlit run app.py
```

### Docker

```bash
docker build -t ngteco-rol .
docker run -p 8501:8501 ngteco-rol
```

## Stack

- Python 3.11
- Streamlit (interfaz web)
- xlrd (lectura de XLS)
- openpyxl (generacion de XLSX)
- Deploy: Render.com con auto-deploy desde GitHub
