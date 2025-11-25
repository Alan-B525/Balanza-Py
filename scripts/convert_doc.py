import markdown
from xhtml2pdf import pisa
import os

def convert_md_to_pdf(source_md, output_pdf):
    # 1. Leer el archivo MD
    with open(source_md, 'r', encoding='utf-8') as f:
        text = f.read()

    # 2. Convertir MD a HTML
    html_text = markdown.markdown(text)

    # Agregar algo de estilo básico para que se vea mejor
    html_content = f"""
    <html>
    <head>
    <style>
        body {{ font-family: Helvetica, sans-serif; font-size: 12pt; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #2c3e50; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 20px; }}
        h3 {{ color: #7f8c8d; }}
        code {{ background-color: #f8f9fa; padding: 2px 4px; font-family: monospace; }}
        pre {{ background-color: #f8f9fa; padding: 10px; border: 1px solid #ddd; }}
        li {{ margin-bottom: 5px; }}
        img {{ max-width: 100%; height: auto; margin: 20px 0; border: 1px solid #ddd; }}
    </style>
    </head>
    <body>
    {html_text}
    </body>
    </html>
    """

    # 3. Convertir HTML a PDF
    with open(output_pdf, "wb") as result_file:
        pisa_status = pisa.CreatePDF(
            html_content,                # the HTML to convert
            dest=result_file             # the file handle to recieve result
        )

    if pisa_status.err:
        print(f"Ocurrió un error al crear el PDF: {pisa_status.err}")
    else:
        print(f"PDF creado exitosamente: {output_pdf}")

if __name__ == "__main__":
    source = "Propuesta_Tecnica_Software.md"
    output = "Propuesta_Tecnica_Software.pdf"
    
    if os.path.exists(source):
        print(f"Convirtiendo {source} a PDF...")
        try:
            convert_md_to_pdf(source, output)
        except ImportError:
            print("Error: Faltan librerías.")
            print("Ejecuta: pip install markdown xhtml2pdf")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print(f"No se encontró el archivo {source}")
