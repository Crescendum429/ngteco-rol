"""Reset + inventario inicial 2026-05-14 según hoja física.

Pasos:
 1. Limpia registros diarios, lotes, movimientos, piezas, molido, aux_consumo.
 2. Renombra j_generic -> "Jeringa sin Logo".
 3. Crea j_farbiopharma (jeringa para cli-farbiopharma).
 4. Crea aux-fundas-vlife y aux-fundas-jfarbio (subitems nuevos).
 5. Crea lotes (cantidad declarada por producto) con fecha hoy.
 6. Crea movimiento ajuste MP por material (kg + cantidad_fundas).
 7. Actualiza stock auxiliares directamente + movimiento auditable.
 8. Genera alertas persistentes por inconsistencias (productos/aux no
    verificados en esta hoja).

Resiliente: cada operacion en try/except. Errores se loggean, no abortan.
"""
from __future__ import annotations
import logging
from datetime import date
from decimal import Decimal

from storage import (
    list_registros_diarios, delete_registro_diario,
    load_alertas_persistentes, save_alertas_persistentes,
    load_clientes,
    load_inv_aux_consumo, save_inv_aux_consumo,
    load_inv_auxiliar, save_inv_auxiliar,
    load_inv_lotes, save_inv_lotes,
    load_inv_molido, save_inv_molido,
    load_inv_piezas, save_inv_piezas,
    load_movimientos_inventario, save_movimientos_inventario,
    load_productos, save_productos,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reset")

FECHA_INVENTARIO = date.today().isoformat()
KG_POR_FUNDA = 25  # Confirmado por contador


PRODUCTOS_STOCK = {
    # prod_id -> cajas declaradas en la hoja fisica
    "v_solplast":   0,
    "v_pequena":    9,
    "v_life":       42,
    "v_lamosan":    11,
    "v_farma1":     134,   # "V. Farmayala 134 cajas"
    "v_farma2":     7,     # "V. Farmayala 2 - 7 cajas"
    "cuchara_5ml":  6,
    "cuchara_30cc": 3,
    "j_life":       159,
    "j_generic":    4,     # "Jeringa sin logo"
    "j_farbiopharma": 3,   # NUEVO
}

# Stock MP en kg = fundas * 25
MP_INVENTARIO = {
    "pp_omo":         {"fundas": 168, "kg": 168 * KG_POR_FUNDA},
    "pe_alta":        {"fundas": 38,  "kg": 38 * KG_POR_FUNDA},
    "pe_baja":        {"fundas": 29,  "kg": 29 * KG_POR_FUNDA},
    "pp_clarificado": {"fundas": 134, "kg": 134 * KG_POR_FUNDA},
}

# Auxiliares declarados en la hoja
AUX_INVENTARIO = {
    "aux-guantes-nitrilo":  {"stock": 41,   "unidad": "cajas"},
    "aux-cintas":           {"stock": 216,  "unidad": "unidades"},
    "aux-rollo-empacadora": {"stock": 81,   "unidad": "unidades"},
    "aux-fundas-cucharas":  {"stock": 1500, "unidad": "unidades"},
    "aux-fundas-jeringas":  {"stock": 4565, "unidad": "unidades"},
}

# Auxiliares NUEVOS (subitems mencionados en hoja)
AUX_NUEVOS = [
    {"id": "aux-fundas-vlife",   "nombre": "Fundas Vaso Life",            "categoria": "fundas",
     "unidad": "unidades", "stock": 400,  "minimo": 100, "costo_unit": 0},
    {"id": "aux-fundas-jfarbio", "nombre": "Fundas Jeringa Farbiopharma", "categoria": "fundas",
     "unidad": "unidades", "stock": 2100, "minimo": 500, "costo_unit": 0},
]


def paso1_limpiar_historico():
    log.info("== Paso 1: limpiar historico ==")
    # Registros diarios
    try:
        for mes in ("2026-04", "2026-05", "2026-06"):
            regs = list_registros_diarios(mes) or {}
            for fecha in list(regs.keys()):
                try:
                    delete_registro_diario(fecha)
                except Exception:
                    log.exception(f"  registro {fecha}")
        log.info("  registros diarios eliminados")
    except Exception:
        log.exception("paso1 registros")
    # Lotes
    try:
        save_inv_lotes([])
        log.info("  lotes reseteados")
    except Exception:
        log.exception("paso1 lotes")
    # Movimientos
    try:
        save_movimientos_inventario([])
        log.info("  movimientos reseteados")
    except Exception:
        log.exception("paso1 movimientos")
    # Piezas (cantidad 0 pero mantener bins de catalogo)
    try:
        piezas = load_inv_piezas() or []
        for p in piezas:
            if isinstance(p, dict):
                p["cantidad"] = 0
        save_inv_piezas(piezas)
        log.info(f"  piezas: {len(piezas)} bins en 0")
    except Exception:
        log.exception("paso1 piezas")
    # Molido
    try:
        save_inv_molido({})
        log.info("  molido reseteado a 0")
    except Exception:
        log.exception("paso1 molido")
    # Aux consumo
    try:
        save_inv_aux_consumo([])
        log.info("  aux consumo historico eliminado")
    except Exception:
        log.exception("paso1 aux_consumo")


def paso2_renombrar_productos():
    log.info("== Paso 2: renombrar/crear productos ==")
    try:
        ps = load_productos() or {}
        if not isinstance(ps, dict):
            ps = {}
        cambios = 0
        # Renombrar j_generic
        if "j_generic" in ps:
            ps["j_generic"]["nombre"] = "Jeringa sin Logo"
            ps["j_generic"]["kind"] = "jeringa"
            cambios += 1
            log.info("  j_generic -> 'Jeringa sin Logo'")
        # Crear j_farbiopharma si no existe
        if "j_farbiopharma" not in ps:
            ps["j_farbiopharma"] = {
                "nombre": "Jeringa Farbiopharma",
                "kind": "jeringa",
                "unidades_caja": 1000,
                "peso_g": 0,
                "material_desc": "PP Clarif + PE Alta + PE Baja",
                "factor_complejidad": 3.0,
                "costo_unit": 0,
                "costo_caja": 0,
                "iva_pct": 0,
                "cliente_asociado": "cli-farbiopharma",
                "datos_incompletos": ["peso_g", "costo_unit", "costo_caja"],
                "empaques": {},
            }
            cambios += 1
            log.info("  j_farbiopharma CREADO (cliente cli-farbiopharma)")
        save_productos(ps)
        log.info(f"  productos: {cambios} cambios")
    except Exception:
        log.exception("paso2 productos")


def paso3_crear_lotes_inventario():
    """Para cada producto con cajas declaradas, crea un lote 'INV-INICIAL'."""
    log.info("== Paso 3: lotes inventario inicial ==")
    try:
        lotes = []
        for pid, cajas in PRODUCTOS_STOCK.items():
            if cajas <= 0:
                continue
            lote = {
                "id": f"INV-{pid.upper()[:8]}-{FECHA_INVENTARIO.replace('-', '')}",
                "producto_id": pid,
                "cliente_id": None,
                "fecha_elaboracion": FECHA_INVENTARIO,
                "fecha_caducidad": "",
                "cantidad_cajas": cajas,
                "unidades_caja": 0,
                "peso_neto": 0,
                "peso_total": 0,
                "responsable": "Inventario inicial",
                "despachado": False,
                "despachado_en": "",
                "es_inventario_inicial": True,
            }
            lotes.append(lote)
        save_inv_lotes(lotes)
        log.info(f"  {len(lotes)} lotes creados")
    except Exception:
        log.exception("paso3 lotes")


def paso4_movs_mp():
    """Crea un movimiento 'entrada' INV-INICIAL para cada material."""
    log.info("== Paso 4: movimientos MP (entradas inventario inicial) ==")
    try:
        movs = load_movimientos_inventario() or []
        nid = max([int(m.get("id", 0)) for m in movs if isinstance(m, dict)], default=0)
        for mat_id, data in MP_INVENTARIO.items():
            nid += 1
            movs.insert(0, {
                "id": nid,
                "fecha": FECHA_INVENTARIO,
                "tipo": "entrada",
                "clase": "mp",
                "item_id": mat_id,
                "cantidad": float(data["kg"]),
                "cantidad_fundas": int(data["fundas"]),
                "unidad": "kg",
                "ref": "INV-INICIAL",
                "nota": f"Inventario inicial 2026-05-14: {data['fundas']} fundas x {KG_POR_FUNDA}kg = {data['kg']}kg",
            })
            log.info(f"  {mat_id}: +{data['kg']}kg ({data['fundas']} fundas)")
        save_movimientos_inventario(movs)
    except Exception:
        log.exception("paso4 mp")


def paso5_auxiliares():
    log.info("== Paso 5: auxiliares ==")
    try:
        aux = load_inv_auxiliar() or []
        if not isinstance(aux, list):
            aux = []
        by_id = {a.get("id"): a for a in aux if isinstance(a, dict)}
        # Actualizar existentes
        for aux_id, target in AUX_INVENTARIO.items():
            if aux_id in by_id:
                by_id[aux_id]["stock"] = target["stock"]
                by_id[aux_id]["unidad"] = target["unidad"]
                # Limpiar flag de "no verificado" si lo tuviera
                di = by_id[aux_id].get("datos_incompletos") or []
                by_id[aux_id]["datos_incompletos"] = [x for x in di if x not in ("stock_inicial",)]
                log.info(f"  {aux_id}: {target['stock']} {target['unidad']}")
            else:
                log.warning(f"  {aux_id} no existe en BD, se omite")
        # Agregar nuevos
        for nuevo in AUX_NUEVOS:
            if nuevo["id"] not in by_id:
                aux.append(nuevo)
                log.info(f"  {nuevo['id']} CREADO: {nuevo['stock']} {nuevo['unidad']}")
        save_inv_auxiliar(aux)
        # Movimientos auditables
        movs = load_movimientos_inventario() or []
        nid = max([int(m.get("id", 0)) for m in movs if isinstance(m, dict)], default=0)
        for aux_id, target in AUX_INVENTARIO.items():
            nid += 1
            movs.insert(0, {
                "id": nid,
                "fecha": FECHA_INVENTARIO,
                "tipo": "entrada", "clase": "aux", "item_id": aux_id,
                "cantidad": float(target["stock"]), "unidad": target["unidad"],
                "ref": "INV-INICIAL",
                "nota": f"Inventario inicial 2026-05-14",
            })
        for nuevo in AUX_NUEVOS:
            nid += 1
            movs.insert(0, {
                "id": nid,
                "fecha": FECHA_INVENTARIO,
                "tipo": "entrada", "clase": "aux", "item_id": nuevo["id"],
                "cantidad": float(nuevo["stock"]), "unidad": nuevo["unidad"],
                "ref": "INV-INICIAL",
                "nota": "Inventario inicial 2026-05-14 (item nuevo)",
            })
        save_movimientos_inventario(movs)
    except Exception:
        log.exception("paso5 aux")


def paso6_alertas_inconsistencias():
    """Genera alertas para productos/aux que estan en BD pero no en la hoja."""
    log.info("== Paso 6: alertas de inconsistencias ==")
    try:
        alertas = load_alertas_persistentes() or []
        ids_existentes = {a.get("id") for a in alertas if isinstance(a, dict)}

        ps = load_productos() or {}
        prod_mencionados = set(PRODUCTOS_STOCK.keys())
        for pid, p in ps.items():
            if pid not in prod_mencionados and not p.get("desactivado"):
                aid = f"inv-no-verificado-prod-{pid}"
                if aid in ids_existentes:
                    continue
                alertas.append({
                    "id": aid, "tipo": "inv_no_verificado", "severidad": "info",
                    "titulo": f"{p.get('nombre', pid)} sin verificar en inventario inicial",
                    "descripcion": f"Producto existe en catalogo pero no aparece en hoja fisica del {FECHA_INVENTARIO}. Cuando se verifique fisicamente, registrar stock con +Movimiento o lote nuevo.",
                    "destino": {"page": "catalogo", "sub": "productos", "id": pid},
                    "ref": pid,
                    "fecha_creacion": FECHA_INVENTARIO,
                })

        aux_list = load_inv_auxiliar() or []
        aux_mencionados = set(AUX_INVENTARIO.keys()) | {n["id"] for n in AUX_NUEVOS}
        for a in aux_list:
            if not isinstance(a, dict):
                continue
            aid_aux = a.get("id")
            if aid_aux not in aux_mencionados and not a.get("desactivado"):
                aid = f"inv-no-verificado-aux-{aid_aux}"
                if aid in ids_existentes:
                    continue
                alertas.append({
                    "id": aid, "tipo": "inv_no_verificado", "severidad": "info",
                    "titulo": f"Auxiliar {a.get('nombre', aid_aux)} sin verificar en inventario inicial",
                    "descripcion": f"Aux existe pero no aparece en hoja fisica del {FECHA_INVENTARIO}.",
                    "destino": {"page": "inventario", "sub": "aux"},
                    "ref": aid_aux,
                    "fecha_creacion": FECHA_INVENTARIO,
                })

        save_alertas_persistentes(alertas)
        nuevas = len([a for a in alertas if a.get("id", "").startswith("inv-no-verificado-")])
        log.info(f"  alertas persistentes totales: {len(alertas)} ({nuevas} de inv no verificado)")
    except Exception:
        log.exception("paso6 alertas")


def main():
    log.info("== RESET + INVENTARIO INICIAL ==")
    paso1_limpiar_historico()
    paso2_renombrar_productos()
    paso3_crear_lotes_inventario()
    paso4_movs_mp()
    paso5_auxiliares()
    paso6_alertas_inconsistencias()
    log.info("== LISTO ==")


if __name__ == "__main__":
    main()
