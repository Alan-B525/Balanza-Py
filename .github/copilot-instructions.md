# Copilot Instructions for Balanza-Py

## Visión General
Este sistema monitorea 4 celdas de carga industriales usando la librería MSCL de MicroStrain, con una interfaz gráfica moderna. El código está organizado en módulos para facilitar la extensión y el mantenimiento.

## Arquitectura y Componentes Clave
- **main.py**: Orquesta la aplicación, inicia la GUI y gestiona los hilos principales.
- **config.py**: Configuración global. Cambia `MODO_EJECUCION` entre "REAL" y "MOCK" para alternar entre hardware y simulación.
- **modules/**:
  - `gui.py`: Interfaz gráfica (Tkinter + ttkbootstrap). Usa botones grandes y táctiles.
  - `data_processor.py`: Lógica de negocio, cálculo de promedios, tara y calibración.
  - `sensor_driver.py` y `sensor_mock.py`: Drivers para hardware real y simulación.
  - Otros módulos: `factory.py`, `logger.py`, `interfaces.py` para patrones de diseño y logging.
- **MSCL/**: Librería nativa de MicroStrain (no modificar).
- **calibrations/**: Archivos JSON con calibraciones por nodo.
- **assets/**: Logo e iconos. El logo se carga automáticamente si existe `logo.png`.

## Flujos de Trabajo
- **Instalación**: Ejecuta `pip install -r requirements.txt`.
- **Ejecución**: Corre `python main.py` desde la raíz. El modo de operación depende de `config.py`.
- **Pruebas**: Usa los scripts en `scripts/` para pruebas unitarias y de integración.
- **Build**: El script `scripts/build_exe.py` genera ejecutables. Revisa la carpeta `build/` para artefactos.

## Convenciones y Patrones
- **Configuración**: Todos los parámetros globales están en `config.py`.
- **Drivers**: Usa `sensor_driver.py` para hardware y `sensor_mock.py` para simulación. El modo se selecciona automáticamente.
- **Calibración**: Los datos de calibración se almacenan en `calibrations/*.json` y se cargan dinámicamente.
- **Logging**: Los eventos y errores se muestran en la GUI y se gestionan vía `logger.py`.
- **Interfaz**: La GUI está optimizada para pantallas táctiles y tablets.

## Integraciones y Dependencias
- **MSCL**: La librería está en `MSCL/` y se importa localmente. No requiere instalación externa.
- **ttkbootstrap**: Usada para la interfaz gráfica.

## Ejemplo de Extensión
Para agregar un nuevo tipo de sensor:
1. Crea un nuevo driver en `modules/` siguiendo el patrón de `sensor_driver.py`.
2. Actualiza `factory.py` para incluir el nuevo driver.
3. Ajusta la configuración en `config.py` si es necesario.

## Referencias Clave
- `main.py`, `config.py`, `modules/gui.py`, `modules/data_processor.py`, `modules/sensor_driver.py`, `modules/sensor_mock.py`, `scripts/build_exe.py`

---
Actualiza estas instrucciones si cambian los flujos de trabajo o la arquitectura. Solicita feedback si alguna sección no es clara o está incompleta.
