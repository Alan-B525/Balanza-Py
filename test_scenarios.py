"""
Script de Pruebas - Escenarios Reales de la Balanza

Ejecutar con: python test_scenarios.py

Este script permite probar diferentes escenarios que pueden ocurrir
en una aplicación real de pesaje industrial.
"""

import sys
import os
import time
import threading

# Agregar path del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import NODOS_CONFIG
from modules.factory import criar_sistema_pesaje, check_mscl_installation

# Verificar MSCL
print("=" * 60)
print("VERIFICANDO INSTALACIÓN DE MSCL")
print("=" * 60)
mscl_status = check_mscl_installation()
print(f"MSCL Instalado: {mscl_status['installed']}")
if mscl_status['installed']:
    print(f"Versión: {mscl_status.get('version', 'N/A')}")
print()


def test_conexion_basica():
    """Escenario 1: Conexión básica y lectura de datos."""
    print("\n" + "=" * 60)
    print("ESCENARIO 1: Conexión Básica y Lectura de Datos")
    print("=" * 60)
    
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    
    # Conectar
    print("\n[TEST] Intentando conexión...")
    if sistema.conectar("192.168.0.100:5000"):
        print("[TEST] ✓ Conexión exitosa")
        
        # Leer datos 5 veces
        print("\n[TEST] Leyendo datos (5 muestras)...")
        for i in range(5):
            datos = sistema.obtener_datos()
            print(f"\n  Muestra {i+1}:")
            for d in datos:
                print(f"    Nodo {d['node_id']}: {d['value']:.4f} (RSSI: {d['rssi']} dBm)")
            time.sleep(0.5)
        
        sistema.desconectar()
        print("\n[TEST] ✓ Desconectado correctamente")
    else:
        print("[TEST] ✗ Falló la conexión (esto puede pasar, hay 5% de probabilidad simulada)")
    
    return True


def test_tara():
    """Escenario 2: Aplicar y resetear tara."""
    print("\n" + "=" * 60)
    print("ESCENARIO 2: Función de Tara")
    print("=" * 60)
    
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    sistema.conectar("192.168.0.100:5000")
    
    # Leer valor inicial
    print("\n[TEST] Valores ANTES de tara:")
    datos = sistema.obtener_datos()
    for d in datos:
        print(f"    Nodo {d['node_id']}: {d['value']:.4f}")
    
    # Aplicar tara global
    print("\n[TEST] Aplicando TARA global...")
    sistema.tarar()
    
    # Leer después de tara (los valores deberían ser cercanos a 0)
    print("\n[TEST] Valores DESPUÉS de tara (deberían ser ~0):")
    time.sleep(0.3)
    datos = sistema.obtener_datos()
    for d in datos:
        # El valor ahora debería ser relativo a la tara
        tared_value = d['value'] - sistema._tares.get(d['node_id'], 0)
        print(f"    Nodo {d['node_id']}: {tared_value:.4f} (raw: {d['value']:.4f})")
    
    # Reset tara
    print("\n[TEST] Reseteando tara...")
    sistema.reset_tarar()
    
    sistema.desconectar()
    print("\n[TEST] ✓ Test de tara completado")
    return True


def test_descubrimiento_nodos():
    """Escenario 3: Descubrir nodos en la red."""
    print("\n" + "=" * 60)
    print("ESCENARIO 3: Descubrimiento de Nodos")
    print("=" * 60)
    
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    sistema.conectar("192.168.0.100:5000")
    
    print("\n[TEST] Buscando nodos en la red...")
    nodos = sistema.descubrir_nodos(timeout_ms=3000)
    
    print(f"\n[TEST] Encontrados {len(nodos)} nodo(s):")
    for nodo in nodos:
        print(f"    ID: {nodo['id']}")
        print(f"        Modelo: {nodo['model']}")
        print(f"        RSSI: {nodo['rssi']} dBm")
        print(f"        Estado: {nodo['status']}")
        print()
    
    sistema.desconectar()
    print("[TEST] ✓ Test de descubrimiento completado")
    return True


