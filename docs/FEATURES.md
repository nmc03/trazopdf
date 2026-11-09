# Funciones y límites

TrazoPDF ofrece un conjunto local de herramientas de PDF. Esta tabla describe el alcance de las operaciones implementadas; las comprobaciones automatizadas no sustituyen la revisión de documentos reales, especialmente en conversiones, formularios y firmas.

| Área | Alcance | Límites relevantes |
| --- | --- | --- |
| Lectura | Renderizar páginas, zoom, buscar texto y navegar por marcadores. Vistas de página completa, ancho, 100 %, dos páginas y desplazamiento continuo. Cada documento recuerda su página, zoom y desplazamiento. | La búsqueda requiere una capa de texto; para escaneos puede ser necesario OCR. |
| Buscar y reemplazar | Barra con anterior y siguiente, contador de coincidencias y opciones de búsqueda; reemplazar texto del documento. | Solo encuentra y reemplaza texto con capa de texto. El reemplazo sigue los límites de edición de la fila Texto. |
| Texto | Seleccionar caracteres/palabras/líneas; escribir sobre la página; editar, mover y eliminar bloques de PDF existentes; cambiar estilo básico. | No redistribuye otros bloques como un documento Word. Las fuentes originales pueden sustituirse. El texto inclinado dentro de una página aún no se edita directamente. |
| Imágenes | Insertar, seleccionar, mover, redimensionar, sustituir y eliminar imágenes individuales con historial. | Edición acotada a imágenes directas compatibles; imágenes anidadas, inline o con estados gráficos complejos pueden no admitirla. Sustituir conserva el área y puede estirar la nueva imagen. No reconstruye el documento original de diseño. |
| Enlaces | Crear, editar, eliminar y listar enlaces web/correo y a páginas internas; apertura explícita desde el menú. | Otros tipos de destino se pueden eliminar, pero no editar ni ejecutar. |
| Anotaciones | Resaltado, notas, subrayado, tachado, figuras, tinta, líneas, flechas y cuadros de texto. Las notas tienen hilo de respuestas y estado, y se gestionan en el panel de comentarios. | La apariencia puede variar según el lector de PDF. |
| Censura | Marcar zonas para censurar y aplicar las censuras: se elimina el texto, las imágenes y los gráficos bajo la marca, y también los enlaces, campos de formulario y anotaciones que la tocan, y los metadatos, XMP y marcadores que citan el texto censurado. | Las marcas sin aplicar no censuran nada: el texto sigue en el archivo, por lo que guardar, exportar, extraer, dividir o firmar con marcas pendientes pide confirmación. Revisa adjuntos y otras zonas antes de compartir información sensible. |
| Buscar y censurar | Busca patrones (tarjetas con comprobación Luhn, IBAN, DNI/NIE, NIF/CIF, teléfonos, fechas, correos) o texto/expresiones regulares propias y marca las coincidencias elegidas; después ofrece aplicarlas. | Detecta lo que está escrito como texto: no lee imágenes escaneadas (usa OCR antes). Puede haber falsos positivos y falsos negativos; revisa la lista. |
| Anonimizar documento | Asistente que detecta datos personales (patrones de Buscar y censurar, más Seguridad Social, matrícula, IP y términos o expresiones propias), los censura, elimina metadatos, XMP, marcadores, adjuntos y anotaciones que los citan, reescribe una copia completa sin historial y verifica el resultado. Informe TXT o JSON que no repite los datos eliminados. | La verificación no detecta texto en fuentes con subconjunto de glifos ni en imágenes sin OCR. No admite documentos cifrados. El original no se modifica. |
| Páginas | Organizar, eliminar, duplicar, combinar, dividir con opciones, extraer, recortar y rotar. Combinar admite soltar varios PDF sobre la ventana. | El recorte cambia el área visible; no debe emplearse para censurar datos sensibles. |
| Formularios | Crear y rellenar campos AcroForm; texto y casillas se pueden rellenar directamente sobre la página. | No incluye formularios XFA ni todos los scripts JavaScript de Acrobat. |
| Campos automáticos | Detecta líneas y casillas de formularios sin campos y propone crearlos, con vista previa y selección antes de aplicar. | Solo detecta líneas cortas y casillas cuadradas; conviene revisar las propuestas. |
| Marcas | Añadir marcas de agua y números de página. | El resultado pasa a formar parte del PDF. |
| Encabezado y pie | Texto a izquierda, centro y derecha con {page}, {pages}, {date} y {filename}; márgenes, color y rango de páginas. | Texto en una sola línea; no ajusta el contenido de la página, así que puede solaparse con él. |
| Numeración Bates | Prefijo, sufijo, número inicial, dígitos y posición, sobre todas las páginas o un rango. | Se escribe en el contenido de la página; no se puede reasignar desde la aplicación salvo deshaciendo. |
| Sellos | Sellos predefinidos o una imagen, como anotación de sello quitable o dibujados en la página; se colocan con un clic (centrados) o arrastrando el tamaño. | El aspecto del sello como anotación depende del lector. |
| Etiquetas de página | Numeración por rangos (arábiga, romana, letras, prefijo) que se muestra en las miniaturas. | Solo cambia las etiquetas lógicas; no renumera el texto impreso en las páginas. |
| Insertar páginas | Página en blanco (A4, Carta, A3, A5 o medida propia), imagen como página y duplicado con copias. | Las imágenes se insertan como una sola página, sin OCR. |
| Aplanar | Incorpora anotaciones y campos de formulario al contenido de la página. | Los campos dejan de ser editables; se puede deshacer en la sesión. |
| Optimizar tamaño | Reduce la resolución y recomprime imágenes, limpia objetos sin uso y, si se quiere, retira metadatos. Muestra el tamaño estimado antes de aplicar y se ejecuta en un proceso aparte. | El tamaño final al guardar puede variar. Reducir ppp es una pérdida de calidad: guarda una copia si dudas. Si no se puede reducir, no cambia nada. |
| Comprobar documento | Informe de páginas escaneadas, fuentes no incrustadas, etiquetas de accesibilidad, título, idioma y JavaScript; doble clic lleva a la página. | Es una revisión rápida, no una validación PDF/UA ni PDF/A. |
| Comprobar accesibilidad | Informe por elemento (título, idioma, etiquetas, páginas sin texto, texto alternativo, marcadores) con corrección de título e idioma en un clic y exportación a texto. | Es una revisión rápida, no una validación PDF/UA. |
| Comparar texto | Diferencias de líneas de texto por página entre el documento abierto y otro PDF. | Compara por número de página; no ve imágenes ni formato (para eso está Comparar PDFs). |
| Información | Editar metadatos y gestionar archivos adjuntos. | No es una auditoría completa de todos los datos ocultos de un PDF. |
| Limpieza | Eliminar metadatos, adjuntos, JavaScript, enlaces y otros elementos mediante la operación de saneamiento. | Puede modificar formularios y eliminar contenido útil; revisa la copia resultante. |
| Protección | Contraseñas de apertura y de propietario con cifrado AES-256. Al guardar se conservan el método, los permisos y las contraseñas del archivo original. Si no se conoce la contraseña de propietario, se ofrece introducirla, proteger con contraseñas nuevas o guardar una copia sin protección. El diálogo de contraseña permite mostrar lo escrito y muestra los errores sin cerrarse. | Los permisos de impresión, edición y copia dependen de que el lector los respete. La contraseña de propietario original no se puede recuperar ni inferir. Quien conozca la de apertura pero no la de propietario no puede conservar las restricciones. |
| OCR | OCR local con Tesseract incluido en la aplicación y capa de texto; modelos de español, inglés, francés, alemán y portugués; enderezado y detección de orientación opcionales; páginas escaneadas y mixtas; función reutilizable `ocr_file` para lotes. | En una ejecución desde el código fuente requiere Tesseract instalado. El enderezado corrige hasta unos 10° y tarda más. La detección de coincidencias evita duplicar texto existente; los errores de reconocimiento necesitan revisión. |
| Office → PDF | Conversión mediante LibreOffice. | Requiere LibreOffice; no garantiza el mismo diseño que Microsoft Office. |
| PDF → DOCX | Exportación de texto extraído. | No mantiene fielmente la maquetación del PDF. |
| PDF → XLSX | Exportación de tablas detectadas; texto en filas cuando no hay tablas. | La detección depende de la estructura visual; no convierte cualquier página en una tabla correcta. |
| PDF → PPTX | Una imagen de página por diapositiva. | Los elementos de la página no se convierten en objetos editables. |
| Comparación | Vista de ambos documentos y diferencias visuales en magenta; navegación por cambios e informe ZIP; procesamiento cancelable. | Compara por número de página, con rasterización limitada a 110 ppp y 1400 px de lado. Cambios pequeños pueden quedar por debajo de la resolución o tolerancia. No compara metadatos, enlaces, firmas ni contenido oculto; no alinea páginas insertadas automáticamente. |
| Historial | Deshacer y rehacer cambios de la sesión. Registro de los últimos 20 mensajes de la barra de estado. | Deshacer no sobrevive al cierre del documento; la recuperación de cambios se describe en Documentos. |
| Documentos | Pestañas para varios PDF abiertos a la vez, cada una con su historial, página, zoom y búsqueda. Autoguardado periódico y ofrecimiento de recuperar cambios no guardados al iniciar. Copia `.bak` opcional al guardar, Guardar copia y Revertir. Recientes con fecha y miniatura, y memoria de vista por archivo. | La copia de recuperación es local y se elimina al guardar o cerrar correctamente. No sustituye a guardar el archivo. Los documentos protegidos no se autoguardan: se avisa una vez para no escribir una copia sin cifrar. |
| Medir | Medición de distancias sobre la página, con escala. | La precisión depende de la escala configurada. No es una medición certificada. |
| Capas | Muestra u oculta las capas de contenido opcional que trae el PDF. | Solo alterna capas existentes; no crea ni edita capas. |
| Acciones guiadas | Asistentes paso a paso para tareas frecuentes, como combinar, comprimir, censurar o firmar. | Cada paso usa una herramienta existente y sus límites son los de esa herramienta. |
| Impresión | Vista previa antes de imprimir; las páginas se generan a la resolución de la impresora (entre 150 y 600 ppp). | Depende del controlador y de la impresora seleccionados. |
| Lotes y recetas | Procesa carpetas o grupos de PDF con una receta: lista ordenada de pasos (anonimizar, OCR, optimizar, limpiar metadatos, marca de agua, numeración, Bates, girar, recortar, firmar con certificado, exportar texto). Incluye tres recetas predefinidas, editor de pasos, guardar/importar/exportar en JSON y progreso con cancelación. También sin ventana: `--batch` y `--watch` (carpeta vigilada cada 5 s). | Los originales no se modifican y, si un archivo falla, se sigue con el siguiente. La contraseña del certificado se pide al ejecutar y nunca se guarda. Los PDF cifrados no se procesan. Cada archivo se procesa en el mismo proceso, uno tras otro. |

