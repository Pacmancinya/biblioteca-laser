# -*- coding: utf-8 -*-
"""Busca e instala una versión nueva de la app (sin tocar tus datos)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        import app
    except Exception as e:
        print("  No pude leer la app:", e)
        return 1

    print()
    r = app.revisar_actualizacion()
    if not r.get("ok"):
        print("  " + r.get("error", "no se pudo revisar"))
        print()
        print("  Si no tienes internet, pidele a Ruperto el ZIP nuevo")
        print("  y descomprimelo encima de esta carpeta.")
        return 1

    print("  Tu version       :", r["actual"])
    print("  Version en linea :", r["disponible"])
    print()

    if not r.get("hay_nueva"):
        print("  Estas al dia. No hay nada que actualizar.")
        return 0

    print("  HAY UNA VERSION NUEVA")
    if r.get("novedades"):
        print("  Novedades:", r["novedades"])
    print()
    resp = input("  Instalar ahora? (s/n): ").strip().lower()
    if resp not in ("s", "si", "sí", "y"):
        print("  Cancelado.")
        return 0

    print("  Descargando e instalando...")
    res = app.aplicar_actualizacion(r["zip"])
    print()
    if res.get("ok"):
        print("  LISTO. Se actualizaron", len(res["archivos"]), "archivos.")
        print("  Tus favoritos, precios, clientes y ventas NO se tocaron.")
        print()
        print("  Abre de nuevo la biblioteca para usar la version nueva.")
        return 0
    print("  ERROR:", res.get("error", "no se pudo actualizar"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
