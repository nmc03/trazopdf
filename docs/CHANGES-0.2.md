# TrazoPDF 0.2

Esta revisión cambia la interacción con el documento a partir de las pruebas de uso y los problemas comunicados por el usuario.

## Edición sobre la página

- Selección por caracteres, palabras y líneas. Arrastrar selecciona texto; doble clic selecciona una palabra; Ctrl+C copia. Resaltado, subrayado y tachado se aplican al texto seleccionado.
- Añadir texto permite hacer clic y escribir en el documento. Ctrl+Enter aplica; Esc cancela; guardar también aplica el texto pendiente.
- Editar PDF permite seleccionar bloques con el puntero, arrastrarlos para moverlos y eliminarlos con Supr. Doble clic o F2 abre la edición directa del bloque.
- El contenido de PDF existentes se puede editar; al guardar y reabrir, los cambios siguen siendo texto del PDF.
- Controles de tamaño, familia, color, negrita y cursiva. Se conserva el color y se intenta aproximar el estilo del bloque original.
- Deshacer y rehacer distinguen la escritura en curso de los cambios ya aplicados al documento.
- Los campos de texto AcroForm se pueden rellenar sobre la página; las casillas responden al clic.

## Disposición

- Herramientas a la izquierda; miniaturas y marcadores a la derecha.
- Panel de páginas plegable mediante la flecha de su cabecera; se recuerda la preferencia.
- Etiquetas bajo las miniaturas y renderizado adaptado a la densidad de pantalla.
- La selección múltiple de páginas se conserva durante las operaciones.

## Correcciones

- Reemplazar texto no aplica otras censuras pendientes ni pinta un rectángulo blanco sobre fondos de color.
- Unicode: otros alfabetos dejan de convertirse silenciosamente en signos de interrogación.
- Extraer páginas respeta el orden solicitado.
- Cerrar el documento limpia las coincidencias de búsqueda.
- Cambiar de zoom cancela los gestos transitorios de forma segura y aplica primero el texto que se estaba escribiendo.
- Si el texto no cabe, el editor conserva lo escrito y no guarda un resultado incompleto.
- Los cambios de varios campos de un formulario forman una sola operación que puede deshacerse; un fallo revierte todos los cambios de ese envío.
- OCR y conversión Office usan procesos separados con cancelación. Un fallo o cancelación conserva el documento que estaba abierto.
- OCR de páginas mixtas: reconoce zonas de imagen y conserva el texto buscable que ya existía.

## Límites que siguen presentes

La edición usa bloques detectados por el motor PDF: no reconstruye el documento original de Word ni redistribuye automáticamente otros bloques. Las fuentes originales pueden sustituirse por una familia equivalente. Los bloques inclinados internamente todavía no se editan directamente; las páginas giradas 90/180/270 grados sí están contempladas. Las exportaciones Office conservan los límites descritos en FEATURES.md.

Las pruebas automatizadas y la revisión visual cubren casos concretos; no prueban compatibilidad con todos los PDF ni paridad completa con Acrobat Pro.
