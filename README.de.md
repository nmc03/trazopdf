# TrazoPDF

[Español](README.md) · [English](README.en.md) · [Français](README.fr.md) · **Deutsch** · [Português](README.pt.md)

Kostenloser und quelloffener PDF-Editor für Windows. Er dient den üblichen Aufgaben mit PDF-Dateien – lesen, suchen, anmerken, Formulare ausfüllen, zusammenführen, teilen, schwärzen oder konvertieren – ohne die Dokumente an einen Online-Dienst zu senden.

Er ist eine schlanke Alternative für den alltäglichen Einsatz von Adobe Acrobat. Er will nicht alle Funktionen ersetzen: Cloud-Dienste, Abläufe zum Versand von Signaturen und einige Spezialfunktionen fehlen. Die konkreten Grenzen jeder Funktion stehen in [docs/FEATURES.md](docs/FEATURES.md).

![TrazoPDF mit hellem Design](docs/screenshots/editor-light.png)

![TrazoPDF mit dunklem Design](docs/screenshots/editor-dark.png)

## Hauptfunktionen

- Lesen mit Zoom, Einzel-, Doppelseiten- und fortlaufender Ansicht, Suche und Ersetzen von Text sowie Lesezeichen.
- Textauswahl nach Zeichen, Wörtern und Zeilen, mit Kopieren.
- Bearbeiten von Text und Blöcken bestehender PDF-Inhalte sowie direktes Schreiben auf die Seite.
- Bilder: auswählen, verschieben, skalieren, ersetzen und löschen.
- Anmerkungen: Hervorheben, Unterstreichen, Durchstreichen, Notizen mit Antworten und Status, Formen, Linien, Pfeile, Textfelder und Freihand-Tinte.
- Web-, E-Mail- und interne Seitenlinks.
- Seiten: anordnen, löschen, duplizieren, zusammenführen, teilen, extrahieren, zuschneiden und drehen.
- AcroForm-Formulare: Felder erstellen und direkt auf der Seite ausfüllen.
- Angewendete Schwärzung, Suche nach vertraulichen Daten zum Schwärzen, Metadaten, Anhänge und Bereinigung des Dokuments.
- Dokument anonymisieren (Sicherheit): erkennt personenbezogene Daten, erstellt eine neue Kopie, prüft sie und liefert einen Bericht.
- Kopf- und Fußzeilen, Bates-Nummerierung, Stempel, Seitenbezeichnungen, Reduzierung, Optimierung der Dateigröße, Dokumentprüfung und Textvergleich.
- Kennwörter und Verschlüsselung mit AES-256.
- Digitale Signatur mit eigenem Zertifikat im Format PKCS#12, unsichtbar oder mit sichtbarem Erscheinungsbild, mit mehreren Signaturen und lokaler Prüfung (ohne Sperrprüfung; keine qualifizierte elektronische Signatur nach eIDAS).
- OCR für Scans ist im Programm enthalten, ohne Installation: Spanisch, Englisch, Französisch, Deutsch und Portugiesisch, mit Geradeausrichtung und Erkennung der Ausrichtung.
- Stapelverarbeitung mit Rezepten, auch über die Befehlszeile.
- Umwandlung von Office in PDF mit LibreOffice sowie Export von PDF nach DOCX, XLSX und PPTX.
- Visueller Vergleich zweier PDF mit Bericht als ZIP.
- Rückgängig und Wiederholen während der Sitzung.
- Mehrere PDF in Registerkarten, mit automatischem Speichern und Wiederherstellung nicht gespeicherter Änderungen, optionaler `.bak`-Kopie, Kopie speichern und Zurücksetzen.
- Entfernungsmessung, optionale Ebenen und geführte Aktionen für häufige Aufgaben.
- Tastenkürzel über `F1` einsehbar; zum Beispiel `F` für Ausfüllen und signieren und `K` für Feld erstellen.
- Oberfläche auf Spanisch, Englisch, Französisch, Deutsch und Portugiesisch (Hilfe > Sprache, oder die Systemsprache).

