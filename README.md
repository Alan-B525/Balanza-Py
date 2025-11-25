# Sistema de Pesaje con MSCL

Este programa permite monitorear 4 celdas de carga utilizando la librería MSCL de MicroStrain.

## Requisitos

1.  Python 3.x instalado.
2.  Librerías listadas en `requirements.txt`.

## Instalación

1.  Abre una terminal en la carpeta del proyecto.
2.  Instala las dependencias:
    ```bash
    pip install -r requirements.txt
    ```

## Ejecución

1.  Conecta la BaseStation al puerto USB.
2.  Ejecuta el programa:
    ```bash
    python app.py
    ```
3.  Ingresa el puerto COM correcto (ej. COM3, COM4) y haz clic en "Conectar".

## Funcionalidades

*   **Conexión**: Conecta a la BaseStation y escucha datos de cualquier nodo configurado.
*   **Visualización**: Muestra 4 valores individuales y el total.
*   **Tara**: El botón "TARA" establece el valor actual como 0.
*   **Reset Tara**: Restaura los valores brutos.
*   **Logo**: Haz doble clic en el texto "LOGO EMPRESA" para cargar una imagen personalizada.

## Notas sobre MSCL

El programa espera encontrar la librería MSCL en la carpeta `MSCL/x64/Release`. Si mueves el proyecto, asegúrate de mantener esta estructura o actualizar la ruta en `app.py`.