def test_desconexion_nodo():
    """Escenario 4: Simular desconexión de un nodo (sensor falla)."""
    print("\n" + "=" * 60)
    print("ESCENARIO 4: Desconexión de un Nodo")
    print("=" * 60)
    
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    sistema.conectar("192.168.0.100:5000")
    
    # Obtener un node_id para prueba
    node_ids = list(sistema._mock_nodes.keys())
    test_node_id = node_ids[0] if node_ids else None
    
    if test_node_id is None:
        print("[TEST] ✗ No hay nodos configurados")
        return False
    
    # Leer con todos los nodos activos
    print(f"\n[TEST] Leyendo con todos los nodos activos:")
    datos = sistema.obtener_datos()
    print(f"    Nodos respondiendo: {len(datos)}")
    
    # Simular desconexión de un nodo
    print(f"\n[TEST] Simulando desconexión del nodo {test_node_id}...")
    sistema.simular_desconexao_no(test_node_id)
    
    # Leer de nuevo - debería faltar un nodo
    print(f"\n[TEST] Leyendo después de desconexión:")
    time.sleep(0.3)
    datos = sistema.obtener_datos()
    print(f"    Nodos respondiendo: {len(datos)}")
    for d in datos:
        print(f"    Nodo {d['node_id']}: {d['value']:.4f}")
    
    # Reconectar nodo
    print(f"\n[TEST] Reconectando nodo {test_node_id}...")
    sistema.simular_reconexao_no(test_node_id)
    
    # Verificar reconexión
    time.sleep(0.3)
    datos = sistema.obtener_datos()
    print(f"    Nodos respondiendo: {len(datos)}")
    
    sistema.desconectar()
    print("\n[TEST] ✓ Test de desconexión completado")
    return True


def test_aplicar_carga():
    """Escenario 5: Simular aplicación de peso (carga)."""
    print("\n" + "=" * 60)
    print("ESCENARIO 5: Aplicar Carga (Simular Peso)")
    print("=" * 60)
    
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    sistema.conectar("192.168.0.100:5000")
    
    # Obtener un nodo para prueba
    node_ids = list(sistema._mock_nodes.keys())
    test_node_id = node_ids[0] if node_ids else None
    
    if test_node_id is None:
        print("[TEST] ✗ No hay nodos configurados")
        return False
    
    # Leer valor inicial
    print(f"\n[TEST] Valor inicial del nodo {test_node_id}:")
    datos = sistema.obtener_datos()
    for d in datos:
        if d['node_id'] == test_node_id:
            print(f"    Valor: {d['value']:.4f}")
    
    # Aplicar carga (simular peso de 50 kg)
    print(f"\n[TEST] Aplicando carga de +50 unidades al nodo {test_node_id}...")
    sistema._mock_nodes[test_node_id].apply_load(50.0)
    
    # Leer nuevo valor
    print(f"\n[TEST] Valor después de aplicar carga:")
    time.sleep(0.3)
    datos = sistema.obtener_datos()
    for d in datos:
        if d['node_id'] == test_node_id:
            print(f"    Valor: {d['value']:.4f} (debería ser ~50 más)")
    
    # Aplicar tara y verificar
    print(f"\n[TEST] Aplicando tara para 'cero'...")
    sistema.tarar(test_node_id)
    
    # Quitar carga
    print(f"\n[TEST] Quitando carga (-50)...")
    sistema._mock_nodes[test_node_id].apply_load(-50.0)
    
    time.sleep(0.3)
    datos = sistema.obtener_datos()
    for d in datos:
        if d['node_id'] == test_node_id:
            tared = d['value'] - sistema._tares.get(d['node_id'], 0)
            print(f"    Valor con tara: {tared:.4f} (debería ser ~-50)")
    
    sistema.desconectar()
    print("\n[TEST] ✓ Test de carga completado")
    return True