## Seguridad de los archivos de salida

- Un PDF abierto con contraseña se guarda con la misma protección. La contraseña de propietario generada al proteger se muestra una sola vez; no se almacena en ningún sitio.
- Exportar (TXT, DOCX, XLSX, PPTX, PNG), extraer páginas, dividir y firmar desde un documento protegido genera archivos **sin contraseña ni restricciones**; la aplicación avisa antes de cada operación.
- Guardar, exportar, extraer, dividir, firmar y las tareas de OCR o comparación se detienen si hay censuras sin aplicar, y ofrecen aplicarlas.
- Los trabajos en segundo plano usan carpetas temporales `pdf-editor-job-*` que se eliminan al terminar; al iniciar se borran las que hayan quedado de ejecuciones interrumpidas con más de un día.

## Firma digital

La firma PKCS#12 usa pyHanko y genera una copia firmada. Puedes elegir entre firma **invisible** (solo queda constancia en el archivo) y firma **visible**: eliges la página, dibujas arrastrando el rectángulo y decides qué muestra (nombre del firmante del certificado, fecha, motivo, lugar y, opcionalmente, una de tus imágenes de firma guardadas).

Firmar un documento que ya tiene firmas añade una revisión incremental: las firmas anteriores siguen siendo válidas y la aplicación lo avisa antes de firmar. Modificar o volver a guardar un PDF firmado puede invalidar sus firmas existentes.

