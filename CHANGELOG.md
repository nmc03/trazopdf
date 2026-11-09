# Historial de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [0.5.0] - 2026-11-08

### Añadido
- **TrazoPDF**: la aplicación pasa a llamarse TrazoPDF (ejecutable, instalador y carpeta de ajustes; los ajustes de versiones previas no se migran).
- Interfaz y documentación en español, inglés, francés, alemán y portugués: el idioma se elige en Ayuda > Idioma (o `PDFEDITOR_LANG`) y se aplica al reiniciar. README y manual de usuario en los cinco idiomas.
- Anonimizar documento: eliminación irreversible de texto, imágenes, metadatos, anotaciones, adjuntos y datos ocultos, con vista previa, verificación posterior e informe.
- Lotes y recetas: cadenas de pasos (11 tipos, con recetas predefinidas) aplicadas a carpetas desde la interfaz o por línea de comandos (`--batch`, `--watch`) con códigos de salida 0/1/2 y política de conflictos.
- OCR integrado y 100 % local: Tesseract se incluye en la aplicación con modelos de español, inglés, francés, alemán y portugués, enderezado y detección de orientación.
- Firma electrónica visible con campo y apariencia configurables, y validación de firmas existentes; la clave se puede pasar por `PDFEDITOR_SIGN_PASSWORD` en lotes.
- Atajo K para el campo de formulario y F para rellenar.
- Instalador de Windows (sin firmar) y autodespliegue de versiones al fusionar en `main`.

- Varios PDF abiertos a la vez, en pestañas sobre el lienzo: cada una conserva su página, zoom, desplazamiento, búsqueda, historial de deshacer y copia de recuperación. Abrir un archivo ya abierto activa su pestaña; Ctrl+Tab y Ctrl+Mayús+Tab cambian de pestaña, Alt+1 a Alt+9 saltan a una y Ctrl+W cierra la actual.
- Comprobar accesibilidad (Herramientas): informe por elemento con corrección de título e idioma en un clic y exportación a texto.
- Firma digital con sello de tiempo opcional: se activa a mano, con la dirección de la autoridad que elija el usuario; sin ella no se envía nada a la red.
- Vista continua y de dos páginas: la selección de texto cruza páginas, los campos de formulario se rellenan en cualquier página visible y los campos detectados automáticamente se marcan en todas.
- Cada pestaña recuerda su panel lateral y la selección de miniaturas; las pestañas se reordenan arrastrando.
- Interfaz renovada: raíl de herramientas con grupos e iconos propios, barra superior con navegador de páginas y zoom en píldoras, panel de páginas con tarjetas, pantalla de bienvenida con recientes y tema claro, oscuro o del sistema.
- Herramientas de documento, disponibles en el raíl (grupo Herramientas) y en los menús, todas con deshacer y rehacer: encabezado y pie de página, numeración Bates, buscar y censurar datos sensibles, optimizar tamaño, aplanar anotaciones y formularios, etiquetas de página (visibles en las miniaturas), insertar páginas (en blanco, desde imagen o duplicadas), sellos colocados con un clic o arrastrando, comprobar documento y comparar texto entre dos PDF.
- Optimizar tamaño y Comprobar documento se ejecutan en un proceso aparte, sin bloquear la ventana.
- Cuadro «Acerca de» con versión, licencia, enlaces a LICENSE y THIRD-PARTY.md y diagnóstico de Tesseract y LibreOffice (se pueden indicar con `PDFEDITOR_TESSERACT` y `PDFEDITOR_SOFFICE`).
- Al abrir un PDF con restricciones se ofrece introducir la contraseña de propietario para poder guardarlo conservándolas.
- Al proteger un documento se puede elegir la contraseña de propietario; si se deja vacía se genera una segura y se muestra una sola vez, con botón para copiarla.
- Documentos: autoguardado periódico con recuperación de cambios no guardados al iniciar, copia `.bak` opcional al guardar, Guardar copia (sin cambiar el documento abierto) y Revertir.
- Vista: desplazamiento continuo y vista de dos páginas, con página, zoom y desplazamiento recordados por archivo. Recientes con fecha y miniatura, y opción de quitarlos de la lista.
- Páginas: Dividir con opciones de reparto, y Archivo > Exportar como para texto, Word, Excel, PowerPoint e imágenes. Soltar varios PDF sobre la ventana para combinarlos.
- Buscar y reemplazar texto del documento, con navegación entre coincidencias.
- Anotaciones: herramientas Línea, Flecha y Cuadro de texto. Los comentarios tienen autor, respuestas y estado, y se gestionan en un panel propio.
- Medir distancias con escala, Capas para mostrar u ocultar capas opcionales, y acciones guiadas para tareas frecuentes.
- Diálogo de contraseña con botón Mostrar y errores en línea.
- Ayuda > Atajos de teclado (F1), historial de los últimos 20 mensajes de la barra de estado, Ctrl+Y para rehacer y Ctrl+A para seleccionar todo según el foco.

