# Soziale Werkstätten korrekt einordnen

Dieser Generator erstellt deutsche MapRoulette-TagFix-Aufgaben für ausdrücklich
als Werkstätten für Menschen mit Behinderungen beschriebene OSM-Objekte.
Die Datenbasis ist der [Deutschland-PBF von Geofabrik](https://download.geofabrik.de/europe/germany.html).
Kandidaten, vollständige Tags und Kartenpositionen für Nodes, Ways und Relations
werden lokal aus derselben Datei gelesen. Nodes können bereits im ersten
Lesedurchlauf ausgegeben werden; benötigte Way-/Relationsreferenzen werden
selektiv lokal aufgelöst.

## Erkennung und vorgeschlagene Änderungen

Als Beleg dienen `name`, `description` und `description:de`. Erkannt werden
`WfbM` als eigenständige Abkürzung sowie Kombinationen aus einem
Werkstatt-/Werkstätten-Begriff und einem Behinderungshinweis im selben Feld,
einschließlich Großschreibung, Umlauten und ae-Schreibweisen.
Allein „Werkstatt“, „Lebenshilfe“ oder „Caritas“ genügt nicht.

Fehlende Tags werden zu `amenity=social_facility` und
`social_facility=workshop` ergänzt. Das allgemeine `amenity=workshop` darf
ersetzt werden. Ein fehlendes `social_facility:for` wird bei diesen eindeutigen
Behinderungshinweisen mit `disabled` ergänzt. Bestehende Zielgruppen bleiben
unverändert; aus geistiger Behinderung wird kein `mental_health` abgeleitet.

Andere Hauptnutzungen, widersprechende soziale Untertypen sowie vorhandene
Läden, Gewerbe, Büros, medizinische Einrichtungen und Freizeiteinrichtungen
werden ausgelassen. Gebäude-, Flächennutzungs- und Adresstags bleiben erhalten.
Auch ausdrücklich stillgelegte, entfernte, zerstörte oder geplante Objekte,
verneinte/ehemalige Werkstätten und erkennbare Werkstattläden, Verwaltungs-,
Schul-, Wohn- und Pflegestandorte werden ausgelassen.
Widersprechende Hinweise in jedem der drei Textfelder haben Vorrang vor einem
passenden Namen. Relationale Erwähnungen wie „gegenüber der Behindertenwerkstatt“
klassifizieren das Gebäude nicht als Werkstatt.

Die Aufgaben zeigen den ursprünglichen Textbeleg und eine Vorher-Nachher-Tabelle
mit den tatsächlich vorgeschlagenen Änderungen. Vorhandene Website-Links helfen
bei der manuellen Prüfung. Die Hinweise sind eine Vorauswahl: Mapper müssen
prüfen, ob der konkrete Standort wirklich eine solche Werkstatt ist.

Grundlagen:
[Soziale Einrichtungen](https://wiki.openstreetmap.org/wiki/DE:Key:social_facility)
und [Zielgruppen](https://wiki.openstreetmap.org/wiki/DE:Key:social_facility:for).

## Lokal aus dem Deutschland-PBF erzeugen

Die Abhängigkeiten aus `requirements.txt` enthalten `osmium>=4.0`.
Vom Repository-Verzeichnis aus:

```powershell
.\.venv\Scripts\python.exe challenges/social_workshop/generate.py
```

Ohne `--pbf` wird `germany-latest.osm.pbf` bei Geofabrik heruntergeladen und
unter `.cache/geofabrik` im Repository zwischengespeichert. Der Download wird
höchstens 24 Stunden wiederverwendet; ein späterer Lauf entfernt die abgelaufene
Datei und lädt sie neu. `--cache-dir PATH` wählt einen anderen Cache-Ordner.
PBF- und Cache-Dateien werden nicht eingecheckt.

Eine vorhandene Datei kann direkt verwendet und zusätzlich lokal eingeschränkt
werden:

```powershell
.\.venv\Scripts\python.exe challenges/social_workshop/generate.py --pbf C:/OSM/germany-latest.osm.pbf --bbox 50.95 13.60 51.12 13.90 --max-tasks 20 --output workshop_sample.json
```

`--pbf PATH` umgeht den automatischen Download. `--bbox SOUTH WEST NORTH EAST`
filtert dieselbe PBF anhand des Anzeigemittelpunkts jedes Objekts; Ways und
Relations werden dafür einschließlich ihrer Referenzen lokal aufgelöst.
`--max-tasks N` begrenzt die Aufgabenzahl eines Probelaufs.

Die Ausgabe ist standardmäßig `social_workshop.json` neben dem Generator.
`--output PATH` wird relativ zum Aufrufverzeichnis aufgelöst; die Standardausgabe
hängt dagegen nicht vom Aufrufverzeichnis ab. Fehlende Ausgabeordner werden
angelegt. Das Format entspricht den anderen Generatoren: eine
UTF-8-JSON-Sequenz mit einem GeoJSON-FeatureCollection/TagFix je Objekt.
Diese JSON ist die versionierte, importierbare Aufgabenquelle und wird nach
erfolgreichen Läufen ins Repository übernommen.

Die gemeinsamen Obergrenzen von 50.000 Aufgaben und 99.000.000 Bytes gelten
immer. Nach Erreichen einer Grenze wird der Reader geschlossen und es werden
keine weiteren Aufgaben bearbeitet. Fehler beim Download oder PBF-Lesen lassen
die vorherige Ausgabe bestehen; erst der erfolgreiche Export ersetzt sie atomisch.

## Deutschlandweiter PBF-Lauf vom 29. Oktober 2026

Die eingecheckte JSON enthält **146 Aufgaben** aus dem vollständig durchgelaufenen
normalen Deutschland-Lauf (**Exitcode 0**, **240.607 Bytes**). Verwendet wurde der
[Geofabrik-Deutschland-Extrakt](https://download.geofabrik.de/europe/germany-latest.osm.pbf)
mit **4.871.369.043 Bytes** und dem PBF-Header-Datenstand
**2026-10-28T21:21:02Z**. Der Aufruf hatte **keine Bounding Box und kein zusätzliches
Tasklimit**. Die gemeinsamen Obergrenzen wurden nicht erreicht; der Lauf endete
nach Verarbeitung aller passenden Objekte des Extrakts.

Aufruf mit dem gemeinsam lokal zwischengespeicherten Deutschland-PBF:

```powershell
.\.venv\Scripts\python.exe challenges/social_workshop/generate.py --cache-dir .venv/geofabrik-cache --output .venv/live-challenges/workshop_germany.json
```

| OSM-Darstellung | Aufgaben |
| --- | ---: |
| Node | 30 |
| Way | 108 |
| Relation | 8 |

Die lokale Referenzauflösung verarbeitete 116 Way-/Relations-Kandidaten,
12 zusätzliche Way-Referenzen und 1.968 benötigte Node-Koordinaten. Es wurden
keine Kandidaten wegen unvollständiger Geometrie ausgelassen.
Die Vorschläge ergänzen beziehungsweise korrigieren 102-mal `amenity`,
109-mal `social_facility` und 140-mal `social_facility:for`.

Alle 146 ausgegebenen Records wurden auf JSON-Sequenz-/TagFix-Struktur,
eindeutige und übereinstimmende Objekt-IDs, endliche gültige Koordinaten,
PBF-Quelle und Datenstand geprüft. Jede vorgeschlagene Tagänderung stimmt mit
der Vorher-Nachher-Tabelle überein und verändert tatsächlich den dort gezeigten
vorherigen Wert. Zielgruppen werden ausschließlich bei fehlendem Tag ergänzt;
Löschoperationen enthält der Export nicht. Dieser deutschlandweite Export ersetzt
die frühere Dresdner Gebietsstichprobe.

## Tests und GitHub Actions

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_geofabrik tests.test_social_workshop -v
```

Die Tests decken Fachregeln, CLI, Cache-/Reader-Anbindung, Ausgabegrenzen und
Fehlerfälle ab. Kleine echte PBF-Dateien prüfen Nodes, Ways, Relations,
Zielgruppenerhalt und lokale BBox-Auswahl ohne Netzwerkzugriff.

Der Workflow **Update Social Workshop Challenge Data** kann manuell auf einem
Branch gestartet werden. Er führt die Tests und den Generator mit dem
Deutschland-PBF aus und committet ausschließlich
`challenges/social_workshop/social_workshop.json`. Es gibt keinen Zeitplan.
