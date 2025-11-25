# Sistema de Pesaje Industrial (Balanza-Py)

Este programa permite monitorear 4 celdas de carga utilizando la librería MSCL de MicroStrain, con una interfaz moderna y robusta.

## Requisitos

1.  Python 3.13 o superior.
2.  Librerías listadas en `requirements.txt`.
3.  Librería MSCL (incluida localmente en la carpeta `MSCL/`).

## Instalación

1.  Abre una terminal en la carpeta del proyecto.
2.  Instala las dependencias:
    ```bash
    pip install -r requirements.txt
    ```

## Configuración

Antes de ejecutar, abre el archivo `config.py` para ajustar los parámetros del sistema:

*   **MODO_EJECUCION**: Cambia a `"REAL"` para usar el hardware o `"MOCK"` para simulación.
*   **PUERTO_COM**: Define el puerto de la BaseStation (ej. `"COM3"`).
*   **NODOS_CONFIG**: Configura los IDs de los nodos inalámbricos y sus canales.

## Personalización (Logo)

Para cambiar el logo de la empresa:
1.  Coloca tu imagen de logo en la carpeta `assets/`.
2.  Renombra el archivo a `logo.png`.
3.  El sistema lo cargará automáticamente al iniciar.

## Ejecución

1.  Conecta la BaseStation al puerto USB (si estás en modo REAL).
2.  Ejecuta el programa principal:
    ```bash
    python main.py
    ```
3.  Haz clic en el botón **"CONECTAR"** en la interfaz.

## Funcionalidades

*   **Conexión**: Gestiona la conexión con la BaseStation MSCL.
*   **Monitoreo**: Visualización en tiempo real de 4 sensores y peso total.
*   **Tara**: El botón "TARA" establece el valor actual como 0.
*   **Zerar Tara**: Restaura la calibración original (requiere confirmación).
*   **Logs**: Registro de eventos y errores en pantalla.
*   **Interfaz Táctil**: Botones grandes optimizados para tablets.

## Estructura del Proyecto

*   `main.py`: Punto de entrada y orquestación de hilos.
*   `config.py`: Archivo de configuración global.
*   `modules/`:
    *   `gui.py`: Interfaz gráfica (Tkinter + ttkbootstrap).
    *   `data_processor.py`: Lógica de negocio, promedios y tara.
    *   `sensor_real.py` / `sensor_mock.py`: Drivers de hardware.
*   `assets/`: Recursos gráficos (logos, iconos).
*   `MSCL/`: Librerías nativas de MicroStrain.
