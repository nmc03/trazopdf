# DESIGN.md - TrazoPDF (Windows, Qt/QSS)

Contrato de diseño para la interfaz en español. La cobertura funcional está en `docs/FEATURES.md`. Este archivo no afirma paridad con Acrobat.

**Perfiles del toolkit design-system-library usados:** `catalog/linear.app/DESIGN.md` (superficies en capas con bordes de 1 px, un único acento cromático, anillo de foco, pestañas y selectores en forma de píldora, densidad de herramienta profesional), `catalog/raycast/DESIGN.md` (jerarquía de superficies oscuras, bordes finos, radios de 6 a 10 px, lista de comandos con fila activa suave) y `catalog/figma/DESIGN.md` (herramienta de lienzo con barra de herramientas lateral por grupos y lienzo neutro). También se aplicaron las reglas de accesibilidad e interacción de `skills/web-design-guidelines` (foco visible, contraste, nombres accesibles, objetivos táctiles, `prefers-color-scheme`). Solo se adaptan principios: no se copian marcas, fuentes ni activos.

## 1. Principios
- Neutros tranquilos con un único acento teal (acción primaria, herramienta activa, selección, foco y progreso).
- La jerarquía se construye con superficies, bordes de 1 px y peso tipográfico. La única sombra es la de la página sobre el lienzo, pintada en `canvas.py`.
- Raíl de herramientas a la izquierda (con etiquetas o solo iconos), documento al centro y panel de navegación a la derecha. El documento es el protagonista.
- Sin degradados, sin emojis, sin decoración. Los iconos son una familia de línea propia.
- Tema claro y oscuro con los mismos nombres de token.

## 2. Paleta (tokens `@nombre`; `theme.py` los sustituye antes de aplicar el QSS)
| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| accent | #0A7A6C | #3FC1AF | Primario, herramienta activa, foco, progreso |
| accenthover | #08695D | #5ED0C0 | Hover del primario |
| accentpressed | #065248 | #2DA695 | Pulsado |
| accentsoft | #DDF0EC | #173C37 | Relleno de selección y herramienta activa |
| onaccent | #FFFFFF | #04211D | Texto e icono sobre el acento |
| canvas | #E6E9EB | #141819 | Fondo del área de documento |
| surface0 | #F4F6F7 | #1B2022 | Ventana, raíl, panel de páginas |
| surface1 | #FFFFFF | #22282B | Barra superior, campos, menús, tarjetas |
| surface2 | #E9EDEE | #2C3437 | Hover neutro |
| pill | #EEF1F2 | #2A3134 | Fondo de los grupos tipo píldora y del buscador |
| border | #D9DFE1 | #343D41 | Divisores y bordes decorativos |
| borderstrong | #848F93 | #7A878C | Bordes de campos (>= 3:1) |
| ink | #1A2225 | #E9EEEF | Texto principal |
| inkmuted | #4B575B | #A7B3B7 | Texto secundario e iconos de reposo |
| inkdisabled | #8B9599 | #68757A | Deshabilitado |
| danger | #B42318 | #F2796E | Error y acciones destructivas |
| shadow | #0B1417 | #000000 | Sombra de la página y de las miniaturas |

Contrastes verificados por `tests/test_theme.py` en ambos temas: texto >= 4.5:1 sobre sus superficies (incluido `inkmuted` sobre `surface2`, `pill` y `accentsoft`), `onaccent` sobre `accent` en reposo, hover y pulsado >= 4.5:1, y `accent` y `borderstrong` >= 3:1 como anillo de foco y borde de control.

## 3. Tipografía (solo fuentes instaladas en Windows)
- Familia: `"Segoe UI Variable Text", "Segoe UI", Arial`. Titulares: `"Segoe UI Variable Display", "Segoe UI"`.
- Tamaños en pt para respetar la escala DPI de Qt.

| Rol | pt | Peso |
|---|---|---|
| title (bienvenida) | 21 | 600 |
| subtitle | 10.5 | 400 |
| heading (panel, marca) | 10-11 | 600 |
| body | 9.5 | 400 |
| control | 9.5 | 500 |
| section (grupos del raíl) | 8.5 | 600 |
| caption (estado, miniaturas) | 8.5 | 400 |

## 4. Espaciado, radios y tamaños
- Base de 4 px: 4, 8, 12, 16, 24, 32.
- Radios: controles 8, píldoras 10, menús y listas 10-12, tarjeta de bienvenida 16.
- Barra superior: botones de 28 + borde de foco de 2. Iconos de 20 (18 dentro de píldoras).
- Raíl: 240 expandido (mín. 224, máx. 300) y 56 compacto. Filas de herramienta de unos 26 px con icono de 18.
- Panel derecho: 210 por defecto, mín. 176, máx. 300; 38 plegado.
- Margen de la página en el lienzo: 32 unidades de escena por lado.

