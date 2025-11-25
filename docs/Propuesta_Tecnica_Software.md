Sistema de Monitoreo de Pesaje Digital

## 1. Resumen

El software permite la adquisición de datos en tiempo real mediante el protocolo MSCL (MicroStrain Communication Library), visualización de cargas individuales y totales, y gestión de tara.

## 2. Alcance del Proyecto

### 2.1. Objetivos Principales
*   **Adquisición de Datos:** Lectura simultánea de 4 nodos/canales de celdas de carga vía inalámbrica usando la BaseStation de MicroStrain.
*   **Visualización:** Interfaz gráfica.
*   **Operatividad:** Funciones de Tara y Reset Tara accesibles y rápidas.
*   **Registro:** (Log) de eventos en pantalla para diagnóstico rápido.

### 2.2. Funcionalidades Incluidas
1.  **Detección Automática:** El sistema identifica automáticamente los nodos activos y los asigna a las posiciones de visualización.
2.  **Cálculo total:** Sumatoria instantánea de las cargas para mostrar el Peso Total Neto.
3.  **Gestión de Tara:** Capacidad de establecer el "Cero" lógico del sistema por software.

### 2.3. Requisitos del Sistema
*   **Hardware:** Tablet o PC con Windows 10/11 (x64).
*   **Configuración Previa:** Se requiere el software **SensorConnect** de MicroStrain para realizar la configuración inicial de los nodos y la red inalámbrica (frecuencias, tasas de muestreo, calibración). Este software de monitoreo está diseñado exclusivamente para la lectura de datos y no permite modificar parámetros de hardware.

---

## 3. Manual de Interfaz y Operación

![Interfaz de Usuario - Aproximación Inicial](interfaz_de_usuario.png)
*Figura 1: Primera aproximación de la interfaz de usuario propuesta.*

La interfaz se ha dividido en tres secciones lógicas para facilitar el flujo de trabajo del operador:

### 3.1. Barra Superior (Encabezado)
*   **Logo:** Espacio personalizable para identidad corporativa.
*   **Botón "Conectar Sistema":**
    *   *Función:* Inicia la búsqueda automática del receptor y comienza a escuchar los nodos inalámbricos.
    *   *Estado:* Cambia de texto para indicar si el sistema está "En Línea" o "Desconectado".
*   **Botón "X":**
    *   *Función:* Cierra la aplicación de manera segura.
    *   *Seguridad:* Incluye un cuadro de diálogo de confirmación para evitar cierres accidentales.

### 3.2. Área de Visualización (Celdas)
Cuatro paneles distribuidos en las esquinas de la pantalla representan la ubicación física de las celdas de carga.
*   **Indicador:** Muestra el peso individual de cada celda en kilogramos (kg).
*   **Identificación:** Muestra el ID del Nodo y el canal correspondiente para facilitar el mantenimiento.

### 3.3. Panel de Control Central
Ubicado en el centro de la pantalla, es el área principal de trabajo:

*   **PESO TOTAL:**
    *   Muestra la suma algebraica de las 4 celdas menos la tara aplicada.
    *   Tipografía de gran tamaño para lectura a distancia.

*   **Botón "TARA":**
    *   *Acción:* Captura el peso actual de todas las celdas y lo establece como el nuevo "Cero".
    *   *Uso:* Se utiliza para descontar el peso de recipientes, pallets o estructuras vacías antes de iniciar el pesaje del producto.
    *   *Feedback:* Muestra debajo el valor de "Tara acumulada" para que el operador sepa cuánto peso se está restando.

*   **Botón "RESET TARA":**
    *   *Acción:* Borra cualquier tara almacenada y devuelve el sistema a mostrar el peso bruto absoluto de los sensores.
    *   *Uso:* Se utiliza al finalizar un lote o para verificar la calibración en vacío.

### 3.4. Registro de Eventos (Log)
Ubicado en la parte inferior, muestra mensajes del sistema:
*   Confirmación de conexión exitosa.
*   Confirmación de acciones de Tara/Reset.
*   Alertas de errores de comunicación o desconexiones.

---

