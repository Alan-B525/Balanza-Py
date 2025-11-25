# Lista de Requerimientos Técnicos y Funcionales

Para asegurar el éxito del despliegue del **Sistema de Pesaje Industrial**, es necesario recopilar la siguiente información del cliente y del entorno de operación.

## 1. Entorno de Hardware y Software
*   **Dispositivo Principal:** ¿Qué equipo se usará? (Tablet, Laptop, PC Industrial).
*   **Sistema Operativo:** Versión exacta de Windows (ej. Windows 10 Pro, Windows 11 IoT, etc.).
*   **Resolución de Pantalla:** ¿Cuál es la resolución nativa del dispositivo? (ej. 1280x800, 1920x1080). *Crítico para que la interfaz se vea bien.*
*   **Entrada:** ¿Se usará pantalla táctil, mouse/teclado o ambos?

## 2. Sensores y Conectividad (MicroStrain)
*   **Hardware de Recepción:** ¿Qué modelo de BaseStation se utiliza? (ej. WSDA-200-USB).
*   **Nodos Inalámbricos:**
    *   Lista de **IDs de los Nodos** (Números de serie) que se usarán.
    *   ¿Cuántos nodos activos habrá simultáneamente? (Actualmente el diseño soporta 4).
*   **Configuración de Canales:**
    *   ¿Qué canal del nodo transmite el peso? (ej. `ch1`, `ch2`).
    *   ¿En qué unidad vienen los datos crudos? (Voltios, Strain, o ya calibrados en Kg?).
*   **Frecuencia de Muestreo:** ¿A qué velocidad envían datos los nodos? (ej. 1 Hz, 10 Hz).

## 3. Lógica de Pesaje y Calibración
*   **Calibración:**
    *   ¿Los nodos ya envían el valor en Kilos/Toneladas?
    *   Si envían datos crudos (ej. mV/V), ¿se requiere una pantalla de calibración en la app para ingresar factores (Pendiente/Offset)?
*   **Tara:**
    *   ¿La tara debe ser individual por sensor o solo del total?
    *   ¿Se necesita guardar el valor de tara entre reinicios de la app?
*   **Límites y Alarmas:**
    *   ¿Existe un peso máximo de seguridad?
    *   ¿Se requiere alerta visual/sonora si se excede cierto peso o si la señal es baja?

## 4. Garantía de Conexión y Ubicación (Crítico)
Para que el software detecte siempre los sensores y los ubique en la posición correcta de la pantalla (ej. "Rueda Delantera Izquierda" siempre en la esquina superior izquierda), necesitamos:

*   **Identificación de Nodos (Node Address):**
    *   Necesitamos el **Número de Serie (ID)** exacto de cada uno de los 4 nodos (ej. `36542`, `12987`).
    *   *¿Qué ID físico corresponde a qué posición física?* (ej. ID `36542` = Esquina Superior Izquierda).
*   **Configuración de Radiofrecuencia:**
    *   ¿En qué **Frecuencia** están configurados los nodos? (ej. Canal 15, 2.4GHz). Todos deben estar en la misma frecuencia que la BaseStation.
*   **Puerto de la BaseStation:**
    *   ¿La BaseStation siempre se conectará al mismo puerto USB?
    *   Si cambia de puerto, ¿el usuario sabrá seleccionarlo o necesitamos que el software busque automáticamente en todos los puertos? (El auto-descubrimiento requiere unos segundos extra al inicio).
*   **Estado de los Nodos:**
    *   ¿Los nodos están configurados en modo "Low Duty Cycle" (envío periódico) o "Synchronized Sampling"?
    *   Para visualización en tiempo real fluida, se recomienda una tasa de al menos 2 Hz a 10 Hz.

## 5. Identidad Visual
*   **Logo:** Archivo del logo de la empresa (PNG/JPG con fondo transparente preferiblemente).
*   **Colores Corporativos:** Códigos de color (Hex o RGB) si se requiere personalización específica.

## 6. Instalación
*   **Permisos:** ¿El usuario final tiene permisos de administrador para instalar drivers (USB)?
*   **Acceso a Internet:** ¿El equipo tendrá internet para actualizaciones remotas o funcionará offline?