"Examinar firmas…" valida cada firma de forma local y muestra: integridad (si el documento se modificó tras firmar), validez criptográfica, estado de la cadena de confianza frente a los certificados raíz del sistema o de certifi (si no se puede verificar: "no verificada: certificado autofirmado o raíz desconocida", sin tratarlo como un fallo) y sello de tiempo, si lo hay. **La revocación no se comprueba**, porque no se consulta ninguna red.

Límites: no se usan servicios de terceros ni de Adobe, no hay firma remota ni envío a firmantes, y el resultado no equivale a una firma electrónica cualificada eIDAS. Revisa los documentos importantes con un lector independiente. La API sin interfaz está en `pdf_editor/signing.py`: `sign_file(path_in, path_out, p12, password, field_spec, appearance) -> Report` y `validate_file(path) -> list[SignatureInfo]`.

Para firmar un documento cifrado debes guardar explícitamente una copia sin contraseña. La aplicación no retira la protección de forma implícita para firmar. Las tareas largas (OCR, conversión Office, exportar, dividir, firmar, imágenes, lotes, optimizar y comprobar documento) muestran su progreso y se pueden cancelar; al cancelar se borran las salidas parciales.

## Funciones de Acrobat Pro que no están cubiertas

La edición directa se orienta a texto digital. En escaneos, OCR crea una capa buscable y no reconstruye la imagen original como un documento editable de Office. Editar esa capa no equivale a sustituir el contenido gráfico del escaneo.

No se ofrece paridad completa con Acrobat Pro. Estos límites están fuera de alcance:

- **Sellos de tiempo**: opcionales y desactivados por defecto; hay que indicar la autoridad de sellado y exigen conexión. No hay sellado de Adobe.
- **PDF/A y PDF/X**: no se convierte ni se certifica el cumplimiento. "Comprobar documento" es una revisión rápida, no una validación.
- **JavaScript de formularios y XFA**: no se ejecutan scripts de formulario ni se editan formularios XFA.
- **PDF 3D y contenido multimedia**.
- **Compartir en la nube**: no hay servicios de Adobe, revisión en línea ni envío de documentos o firmas a terceros.
- **Otros**: aplicaciones móviles, carteras PDF y el etiquetado automático o la edición de etiquetas de accesibilidad.

Tampoco se garantiza compatibilidad con todos los documentos complejos, formularios dinámicos, fuentes o perfiles de color.

Referencia de producto: [comparativa oficial de Acrobat](https://www.adobe.com/acrobat/pricing/compare-versions.html) y [herramientas de Acrobat](https://helpx.adobe.com/acrobat/using/explore-acrobat-tools.html). Estas referencias orientan el alcance; no demuestran que la nueva aplicación reproduzca cada función.
