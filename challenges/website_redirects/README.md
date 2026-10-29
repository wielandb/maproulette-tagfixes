# Permanente Website-Weiterleitungen prüfen

Dieser Generator erstellt deutsche MapRoulette-TagFix-Aufgaben für `website`
und `contact:website` an Nodes, Ways und Relationen. Er schlägt ausschließlich
die vom Server bestätigte neue URL vor. Eine Aufgabe bündelt alle bestätigten
Schlüssel desselben Objekts. Es werden keine Websites gesucht, keine fehlenden
Tags ergänzt und keine Links gelöscht.

## HTTP-Regeln und manuelle Prüfung

Zulässig sind vollständige Ketten aus ausschließlich **301/308** mit höchstens
zehn Weiterleitungen und abschließendem **200**. Das schließt HTTPS-, www- und
Slash-Umleitungen sowie Wechsel zu anderen Domains ein. Relative `Location`-
Angaben werden aufgelöst; Queryparameter und Fragmente bleiben erhalten, soweit
die tatsächliche Weiterleitung sie nicht ersetzt. Fehlt im Weiterleitungsziel
ein Fragment, wird das vorherige Fragment gemäß RFC 9110 übernommen. Ein
explizit leeres `#` entfernt es. Die HTTP-Anfrage selbst enthält kein Fragment.

Temporäre oder gemischte Ketten (302/303/307), Schleifen, fehlende/ungültige
`Location` und nicht eindeutige Antworten ergeben keine Aufgabe. Auch eine
permanente HTTPS→HTTP-Umleitung ist enthalten; der Task hebt das HTTP-Ziel
ausdrücklich hervor, damit Mapper die Website und URL prüfen können.
`rel=canonical`, Meta-Refresh und JavaScript-Weiterleitungen werden nicht
interpretiert. Nur einzelne absolute HTTP(S)-URLs werden geprüft; unsaubere
Tagwerte werden nicht stillschweigend repariert oder in URL-Listen zerlegt.
Nicht öffentliche Zieladressen und URLs mit Zugangsdaten werden abgelehnt.

**Eine permanente Weiterleitung beweist nicht, dass die Zielseite noch zum
OSM-Objekt gehört.** Die Aufgabe zeigt vorherige und vorgeschlagene URL, die
HTTP-Kette, UTC-Prüfzeit, gegebenenfalls den Seitentitel sowie Namen und Adresse
des aktuellen OSM-Objekts. Hostnamewechsel und der Verlust eines Unterseitenpfads
zugunsten der Startseite werden hervorgehoben. Mapper müssen Betreiber und
Standort prüfen und ungeeignete Vorschläge verwerfen, etwa Domainparking,
Anmeldeseiten, fremde Geschäfte oder eine Konzernseite statt einer Filialseite.