## 5. Iconos
- `pdf_editor/icons.py`: cuadrícula de 24 px, trazo de 1.75 px, extremos y uniones redondeados, SVG en línea dibujados para este proyecto (no se usa ningún paquete de iconos externo).
- Se renderizan con `QSvgRenderer` a 16, 20, 24, 32, 40, 48 y 64 px y se tiñen según el tema: reposo (`inkmuted` o `ink`), hover (`ink`), deshabilitado (`inkdisabled`) y activo (`accent` en el estado checked).
- Cada herramienta, acción de la barra superior y acción de documento tiene su icono. Todo botón solo-icono lleva `toolTip` y `accessibleName`.
- Al cambiar de tema `EditorWindow.apply_icons()` vuelve a teñir todos los iconos registrados con `bind_icon`.

## 6. Estados (todos los controles)
- normal: borde `borderstrong` en campos; botones de barra y raíl sin borde.
- hover: `surface2` (dentro de una píldora, `surface1`).
- pressed: `accentsoft`.
- checked/selected: `accentsoft` y texto `ink`. En el raíl se añade una barra de 3.5 px de `accent` en el borde izquierdo (pintada en `RailButton`) y el icono pasa a `accent`.
- **focus (teclado): borde de 2 px `accent`, siempre visible. Nunca se usa `outline: none`.** Al abrir la ventana no hay ningún control con foco visible; aparece al pulsar Tab.
- disabled: texto e icono `inkdisabled`, sin hover.
- El primario usa fondo `accent` y texto `onaccent`; su foco usa un borde `ink`.

## 7. Componentes y hooks (`setObjectName`)
| objectName | Descripción |
|---|---|
| `AppWindow` | Ventana principal |
| `MainToolbar` | Barra superior: abrir, guardar, imprimir, deshacer, rehacer, navegador de páginas, zoom, buscador |
| `Pill` | Grupo redondeado de controles relacionados (navegador de páginas, zoom) |
| `SearchField` | Buscador con lupa inicial (clic o Intro busca) |
| `ToolRail` | Raíl izquierdo (`QScrollArea`); propiedad `compact` cuando es de solo iconos |
| `ModeButton` / `DocButton` | Filas del raíl (clase `RailButton`); `ModeButton` es checkable |
| `DocButton` (grupo Herramientas) | Encabezado y pie, Bates, buscar y censurar, optimizar, aplanar, etiquetas, insertar página, sellos, comprobar y comparar texto; el raíl se desplaza si la ventana es baja |
| `RailToggle` | Contrae o expande el raíl (Ctrl+B) |
| `TextOptions` | Formato de texto contextual; si el raíl está compacto lo expande en esa sesión |
| `DocumentArea` | Vista del documento (fondo canvas, página con sombra suave pintada en `PageView.drawBackground`) |
| `PagesPanel`, `PagesHeader`, `CollapseButton` | Panel derecho plegable |
| `ThumbnailList` | Miniaturas pintadas por `ThumbnailDelegate`: sombra, número de página y contorno `accent` al seleccionar |
| `WelcomeView`, `WelcomeCard`, `DropZone`, `RecentList` | Pantalla de bienvenida; `RecentList` usa `RecentDelegate` (icono de archivo, nombre y carpeta) |

## 8. Pantallas
- **Bienvenida:** tarjeta centrada de 600 px como máximo con el icono de la aplicación, título, frase corta, «Abrir PDF» (primario), «Crear documento en blanco» (secundario), zona de arrastre y la lista de recientes cuando hay archivos. Se desplaza si la ventana es baja.
- **Espacio de trabajo:** `ToolRail` | `DocumentArea` | `PagesPanel`. A 1024x768 el raíl sigue expandido y el panel derecho en 210. El raíl se desplaza si no caben todas las herramientas.
- **Menú Ver:** ajustar a anchura, buscar, raíl compacto (Ctrl+B), panel de páginas (Ctrl+Mayús+B) y Tema (Sistema, Claro, Oscuro).

## 9. Tema
- `theme.apply_theme(app, modo)` resuelve `system` con `QStyleHints.colorScheme()`, fija el esquema de Qt (barra de título oscura en Windows), instala paleta y QSS y reinicia los iconos. Se vuelve a aplicar cuando el sistema cambia de esquema y el modo es `system`.
- La elección se guarda en `QSettings` (`theme`: `system`, `light`, `dark`); por defecto `system`.
- Las flechas de los spin y combos son PNG generados por tema en la carpeta temporal (`write_assets`), porque QSS no dibuja flechas sin imagen.

## 10. Accesibilidad y alta densidad
- Todo es accesible con teclado en orden lógico: barra superior, raíl, documento, panel. Los recientes se abren con Intro.
- Cada icono-botón lleva `toolTip` y `accessibleName` en español; los atajos aparecen en el tooltip.
- Iconos vectoriales con varias resoluciones; se prueba a 100, 125, 150 y 200 %.
- Las miniaturas y los iconos se pintan con el `devicePixelRatio` de la pantalla.
- Textos en español neutro y ninguna cadena incrustada en imágenes.

## 11. Reglas
- Hacer: un único acento, tokens en lugar de hex sueltos, cambios de estado por superficie y borde, foco siempre visible.
- No hacer: sombras largas, degradados, emojis, colores decorativos, texto menor de 8.5 pt ni «equivalente a Acrobat» en la interfaz.
