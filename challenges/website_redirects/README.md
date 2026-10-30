# Permanente Website-Weiterleitungen prüfen

Dieser Generator erstellt deutsche MapRoulette-TagFix-Aufgaben für `website`
und `contact:website` an Nodes, Ways und Relationen. Er schlägt ausschließlich
die vom Webserver bestätigte neue URL vor. Eine Aufgabe bündelt alle bestätigten
Schlüssel desselben Objekts. Es werden keine Websites gesucht, keine fehlenden
Tags ergänzt und keine Links gelöscht.

## Ausschließlich Geofabrik-PBF als OSM-Datenquelle

Standardmäßig lädt `shared/geofabrik.py` den Deutschland-Extrakt von Geofabrik
nach `.cache/geofabrik/germany-latest.osm.pbf` im Repository. Eine nicht leere
Datei wird höchstens 24 Stunden ab Download wiederverwendet. Danach wird die
alte automatisch geladene Datei gelöscht und eine neue Datei gestreamt. Bei
Fehlschlag gibt es keinen veralteten PBF-Fallback; die bisherige Aufgaben-JSON
bleibt erhalten. Mit `--pbf PATH` angegebene Dateien werden weder gelöscht noch
neu geladen. Ihr Umfang und ihre Aktualität liegen beim Aufrufer.

**Kandidaten, Tags und alle Displayzentren stammen aus demselben PBF-Snapshot.**
Es gibt keine Abfragen an Overpass oder die OSM-API. `--bbox SÜD WEST NORD OST`
filtert lokal nach dem berechneten Displayzentrum und kann mit `--pbf`
kombiniert werden. Der Deutschland-Standard umfasst auch Randobjekte des
Geofabrik-Extrakts.

Der gemeinsame Helper gibt passende Nodes bereits im ersten PBF-Pass aus.
Für Ways und Relationen sammelt er Tag-Kandidaten und nur deren benötigte
Referenzen in einer temporären SQLite-Datenbank. Weitere PBF-Pässe lösen die
benötigten Ways, verschachtelten Relationen und Node-Koordinaten lokal auf.
Es gibt keinen globalen All-Nodes-Koordinatenindex und keinen zweiten Download.
Die selektiven C++-ID-Filter benötigen RAM für die ausgewählten Referenz-IDs;
Tags, Referenzlisten und Koordinaten bleiben im temporären SQLite-Cache.
Fehlende Referenzen, Zyklen und Relationen mit mehr als acht Verschachtelungen
werden mit Diagnose übersprungen. Unvollständige Geometrien werden nicht durch
einen geratenen Mittelpunkt ersetzt. Temporäre Referenzdateien werden auch
beim frühen Erreichen einer Aufgabengrenze entfernt. Phasenmeldungen zeigen den
PBF-Stand und den Fortschritt der Referenzauflösung.

## HTTP-Regeln und manuelle Prüfung

Zulässig sind vollständige Ketten aus ausschließlich **301/308** mit höchstens
zehn Weiterleitungen und abschließendem **200**. Das schließt HTTPS-, www- und
Slash-Umleitungen, Domainwechsel und permanente HTTPS→HTTP-Umleitungen ein.
HTTP-Ziele anstelle vorheriger HTTPS-Adressen werden ausdrücklich markiert.
Relative `Location`-Angaben werden aufgelöst. Queryparameter und Fragmente
bleiben erhalten, soweit die tatsächliche Weiterleitung sie nicht ersetzt.
Fehlt im Ziel ein Fragment, wird das vorherige Fragment gemäß RFC 9110
übernommen; ein explizit leeres `#` entfernt es. Die HTTP-Anfrage selbst enthält
kein Fragment.

Temporäre oder gemischte Ketten (302/303/307), Schleifen, fehlende/ungültige
`Location` und uneindeutige Antworten ergeben keine Aufgabe. `rel=canonical`,
Meta-Refresh und JavaScript werden nicht interpretiert. Nur einzelne absolute
HTTP(S)-URLs werden geprüft. Nicht öffentliche Zieladressen und URLs mit
Zugangsdaten werden abgelehnt; unsaubere Tagwerte werden nicht still repariert.

**Eine permanente Weiterleitung beweist nicht die Identität des Ziels.**
Die Aufgabe zeigt vorherige und vorgeschlagene URL, HTTP-Kette, UTC-Prüfzeit,
gegebenenfalls Seitentitel sowie Namen und Adresse aus dem PBF. Hostnamewechsel
und der Verlust eines Unterseitenpfads zugunsten der Startseite sind markiert.
Die Anleitung nennt außerdem den PBF-Stand aus dem Header und fordert zur
Prüfung der aktuellen OSM-Tags auf. Zwischenzeitliche Mapper-Änderungen dürfen
nicht überschrieben werden. Betreiber und Standort müssen weiterhin passen;
Domainparking, Anmeldeseiten, fremde Geschäfte oder eine ungeeignete
Konzernstartseite sind Gründe, den Vorschlag nicht zu übernehmen.

Bei unbekannten Zeichensatzangaben wie `utf-8mb4` wird der optionale Seitentitel
mit UTF-8 gelesen; ungültige Bytes werden durch Ersatzzeichen dargestellt.
Dadurch bleibt eine bestätigte Weiterleitung auch bei falschen Charset-Namen
des Webservers auswertbar.