Das vollständige Benutzerhandbuch steht in [docs/manual/de.md](docs/manual/de.md).

Siehe [docs/FEATURES.md](docs/FEATURES.md) für Umfang und Grenzen jedes Bereichs. Die Änderungen jeder Version stehen im [CHANGELOG](CHANGELOG.md).

## Stapelverarbeitung

**Werkzeuge > Mehrere PDFs verarbeiten…** wendet ein Rezept (eine geordnete Liste von Schritten) auf mehrere Dateien an, ohne die Originale zu verändern. Verfügbare Schritte: anonymisieren, OCR, optimieren, Metadaten und verborgene Inhalte bereinigen, Wasserzeichen, Seiten nummerieren, Bates-Nummerierung, drehen, Ränder zuschneiden, mit Zertifikat signieren und Text exportieren. Rezepte lassen sich speichern, importieren und als `.json` exportieren. Es gibt drei vordefinierte Rezepte: *Anonymisieren und archivieren*, *Scan zu durchsuchbarem PDF* und *Verkleinern und bereinigen*.

Auch ohne Fenster nutzbar, zum Beispiel um einen Scanner zu automatisieren:

```
"TrazoPDF.exe" --batch receta.json --in C:\Escaneos --out C:\Salida --recursive --on-conflict renombrar
"TrazoPDF.exe" --watch C:\Entrada --recipe receta.json --out C:\Salida
```

