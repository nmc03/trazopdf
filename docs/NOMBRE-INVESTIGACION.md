# Investigación de nombre: lector/editor PDF (AGPL-3.0, Windows)

Fecha: 2026-11-09. Hay red. Partida: lista de Codex (verificada de nuevo aquí, sin fiarse del log).
Comandos: COM = `curl -s -o /dev/null -w %{http_code} https://rdap.verisign.com/com/v1/domain/<n>.com`;
ES = `dig +short NS <n>.es` y `dig <n>.es SOA` (estado); GH = `gh api "search/repositories?q=<n>+in:name"`;
PyPI/npm/crates = HTTP a pypi.org/pypi/<n>/json, registry.npmjs.org/<n>, crates.io/api/v1/crates/<n>;
Choco = community.chocolatey.org/packages/<n>; Flathub = flathub.org/api/v2/appstream/<n>.

## Tabla resumen (todos con sufijo "pdf" salvo linedra)
| Nombre | .com | .es | GitHub/paquetes | Web | Marcas | Nota |
|---|---|---|---|---|---|---|
| trazopdf | 404 (libre) | NS vacío, NXDOMAIN (probable libre, no concluyente) | GH 0; PyPI/npm/crates/Choco/Flathub 404 | Sin producto exacto. Cercanos: "Trazo Studio" (app iOS de plantillas PDF de dibujo, mwm.ai/apps/trazo-studio/6773057678), "Trazo" (IA de arte, sourceforge.net/app/trazo/web-app/) | NO comprobado | "Trazo" = trazo/línea (es, pt); fácil; riesgo medio por nombres "Trazo" en otros sectores |
| plicapdf | 404 | NXDOMAIN | GH 0; resto 404 | Búsqueda "PlicaPDF"/"Plica PDF": sin resultados | NO comprobado | "Plica" = pliegue (lat.), "plica" en es: sobre sellado (concursos); 3 sílabas; también término médico (plica polonica) y mala asociación leve |
| heronpdf | 404 | NXDOMAIN | GH 0; resto 404 | Sin producto "HeronPDF". Conflicto cercano: Heron Data (docs.herondata.io), procesado de documentos/extractos PDF para finanzas; y una herramienta web "Heron PDF to Text" (wildandfreetools.com/blog/pdf-to-text-for-developers-browser-free/) | NO comprobado | Garza (heron); significado claro en en, "garza" en es; PERO riesgo real de confusión con Heron Data (clase 42/35) |
| vitelapdf | 404 | NXDOMAIN | GH 0; resto 404 | Sin resultados exactos (cercano: VitaPDF, homebrew PS Vita, gamebrew.org) | NO comprobado | "Vitela" = vitela/vellum (es, pt "vitela" también ternera joven): pergamino fino, sentido bueno para es; en en suena oscuro |
| glosapdf | 404 | NXDOMAIN | GH 0; resto 404 | Sin resultados | NO comprobado | "Glosa" = anotación al margen (es, pt, gl); muy apropiado para anotar PDFs; "Glosa" es también un idioma construido (Glosa, 1972), conflicto menor |
| foliolopdf | 404 | NXDOMAIN | GH 0; resto 404 | Sin resultados | NO comprobado | "foliolo" = hojuela (botánica), poco conocido, 4 sílabas |
| tirajepdf | 404 | NXDOMAIN | GH 0; resto 404 | No buscado en profundidad | NO comprobado | "tiraje" = tirada impresa; (in)significado en en/fr |
| virgulapdf | 404 | NXDOMAIN | GH 0; resto 404 | No buscado en profundidad | NO comprobado | "vírgula" = coma/marca; sin gancho |
| escoliopdf | 404 | NXDOMAIN | GH 0; resto 404 | Una búsqueda conjunta, sin resultados | NO comprobado | "escolio" = nota marginal; culto, difícil |
| calamopdf | 404 | NXDOMAIN | GH 1: motthz/CalamoPDF (repo con ese nombre) | Una búsqueda conjunta, sin resultados | NO comprobado | Conflicto de repo GitHub |
| renglinapdf | 404 | NXDOMAIN | GH 0; resto 404 | No buscado | NO comprobado | Inventado, 4 sílabas |
| folivrapdf | 404 | NXDOMAIN | GH 0; resto 404 | No buscado | NO comprobado | Inventado, sin significado |
| linedra | 404 (linedra.com) | NXDOMAIN | GH 233 repos con "linedra" en nombre/ruido por coincidencia parcial; PyPI/npm/crates 404 | No buscado | NO comprobado | Sin "PDF" ni significado claro |
| pliegopdf | 200 (OCUPADO) | NXDOMAIN | GH 0 | - | - | Descartado: pliegopdf.com registrado |
| velinpdf | 200 (OCUPADO) | NXDOMAIN | GH 0 | - | - | Descartado: velinpdf.com registrado |

Choco/Flathub 404 para todos (excepto no aplicable a los dos ocupados). winget y Microsoft Store: NO comprobados.

## Recomendación (orden)
1. **TrazoPDF**: palabra real en es/pt, pronunciable en en, 3 sílabas; sin producto PDF homónimo hallado; dominios y paquetes libres.
2. **GlosaPDF**: significado perfecto (anotar/comentar), corto y sonoro; único matiz es el idioma Glosa, sin riesgo comercial evidente.
3. **PlicaPDF**: evoca pliegue/documento, pronunciable en es/en; connotación médica menor.
4. **VitelaPDF**: evoca pergamino; más literario, menos claro en inglés.
5. **HeronPDF** (solo si se acepta riesgo): marca atractiva pero Heron Data opera en procesado de documentos PDF; no recomendado sin revisión de marcas.

## NO se pudo comprobar
- Marcas (TMview, USPTO, WIPO, OEPM): los portales respondieron HTTP 200 pero son aplicaciones JS sin API consultable por curl; la sede OEPM dio 404 en la URL probada. Pendiente de consulta manual, clases 9, 42, 35, para al menos TrazoPDF, GlosaPDF, PlicaPDF.
- .es: solo DNS (NXDOMAIN/NS vacío) sin consulta WHOIS/Red.es; es indicio, no confirmación. Verificar en un registrador antes de comprar.
- winget, Microsoft Store, Product Hunt, AlternativeTo, Crunchbase, LinkedIn: no consultados directamente; web search (US) solo vía buscador, con pocas consultas por candidato (2-3 para los 5 primeros; 0-1 para el resto).
- Connotaciones en fr/de: por inferencia propia, sin fuente; en pt coinciden "trazo", "glosa", "vitela".

## Descartados por conflicto
- pliegopdf: pliegopdf.com ya registrado (RDAP 200).
- velinpdf: velinpdf.com ya registrado (RDAP 200).
- calamopdf: repo github.com/motthz/CalamoPDF.
- heronpdf (parcial, no descartado): Heron Data, https://docs.herondata.io/integrations/bank-statements
