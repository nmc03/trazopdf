# Name research: PDF reader/editor (AGPL-3.0, Windows)

Date: 2026-11-09. Network access available. Starting point: Codex list (re-verified here, not relying on the log).
Commands: COM = `curl -s -o /dev/null -w %{http_code} https://rdap.verisign.com/com/v1/domain/<n>.com`;
ES = `dig +short NS <n>.es` and `dig <n>.es SOA` (status); GH = `gh api "search/repositories?q=<n>+in:name"`;
PyPI/npm/crates = HTTP to pypi.org/pypi/<n>/json, registry.npmjs.org/<n>, crates.io/api/v1/crates/<n>;
Choco = community.chocolatey.org/packages/<n>; Flathub = flathub.org/api/v2/appstream/<n>.

## Summary table (all with the "pdf" suffix except linedra)
| Name | .com | .es | GitHub/packages | Web | Trademarks | Note |
|---|---|---|---|---|---|---|
| trazopdf | 404 (free) | Empty NS, NXDOMAIN (probably free, not conclusive) | GH 0; PyPI/npm/crates/Choco/Flathub 404 | No exact product. Close matches: "Trazo Studio" (iOS app for PDF drawing templates, mwm.ai/apps/trazo-studio/6773057678), "Trazo" (art AI, sourceforge.net/app/trazo/web-app/) | NOT checked | "Trazo" = stroke/line (es, pt); easy; medium risk from "Trazo" names in other sectors |
| plicapdf | 404 | NXDOMAIN | GH 0; rest 404 | Search for "PlicaPDF"/"Plica PDF": no results | NOT checked | "Plica" = fold (Latin), "plica" in es: sealed envelope (contests); 3 syllables; also a medical term (plica polonica) and a slight negative association |
| heronpdf | 404 | NXDOMAIN | GH 0; rest 404 | No "HeronPDF" product. Close conflict: Heron Data (docs.herondata.io), PDF document/statement processing for finance; and a web tool "Heron PDF to Text" (wildandfreetools.com/blog/pdf-to-text-for-developers-browser-free/) | NOT checked | Heron (the bird); clear meaning in en; real risk of confusion with Heron Data (classes 42/35) |
| vitelapdf | 404 | NXDOMAIN | GH 0; rest 404 | No exact results (close: VitaPDF, PS Vita homebrew, gamebrew.org) | NOT checked | "Vitela" = vitela/vellum (es, pt "vitela" also young veal): fine parchment, good sense for es; sounds obscure in en |
| glosapdf | 404 | NXDOMAIN | GH 0; rest 404 | No results | NOT checked | "Glosa" = marginal annotation (es, pt, gl); very apt for annotating PDFs; "Glosa" is also a constructed language (Glosa, 1972), minor conflict |
| foliolopdf | 404 | NXDOMAIN | GH 0; rest 404 | No results | NOT checked | "foliolo" = leaflet (botany), little known, 4 syllables |
| tirajepdf | 404 | NXDOMAIN | GH 0; rest 404 | Not searched in depth | NOT checked | "tiraje" = print run; (no) meaning in en/fr |
| virgulapdf | 404 | NXDOMAIN | GH 0; rest 404 | Not searched in depth | NOT checked | "vírgula" = comma/mark; no hook |
| escoliopdf | 404 | NXDOMAIN | GH 0; rest 404 | One joint search, no results | NOT checked | "escolio" = marginal note; erudite, hard |
| calamopdf | 404 | NXDOMAIN | GH 1: motthz/CalamoPDF (repo with that name) | One joint search, no results | NOT checked | GitHub repo conflict |
| renglinapdf | 404 | NXDOMAIN | GH 0; rest 404 | Not searched | NOT checked | Invented, 4 syllables |
| folivrapdf | 404 | NXDOMAIN | GH 0; rest 404 | Not searched | NOT checked | Invented, no meaning |
| linedra | 404 (linedra.com) | NXDOMAIN | GH 233 repos with "linedra" in name/noise from partial matches; PyPI/npm/crates 404 | Not searched | NOT checked | No "PDF" and no clear meaning |
| pliegopdf | 200 (TAKEN) | NXDOMAIN | GH 0 | - | - | Discarded: pliegopdf.com registered |
| velinpdf | 200 (TAKEN) | NXDOMAIN | GH 0 | - | - | Discarded: velinpdf.com registered |

Choco/Flathub 404 for all (not applicable to the two taken ones). winget and Microsoft Store: NOT checked.

## Recommendation (in order)
1. **TrazoPDF**: a real word in es/pt, pronounceable in en, 3 syllables; no homonymous PDF product found; domains and packages free.
2. **GlosaPDF**: perfect meaning (annotate/comment), short and sonorous; the only nuance is the Glosa language, with no evident commercial risk.
3. **PlicaPDF**: evokes fold/document, pronounceable in es/en; minor medical connotation.
4. **VitelaPDF**: evokes parchment; more literary, less clear in English.
5. **HeronPDF** (only if the risk is accepted): attractive mark, but Heron Data operates in PDF document processing; not recommended without a trademark review.

## NOT verified
- Trademarks (TMview, USPTO, WIPO, OEPM): the portals responded with HTTP 200 but are JS applications with no API queryable via curl; the OEPM site returned 404 at the URL tried. Pending manual check, classes 9, 42, 35, for at least TrazoPDF, GlosaPDF, PlicaPDF.
- .es: DNS only (NXDOMAIN/empty NS), without WHOIS/Red.es lookup; it is an indication, not confirmation. Verify with a registrar before buying.
- winget, Microsoft Store, Product Hunt, AlternativeTo, Crunchbase, LinkedIn: not checked directly; web search (US) only via the search engine, with few queries per candidate (2-3 for the top 5; 0-1 for the rest).
- Connotations in fr/de: my own inference, no source; in pt, "trazo", "glosa" and "vitela" coincide.

## Discarded due to conflict
- pliegopdf: pliegopdf.com already registered (RDAP 200).
- velinpdf: velinpdf.com already registered (RDAP 200).
- calamopdf: repo github.com/motthz/CalamoPDF.
- heronpdf (partial, not discarded): Heron Data, https://docs.herondata.io/integrations/bank-statements