### Cambiado
- Guardar conserva el cifrado, los permisos y las contraseñas del archivo original. Si no se puede conservar la protección, se ofrece introducir la contraseña de propietario, proteger con contraseñas nuevas o guardar una copia sin protección.
- Aplicar censuras también elimina los enlaces, campos de formulario y anotaciones que quedan bajo las marcas, y los metadatos que citan el texto censurado; el aviso lo explica.
- Las exportaciones, extracciones, divisiones y copias firmadas de un documento protegido avisan de que el resultado no tendrá contraseña.
- La ventana muestra la versión real de la aplicación.

### Corregido
- Guardar, exportar, extraer, dividir, firmar y las tareas de OCR o comparación ya no escriben texto que sigue bajo censuras sin aplicar sin avisar; se ofrece aplicarlas primero.
- La apertura de PDF cifrados no consulta el documento ya abierto, lo que evita lecturas erróneas tras pedir la contraseña.
- Eliminar un comentario desde la lista de anotaciones se puede deshacer y se revierte si falla.
- Las carpetas temporales de trabajos interrumpidos se eliminan al iniciar si tienen más de un día.

## [0.3.0] - 2026-10-18

### Añadido
- Manipulación de imágenes desde Editar PDF: selección, arrastre, esquinas para redimensionar, sustitución y eliminación. Cada operación afecta a una aparición concreta de la imagen, y las demás copias compartidas se conservan cuando la estructura del PDF lo permite.
- Enlaces web, de correo y a páginas internas: creación por área, edición, eliminación, listado y apertura explícita.
- Comparación visual de dos PDF en un proceso separado y cancelable, con tres vistas, navegación por cambios, zoom sincronizado y exportación del informe en ZIP.

### Corregido
- Coordenadas de los enlaces en páginas recortadas y giradas.
- Una nueva comparación exige una carpeta de salida vacía, para no sobrescribir un informe anterior.
- Las líneas se conservan al unir varios segmentos de texto compatibles en un bloque editable.

## [0.2.0]

### Añadido
- Selección de texto por caracteres, palabras y líneas, con copia y marcado (resaltado, subrayado, tachado).
- Añadir texto haciendo clic sobre la página.
- Edición de bloques de texto de PDF existentes: mover, editar en el sitio y eliminar, con control de tamaño, familia, color, negrita y cursiva.
- Rellenado de campos de formulario AcroForm directamente sobre la página.
- Panel de páginas plegable y miniaturas con etiquetas.
- OCR de páginas escaneadas y mixtas, y conversión de Office a PDF, ambas canceladas sin perder el documento abierto.

### Corregido
- Reemplazo de texto sin aplicar censuras pendientes ni dibujar rectángulos blancos sobre fondos de color.
- Caracteres de otros alfabetos que se convertían en signos de interrogación.
- Extracción de páginas en el orden solicitado.
- Los cambios de varios campos de un formulario forman una sola operación deshacible.