`--on-conflict` akzeptiert `renombrar` (Standard), `omitir` und `sobrescribir`; `--interval` legt die Sekunden zwischen den Prüfungen von `--watch` fest (Standard 5). Der Exitcode ist 0, wenn alles gut gelaufen ist, 1, wenn eine Datei fehlgeschlagen ist, und 2, wenn die Verwendung falsch ist. Der Bericht wird ausgegeben und als `batch-report.json` im Ausgabeordner gespeichert. Signiert das Rezept mit einem Zertifikat, wird das Kennwort aus der Umgebungsvariablen `PDFEDITOR_SIGN_PASSWORD` gelesen. Die Details stehen im [Handbuch](docs/manual/de.md#stapelverarbeitung-und-rezepte).

## Herunterladen und installieren

Veröffentlichte Versionen stehen auf der Seite [Releases](../../releases). Es gibt zwei Möglichkeiten zur Installation:

- **Installer** (`TrazoPDF-x.y.z-setup.exe`): installiert für den eigenen Benutzer, ohne Administratorrechte. Man kann auch für alle Benutzer des Computers installieren. Legt die Verknüpfung im Startmenü an und, wenn angekreuzt, auf dem Desktop. Trägt die Anwendung unter „Öffnen mit“ für PDF-Dateien ein, ohne das Standardprogramm zu ändern.
- **Portabler Ordner** (`TrazoPDF-x.y.z-windows.zip`): Datei entpacken und `TrazoPDF.exe` ausführen. Keine Installation nötig.

Die Integrität der heruntergeladenen Datei mit der Datei `SHA256SUMS.txt` derselben Version prüfen.

Voraussetzungen: Windows 10 oder 11, 64 Bit.

> **Nicht signiert.** Der Installer und das Programm sind nicht mit einem Codesignatur-Zertifikat signiert. Deshalb kann Windows SmartScreen vor einem „unbekannten Herausgeber“ warnen. Bei einem Download von der offiziellen Releases-Seite „Weitere Informationen“ und danach „Trotzdem ausführen“ wählen; vorher die Prüfsumme mit `SHA256SUMS.txt` kontrollieren.

## Aus dem Quellcode erstellen

Man braucht Python 3.13 für Windows.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pdf_editor
```

Zum Erzeugen des Anwendungsordners:

```powershell
.\build.ps1
```

Die Ausgabe liegt in `dist\TrazoPDF\`, mit `TrazoPDF.exe` und einer Datei `SHA256SUMS.txt` neben dem Ordner. Für das Installationsprogramm wird [Inno Setup 6](https://jrsoftware.org/isinfo.php) benötigt:

```powershell
.\installer\build-installer.ps1
```

Das Skript sucht `ISCC.exe` in der Installation von Inno Setup. Wird es dort nicht gefunden, kann der Pfad über die Umgebungsvariable `INNO_SETUP_ISCC` angegeben werden. Das Installationsprogramm wird in `installer\Output\` erstellt.

Die Tests laufen ohne sichtbare Fenster:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

## Optionale externe Abhängigkeiten

- **LibreOffice** (nicht enthalten): Umwandlung von Office-Dokumenten in PDF. Nur für diese Funktion nötig. Download: https://www.libreoffice.org/
- **Tesseract OCR**: In der installierten und in der portablen Version ist es nicht mehr nötig, da es mit den Modellen für Spanisch, Englisch, Französisch, Deutsch und Portugiesisch enthalten ist. Nur beim Ausführen aus dem Quellcode muss es installiert und auffindbar sein (die zusätzlichen Modelle werden mit `tools/fetch_tessdata.ps1` heruntergeladen). Download: https://github.com/UB-Mannheim/tesseract/wiki

## Tastenkürzel

| Tastenkürzel | Aktion |
| --- | --- |
| `Strg+O` | Öffnen |
| `Strg+S` | Speichern |
| `Strg+Umschalt+S` | Speichern unter |
| `Strg+Z` | Rückgängig |
| `Strg+Umschalt+Z` | Wiederholen |
| `Strg+Y` | Wiederholen |
| `Strg+A` | Alles auswählen (Miniaturen oder Text, je nach Fokus) |
| `Strg+Tab` / `Strg+Umschalt+Tab` | Zwischen Dokument-Registerkarten wechseln |
| `Alt+1` bis `Alt+9` | Zur angegebenen Registerkarte wechseln |
| `Strg+W` | Aktuelles Dokument schließen |
| `F1` | Tastenkürzel (Hilfe) |
| `Strg+E` | PDF bearbeiten |
| `Strg+F` | Suchen |
| `F3` / `Umschalt+F3` | Nächster / vorheriger Treffer |
| `Strg+R` | Drehen |
| `Strg+P` | Drucken |
| `Strg+C` | Ausgewählten Text kopieren |
| `Strg+Eingabe` | Den gerade eingegebenen Text übernehmen |
| `Esc` | Die laufende Eingabe abbrechen |
| `F2` | Den ausgewählten Block bearbeiten |
| `Entf` | Das ausgewählte Element löschen |
| `Strg` + Mausrad | Zoom ändern |

## Datenschutz

TrazoPDF arbeitet auf dem eigenen Computer. Es gibt keine Konten, keine Telemetrie und keine Prüfung auf Updates, und Dokumente werden nirgendwo hochgeladen. Die einzige Netzwerkverbindung entsteht, wenn ein Link geöffnet wird, den man selbst anklickt. Details stehen in [PRIVACY.md](PRIVACY.md).

## Lizenz

TrazoPDF wird unter der [GNU Affero General Public License v3.0 oder später](LICENSE) (AGPL-3.0-or-later) verbreitet. Diese Lizenz ist nötig, weil PyMuPDF, eine seiner Bibliotheken, unter AGPL-3.0 steht. Die Lizenzen der anderen Bibliotheken stehen in [THIRD-PARTY.md](THIRD-PARTY.md).

Es handelt sich um eine eigenständige Implementierung. Sie enthält keinen Code, keine Oberfläche und keine grafischen Ressourcen von Adobe.

## Mitwirken

Beiträge sind willkommen. Vorher [CONTRIBUTING.md](CONTRIBUTING.md) und den [Verhaltenskodex](CODE_OF_CONDUCT.md) lesen. Eine Sicherheitslücke meldet man gemäß [SECURITY.md](SECURITY.md).