Die HTTP-Bedeutung ist in [RFC 9110, 301](https://www.rfc-editor.org/rfc/rfc9110.html#name-301-moved-permanently),
[308](https://www.rfc-editor.org/rfc/rfc9110.html#name-308-permanent-redirect)
und [Location/Fragmente](https://www.rfc-editor.org/rfc/rfc9110.html#name-location)
beschrieben.

## Ausführen

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe challenges/website_redirects/generate.py
.\.venv\Scripts\python.exe challenges/website_redirects/generate.py --pbf C:\osm\germany-latest.osm.pbf --cache-dir .venv/geofabrik-cache
.\.venv\Scripts\python.exe challenges/website_redirects/generate.py --pbf C:\osm\germany-latest.osm.pbf --bbox 50.95 13.60 51.12 13.90 --max-tasks 3 --output .venv/website-sample.json
```

Weitere Optionen: `--output PATH`, `--max-tasks N`, `--workers 1..4` und
`--cache-dir PATH`. Die Standardausgabe ist
`challenges/website_redirects/website_redirects.json`. Relative CLI-Pfade
beziehen sich auf das aktuelle Arbeitsverzeichnis, Standardpfade auf das
Repository beziehungsweise den Skriptordner. Die Ausgabe ist eine JSON-Sequenz,
keine gewöhnliche JSON-Liste. Die Aufgaben-JSON ist bewusst versionierbar;
PBF-Dateien und der Standardcache werden ignoriert.

## HTTP-Cache, Fehler und Grenzen

Identische URLs werden innerhalb eines Batches und über einen SQLite-Cache
dedupliziert. Eindeutige Ergebnisse werden höchstens 24 Stunden gespeichert;
Transportfehler, Zugriffssperren und temporäre Serverfehler werden nicht als
negative Ergebnisse dauerhaft gespeichert. Erst nach der HTTP-Prüfung werden
Tasks aus den ursprünglichen PBF-Daten gebaut. Eine automatische Revalidierung
gegen den aktuellen OSM-Datenbestand findet nicht statt.

Höchstens vier HTTP-Worker halten mindestens eine Sekunde Abstand je Host ein.
Connect-/Read-Timeouts betragen 10/20 Sekunden. `Retry-After` als Sekundenwert
oder HTTP-Datum gilt auch beim Wechsel zu einem anderen Host und für bereits
wartende Worker. Mehr als 60 Sekunden Wartezeit stellen den Host für diesen
Lauf zurück. Der Prüfer verwendet weder Browser-Cookies noch `.netrc`-Zugangsdaten.

Einzelne unklare Websites werden übersprungen. Wenn sämtliche neuen Prüfungen
am Netzwerk oder an uneindeutigen Sperr-/Serverantworten scheitern, bricht der
Lauf ab. PBF- und Ausgabefehler führen ebenfalls zum Fehlerstatus und erhalten
die bisherige Aufgaben-JSON. Ein erfolgreicher Lauf ohne Treffer schreibt eine
leere JSON-Sequenz.

Die gemeinsame `Challenge`-Klasse begrenzt die Ausgabe auf 50.000 Aufgaben und
99.000.000 Byte. `--max-tasks` kann die Grenze verkleinern. Nodes werden im
ersten Pass direkt ausgegeben; nur Ways und Relationen benötigen zusätzliche
Referenzpässe. Ein frühes Aufgabenlimit bei Nodes kann diese Pässe vollständig
vermeiden. HTTP-Prüfungen werden in Batches von 32 Objekten vorbereitet.
Nach Erreichen einer Ausgabegrenze werden keine weiteren Batches
oder Aufgaben bearbeitet.

Beim MapRoulette-Import **OSM/External ID Property** auf `task_id` setzen und als
Aufgabenbeschreibung `{{task_instruction}}` verwenden. Der Generator lädt keine
Änderungen in OSM oder MapRoulette hoch.

## Tests und manueller GitHub-Lauf

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_geofabrik.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_website_redirects.py -v
```

`update_website_redirects.yml` startet ausschließlich manuell, testet Quelle und
Generator und committet nur die eigene Aufgaben-JSON. Die optionale Bounding
Box ist ein lokaler PBF-Filter. Der Workflow hat keinen Zeitplan.
`update_all_challenges.bat` enthält den Generator ebenfalls.

## Echter Deutschland-PBF-Probelauf vom 29.10.2026

Die versionierte `website_redirects.json` stammt aus einem erfolgreichen echten
CLI-Lauf (Exitstatus **0**) mit dem vollständig heruntergeladenen Geofabrik-
Deutschland-Extrakt (**4.871.369.043 Byte**, PBF-Datenstand
**2026-10-28T21:21:02Z**). Die lokale Dresden-BBox war
`50.95 13.60 51.12 13.90`, das Aufgabenlimit 20.

```powershell
python challenges/website_redirects/generate.py --cache-dir .venv/geofabrik-cache --bbox 50.95 13.60 51.12 13.90 --max-tasks 20
```

Der Generator prüfte **128 PBF-Kandidaten** und erzeugte **20 Aufgaben**.
Kandidaten, Tags und Kartenpositionen kamen ausschließlich aus demselben PBF;
HTTP-Abrufe dienten ausschließlich der Website-Prüfung. Es gab weder Overpass-
noch OSM-API-Abfragen und keine gemockten Eingaben. Nodes wurden im ersten
Lesedurchgang ausgegeben; das Aufgabenlimit beendete den PBF-Iterator sauber.
Die JSON-Sequenz wurde auf eindeutige Objekt-IDs, gültige Koordinaten innerhalb
der BBox, PBF-Datenstand und TagFix-Operationen geprüft.

Die Treffer sind technisch bestätigte Weiterleitungen. Ihre inhaltliche
Zuordnung bleibt Teil der Aufgabe: Beispielsweise zeigte das Ziel der
16. Grundschule Josephine den Seitentitel „Turystyka“. Dieser auffällige
Treffer muss inhaltlich geprüft und gegebenenfalls abgelehnt werden; eine
permanente Weiterleitung allein bestätigt keine Schulwebsite. Die Datei ist
eine begrenzte Datenprobe und kein Deutschland-Gesamtexport.