def test_lectura_continua():
    """Escenario 6: Lectura continua por 10 segundos."""
    print("\n" + "=" * 60)
    print("ESCENARIO 6: Lectura Continua (10 segundos)")
    print("=" * 60)
    
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    sistema.conectar("192.168.0.100:5000")
    
    print("\n[TEST] Iniciando lectura continua...")
    print("       (Observe el ruído y posibles pérdidas de paquetes)")
    
    start_time = time.time()
    lecturas_totales = 0
    lecturas_perdidas = 0
    expected_nodes = len(sistema._mock_nodes)
    
    while time.time() - start_time < 10:
        datos = sistema.obtener_datos()
        lecturas_totales += 1
        
        if len(datos) < expected_nodes:
            lecturas_perdidas += 1
        
        # Mostrar cada segundo
        if lecturas_totales % 10 == 0:
            elapsed = time.time() - start_time
            print(f"  [{elapsed:.1f}s] Lecturas: {lecturas_totales}, Pérdidas: {lecturas_perdidas}")
        
        time.sleep(0.1)  # 10 Hz
    
    print(f"\n[TEST] Resumen:")
    print(f"    Lecturas totales: {lecturas_totales}")
    print(f"    Lecturas con pérdida: {lecturas_perdidas}")
    print(f"    Tasa de pérdida: {(lecturas_perdidas/lecturas_totales)*100:.1f}%")
    
    sistema.desconectar()
    print("\n[TEST] ✓ Test de lectura continua completado")
    return True


def test_reconexion():
    """Escenario 7: Probar reconexión después de desconexión."""
    print("\n" + "=" * 60)
    print("ESCENARIO 7: Reconexión del Sistema")
    print("=" * 60)
    
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    
    # Primera conexión
    print("\n[TEST] Primera conexión...")
    sistema.conectar("192.168.0.100:5000")
    print(f"    Estado: {'Conectado' if sistema.esta_conectado() else 'Desconectado'}")
    
    # Desconectar
    print("\n[TEST] Desconectando...")
    sistema.desconectar()
    print(f"    Estado: {'Conectado' if sistema.esta_conectado() else 'Desconectado'}")
    
    # Reconectar
    print("\n[TEST] Reconectando...")
    sistema.conectar("192.168.0.100:5000")
    print(f"    Estado: {'Conectado' if sistema.esta_conectado() else 'Desconectado'}")
    
    # Verificar que funciona
    datos = sistema.obtener_datos()
    print(f"    Datos recibidos: {len(datos)} nodos")
    
    sistema.desconectar()
    print("\n[TEST] ✓ Test de reconexión completado")
    return True


def menu_interactivo():
    """Menú interactivo para seleccionar escenarios."""
    print("\n" + "=" * 60)
    print("       MENÚ DE PRUEBAS - BALANZA-PY")
    print("=" * 60)
    print()
    print("  1. Conexión Básica y Lectura")
    print("  2. Función de Tara")
    print("  3. Descubrimiento de Nodos")
    print("  4. Desconexión de Nodo (simular falla)")
    print("  5. Aplicar Carga (simular peso)")
    print("  6. Lectura Continua (10 seg)")
    print("  7. Reconexión del Sistema")
    print("  8. Ejecutar TODOS los tests")
    print("  0. Salir")
    print()
    
    while True:
        try:
            opcion = input("Seleccione opción (0-8): ").strip()
            
            if opcion == "0":
                print("\n¡Hasta luego!")
                break
            elif opcion == "1":
                test_conexion_basica()
            elif opcion == "2":
                test_tara()
            elif opcion == "3":
                test_descubrimiento_nodos()
            elif opcion == "4":
                test_desconexion_nodo()
            elif opcion == "5":
                test_aplicar_carga()
            elif opcion == "6":
                test_lectura_continua()
            elif opcion == "7":
                test_reconexion()
            elif opcion == "8":
                print("\n" + "=" * 60)
                print("EJECUTANDO TODOS LOS TESTS")
                print("=" * 60)
                
                tests = [
                    test_conexion_basica,
                    test_tara,
                    test_descubrimiento_nodos,
                    test_desconexion_nodo,
                    test_aplicar_carga,
                    test_lectura_continua,
                    test_reconexion,
                ]
                
                passed = 0
                for test in tests:
                    try:
                        if test():
                            passed += 1
                    except Exception as e:
                        print(f"[ERROR] {test.__name__}: {e}")
                
                print("\n" + "=" * 60)
                print(f"RESULTADO FINAL: {passed}/{len(tests)} tests pasaron")
                print("=" * 60)
            else:
                print("Opción inválida")
            
            input("\nPresione ENTER para continuar...")
            menu_interactivo()
            break
            
        except KeyboardInterrupt:
            print("\n\n¡Interrumpido por usuario!")
            break
        except Exception as e:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    menu_interactivo()