Die HTTP-Bedeutung ist in [RFC 9110, 301](https://www.rfc-editor.org/rfc/rfc9110.html#name-301-moved-permanently),
[308](https://www.rfc-editor.org/rfc/rfc9110.html#name-308-permanent-redirect)
und [Location/Fragmente](https://www.rfc-editor.org/rfc/rfc9110.html#name-location)
beschrieben.

## Ausführen

Abhängigkeiten aus dem Repository-Stamm installieren:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Standardmäßig wird der aktuelle Deutschland-Extrakt von Geofabrik nach
`challenges/website_redirects/.cache/germany-latest.osm.pbf` gestreamt und mit
pyosmium nach Website-Tags durchsucht. Das kann einen großen Download und
viele HTTP-Abrufe bedeuten. Eine vorhandene, nicht leere Download-Datei wird
höchstens 24 Stunden ab Download wiederverwendet und beim nächsten Lauf danach
atomar erneuert. Schlägt die Erneuerung fehl, wird die alte Datei nicht als
Ersatz verwendet. Der Standardumfang entspricht dem Deutschland-Extrakt,
einschließlich dessen Randobjekten. Ein explizit übergebener Extrakt wird
unverändert benutzt; sein geografischer Umfang und seine Aktualität liegen beim
Aufrufer.

```powershell
.\.venv\Scripts\python.exe challenges/website_redirects/generate.py
.\.venv\Scripts\python.exe challenges/website_redirects/generate.py --pbf C:\osm\germany-latest.osm.pbf --cache-dir .venv/website-cache
```

Für kleine echte Probeläufe wählt `--bbox` die Kandidaten über Overpass aus.
`--pbf` und `--bbox` schließen sich gegenseitig aus. Die Bounding Box ersetzt
den Deutschland-Standard und kann eine beliebige Region eingrenzen.

```powershell
.\.venv\Scripts\python.exe challenges/website_redirects/generate.py --bbox 52.51 13.37 52.53 13.40 --max-tasks 3 --output .venv/website-sample.json --cache-dir .venv/website-cache
```

Weitere Optionen: `--output PATH`, `--max-tasks N` und `--workers 1..4`.
Die Standardausgabe ist `challenges/website_redirects/website_redirects.json`.
Relative CLI-Pfade beziehen sich auf das aktuelle Arbeitsverzeichnis, die
Standardpfade auf den Skriptordner. Die Ausgabe ist eine JSON-Sequenz aus
MapRoulette-Aufgaben, keine gewöhnliche JSON-Liste. `website_redirects.json`
ist bewusst versionierbar; im PR wird kein künstlicher Beispieldatensatz
angelegt.

## Datenfluss, Cache und Grenzen

Der PBF-Scan liest nur IDs und Website-Tags und benötigt keinen Geometrieindex.
Gleiche URLs werden innerhalb eines Batches und über einen SQLite-Cache
dedupliziert. Eindeutige Ergebnisse werden höchstens 24 Stunden gespeichert;
Transportfehler, Zugriffssperren und temporäre Serverfehler werden nicht als
negative Ergebnisse dauerhaft gespeichert. Erst für bestätigte Redirect-
Kandidaten holt der Generator aktuelle Tags und Kartenpositionen über Overpass
in Batches von höchstens 100 Objekten. Ein Tag wird nur dann vorgeschlagen,
wenn sein aktueller Wert exakt dem geprüften Ausgangswert entspricht.

Es laufen höchstens vier HTTP-Worker mit mindestens einer Sekunde Abstand
zwischen Anfragen an denselben Host und festen Connect-/Read-Timeouts von
10/20 Sekunden. `Retry-After` wird als Sekundenwert oder HTTP-Datum beachtet,
auch vor einem Redirect auf einen anderen Host. Bei mehr als 60 Sekunden
Wartezeit wird der Host für diesen Lauf zurückgestellt. Jede URL-Prüfung ist
auf zehn Redirects und einen kurzen Titel-Ausschnitt begrenzt. Der Prüfer
verwendet weder Browser-Cookies noch Zugangsdaten aus `.netrc`.

Einzelne unklare Websites werden übersprungen. Wenn sämtliche neuen Prüfungen
am Netzwerk oder an uneindeutigen Sperr-/Serverantworten scheitern, bricht der
Lauf ab. Ebenso führen Fehler bei PBF, Overpass oder Ausgabe zum Fehlerstatus;
die bisherige Challenge-Ausgabe bleibt erhalten. Ein erfolgreicher Lauf ohne
Treffer schreibt eine leere JSON-Sequenz. Cache-Dateien werden ignoriert und
gehören nicht zum Challenge-Datensatz.

Die gemeinsame `Challenge`-Klasse begrenzt die Ausgabe auf 50.000 Aufgaben und
99.000.000 Byte. `--max-tasks` kann diese Grenze verkleinern. Kandidaten und
HTTP-Prüfungen werden in Batches von 32 Objekten vorbereitet; nach Erreichen
einer Ausgabegrenze werden keine weiteren Batches oder Aufgaben bearbeitet.

Beim MapRoulette-Import **OSM/External ID Property** auf `task_id` setzen und als
Aufgabenbeschreibung `{{task_instruction}}` verwenden. Der Generator lädt keine
Änderungen in OSM oder MapRoulette hoch.

## Tests und manueller GitHub-Lauf

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_website_redirects.py -v
```

Der Workflow `update_website_redirects.yml` startet ausschließlich manuell.
Er prüft den Generator, erzeugt echte Daten und committet nur
`challenges/website_redirects/website_redirects.json`. Optional begrenzt eine
Bounding Box den Lauf. Der Workflow hat keinen Zeitplan. Für die lokale
Sammelaktualisierung ist der Generator in `update_all_challenges.bat` enthalten.


## Enthaltene erste Live-Probe

Die eingecheckte JSON-Sequenz enthält **eine echte Aufgabe**, keinen
Deutschland-Gesamtexport. Am **29.10.2026** wurden zwölf verschiedene Website-
URLs aus einer Dresdner Kandidatenprobe (BBox `50.95 13.60 51.12 13.90`) geprüft.
Die OSM-Objekte wurden vorher frisch über die OSM-API revalidiert. Eine
Weiterleitung war vollständig permanent: `node/309018405`, Pizzeria Toscana,
Louisenstraße 34, auf die neue Eatbu-Seite; der Zielseitentitel bestätigt den
Bezug zu Dresden. Acht URLs hatten keine Weiterleitung, zwei nur temporäre
Weiterleitungen und eine lieferte HTTP 404. Diese elf Fälle erzeugten keine
Änderungsvorschläge.

Die Live-Probe prüft HTTP, Aufgabe und TagFix-Ausgabe mit echten Daten. Eine
vollständige Live-Ausführung der Overpass-Kandidatensuche und der anschließenden
Overpass-Abfrage aktueller Objekte war wegen nicht verfügbarer aktueller
Overpass-Daten nicht möglich. Diese Abfragen sind offline mit kontrollierten
Antworten getestet. Die erste Probe ersetzt weder einen deutschlandweiten Lauf
noch die manuelle Prüfung durch den Mapper.
