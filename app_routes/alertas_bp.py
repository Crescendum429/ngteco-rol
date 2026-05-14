"""Blueprint de alertas inteligentes.

Genera dinamicamente alertas a partir del estado del sistema:
- Productos con `datos_incompletos`
- Clientes con `datos_incompletos`
- Piezas con `datos_incompletos`
- Alertas persistentes (creadas a mano, ej. OC sugeridas del chat)
- Stock bajo minimo en MP / PT / Auxiliar

Cada alerta tiene `id` estable para que el usuario pueda descartarla.
Las descartadas no vuelven a aparecer salvo que se reactiven.

Resiliente: si alguna fuente falla, se ignora silenciosamente (no rompe el resto).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app_routes._auth import require_auth
from storage import (
    load_alertas_descartadas,
    load_alertas_persistentes,
    load_clientes,
    load_inv_auxiliar,
    load_inv_piezas,
    load_inventario_mp,
    load_inventario_pt,
    load_productos,
    save_alertas_descartadas,
    save_alertas_persistentes,
)

log = logging.getLogger("alertas")

alertas_bp = Blueprint("alertas", __name__)


def _datos_incompletos_de(item):
    """Retorna lista de campos faltantes o [] si no aplica."""
    if not isinstance(item, dict):
        return []
    di = item.get("datos_incompletos")
    if isinstance(di, list):
        return di
    if di is True:
        return ["(sin detalle)"]
    return []


def _generar_alertas():
    alertas = []
    # Acumuladores para agrupar items con datos_incompletos por categoria
    inc_productos = []  # [{id, nombre, faltantes}]
    inc_clientes = []
    inc_piezas = []
    inc_aux = []

    # 1) Productos con datos incompletos -> recolectar (luego agrupar)
    try:
        productos = load_productos() or {}
        if isinstance(productos, dict):
            for pid, p in productos.items():
                faltantes = _datos_incompletos_de(p)
                if faltantes:
                    inc_productos.append({"id": pid, "nombre": p.get("nombre", pid), "faltantes": faltantes})
    except Exception:
        log.exception("alertas: productos")

    # 2) Clientes con datos incompletos
    try:
        clientes = load_clientes() or []
        for c in clientes:
            faltantes = _datos_incompletos_de(c)
            if faltantes:
                inc_clientes.append({"id": c.get("id"), "nombre": c.get("nombre_comercial", "?"), "faltantes": faltantes})
    except Exception:
        log.exception("alertas: clientes")

    # 3) Piezas con datos incompletos
    try:
        piezas = load_inv_piezas() or []
        for p in piezas:
            faltantes = _datos_incompletos_de(p)
            if faltantes:
                inc_piezas.append({"id": p.get("id"), "nombre": p.get("pieza", "?"), "faltantes": faltantes})
    except Exception:
        log.exception("alertas: piezas")

    # 3b) Auxiliares con datos incompletos (costo_unit, stock_inicial)
    try:
        aux = load_inv_auxiliar() or []
        if isinstance(aux, list):
            for a in aux:
                faltantes = _datos_incompletos_de(a)
                if faltantes:
                    inc_aux.append({"id": a.get("id"), "nombre": a.get("nombre", "?"), "faltantes": faltantes})
    except Exception:
        log.exception("alertas: aux incompletos")

    # Emitir UNA alerta agrupada por categoria con resumen
    def _emitir_grupo(items, tipo_key, label_singular, label_plural, destino):
        if not items:
            return
        n = len(items)
        nombres_preview = ", ".join(i["nombre"] for i in items[:3])
        if n > 3:
            nombres_preview += f", +{n-3} más"
        alertas.append({
            "id": f"grupo-incomplete-{tipo_key}",
            "tipo": "datos_incompletos",
            "severidad": "info",
            "titulo": f"{n} {label_singular if n == 1 else label_plural} sin verificar",
            "descripcion": nombres_preview,
            "destino": destino,
            "ref": tipo_key,
            "items": items,  # incluido para que la UI pueda expandir
        })

    _emitir_grupo(inc_productos, "productos", "producto", "productos",
                  {"page": "catalogo", "sub": "productos"})
    _emitir_grupo(inc_clientes, "clientes", "cliente", "clientes",
                  {"page": "clientes"})
    _emitir_grupo(inc_piezas, "piezas", "pieza", "piezas",
                  {"page": "inventario", "sub": "piezas"})
    _emitir_grupo(inc_aux, "auxiliares", "auxiliar", "auxiliares",
                  {"page": "inventario", "sub": "aux"})

    # 4) Stock bajo MP / PT / Aux
    try:
        mp = load_inventario_mp() or []
        if isinstance(mp, list):
            for m in mp:
                stock = float(m.get("stock_kg") or 0)
                minimo = float(m.get("minimo_kg") or 0)
                if minimo > 0 and stock <= minimo:
                    alertas.append({
                        "id": f"stock-mp-{m.get('id')}",
                        "tipo": "stock_bajo",
                        "severidad": "warn",
                        "titulo": f"Materia prima baja: {m.get('id')}",
                        "descripcion": f"Stock {stock:.1f} kg ≤ minimo {minimo:.0f} kg",
                        "destino": {"page": "inventario", "sub": "mp"},
                        "ref": m.get("id"),
                    })
    except Exception:
        log.exception("alertas: stock MP")

    try:
        pt = load_inventario_pt() or []
        if isinstance(pt, list):
            for p in pt:
                disp = int(p.get("stock_cajas") or 0) - int(p.get("reservado") or 0)
                minimo = int(p.get("minimo_cajas") or 0)
                if minimo > 0 and disp <= minimo:
                    alertas.append({
                        "id": f"stock-pt-{p.get('prod_id')}",
                        "tipo": "stock_bajo",
                        "severidad": "warn",
                        "titulo": f"Producto terminado bajo: {p.get('prod_id')}",
                        "descripcion": f"Disponible {disp} cajas ≤ minimo {minimo}",
                        "destino": {"page": "inventario", "sub": "pt"},
                        "ref": p.get("prod_id"),
                    })
    except Exception:
        log.exception("alertas: stock PT")

    try:
        aux = load_inv_auxiliar() or []
        if isinstance(aux, list):
            for a in aux:
                stock = float(a.get("stock") or 0)
                minimo = float(a.get("minimo") or 0)
                if minimo > 0 and stock <= minimo and not a.get("desactivado"):
                    alertas.append({
                        "id": f"stock-aux-{a.get('id')}",
                        "tipo": "stock_bajo",
                        "severidad": "warn",
                        "titulo": f"Auxiliar bajo: {a.get('nombre')}",
                        "descripcion": f"Stock {stock} {a.get('unidad', '')} ≤ minimo {minimo}",
                        "destino": {"page": "inventario", "sub": "aux"},
                        "ref": a.get("id"),
                    })
    except Exception:
        log.exception("alertas: stock aux")

    # 5) Alertas persistentes (ej. OC sugeridas, recordatorios manuales)
    try:
        persistentes = load_alertas_persistentes() or []
        for p in persistentes:
            if not isinstance(p, dict):
                continue
            alertas.append({
                "id": p.get("id"),
                "tipo": p.get("tipo", "manual"),
                "severidad": p.get("severidad", "info"),
                "titulo": p.get("titulo", ""),
                "descripcion": p.get("descripcion", ""),
                "destino": p.get("destino"),
                "ref": p.get("ref"),
                "fecha": p.get("fecha_creacion"),
            })
    except Exception:
        log.exception("alertas: persistentes")

    return alertas


@alertas_bp.route("/api/alertas", methods=["GET"])
@require_auth
def get_alertas():
    """Lista de alertas activas (no descartadas)."""
    try:
        descartadas = set(load_alertas_descartadas() or [])
        todas = _generar_alertas()
        activas = [a for a in todas if a.get("id") not in descartadas]
        return jsonify(activas)
    except Exception:
        log.exception("get_alertas fallo")
        return jsonify([])


@alertas_bp.route("/api/alertas/<alert_id>/descartar", methods=["POST"])
@require_auth
def descartar(alert_id):
    descartadas = load_alertas_descartadas() or []
    if alert_id not in descartadas:
        descartadas.append(alert_id)
        save_alertas_descartadas(descartadas)
    log.info(f"alerta descartada: {alert_id}")
    return jsonify({"ok": True})


@alertas_bp.route("/api/alertas/<alert_id>/restaurar", methods=["POST"])
@require_auth
def restaurar(alert_id):
    descartadas = load_alertas_descartadas() or []
    descartadas = [d for d in descartadas if d != alert_id]
    save_alertas_descartadas(descartadas)
    return jsonify({"ok": True})


@alertas_bp.route("/api/alertas/persistente", methods=["POST"])
@require_auth
def crear_persistente():
    """Crea una alerta persistente manual."""
    data = request.get_json(force=True) or {}
    alertas = load_alertas_persistentes() or []
    nid = data.get("id") or f"manual-{(max([0] + [int(a.get('id','0').split('-')[-1] or 0) for a in alertas if isinstance(a, dict) and a.get('id','').startswith('manual-')]) + 1)}"
    nueva = {
        "id": nid,
        "tipo": data.get("tipo", "manual"),
        "severidad": data.get("severidad", "info"),
        "titulo": data.get("titulo", ""),
        "descripcion": data.get("descripcion", ""),
        "destino": data.get("destino"),
        "ref": data.get("ref"),
        "fecha_creacion": data.get("fecha_creacion") or "",
    }
    alertas.append(nueva)
    save_alertas_persistentes(alertas)
    return jsonify({"ok": True, "id": nid})
