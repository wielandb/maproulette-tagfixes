# Soziale Werkstätten korrekt einordnen

Dieser Generator erstellt deutsche MapRoulette-TagFix-Aufgaben für ausdrücklich
als Werkstätten für Menschen mit Behinderungen beschriebene OSM-Objekte.
Standardmäßig wird Deutschland abgefragt. Ein kleineres Gebiet lässt sich mit
einer Bounding Box auswählen.

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
Auch ausdrücklich stillgelegte oder geplante Objekte, verneinte/ehemalige
Werkstätten und erkennbare Werkstattläden, Verwaltungs-, Schul-, Wohn- und
Pflegestandorte werden ausgelassen. Widersprechende Hinweise in jedem der
drei Textfelder haben Vorrang vor einem passenden Namen. Rein relationale
Erwähnungen wie „gegenüber der Behindertenwerkstatt“ klassifizieren das Gebäude
nicht als Werkstatt. Auch removed-/destroyed-Lifecycle-Tags schließen es aus.

Die Aufgaben zeigen den ursprünglichen Textbeleg und eine Vorher-Nachher-Tabelle
mit den tatsächlich vorgeschlagenen Änderungen. Vorhandene Website-Links helfen
bei der manuellen Prüfung. Die Hinweise sind eine Vorauswahl: Mapper müssen
prüfen, ob der konkrete Standort wirklich eine solche Werkstatt ist.

Grundlagen:
[Soziale Einrichtungen](https://wiki.openstreetmap.org/wiki/DE:Key:social_facility)
und [Zielgruppen](https://wiki.openstreetmap.org/wiki/DE:Key:social_facility:for).

## Lokal erzeugen

Vom Repository-Verzeichnis aus, mit den Abhängigkeiten aus `requirements.txt`:

```powershell
.\.venv\Scripts\python.exe challenges/social_workshop/generate.py
```

Die Ausgabe ist `social_workshop.json` neben dem Generator. Diese Datei ist
die versionierte, importierbare Aufgabenquelle und wird nach erfolgreichen
Läufen ins Repository übernommen. Sie muss vor dem ersten Lauf noch nicht
vorhanden sein. Das Format entspricht den anderen Generatoren: eine
UTF-8-JSON-Sequenz mit einem GeoJSON-FeatureCollection/TagFix je Objekt.

Für einen begrenzten Probelauf:

```powershell
.\.venv\Scripts\python.exe challenges/social_workshop/generate.py --bbox 50.7 12.7 51.2 14.0 --max-tasks 20 --output workshop_sample.json
```

`--bbox SOUTH WEST NORTH EAST` ersetzt die Deutschlandauswahl.
`--output PATH` wird relativ zum Aufrufverzeichnis aufgelöst; die Standardausgabe
hängt dagegen nicht vom Aufrufverzeichnis ab. Fehlende Ausgabeordner werden
angelegt. `--max-tasks N` begrenzt einen Probelauf. Die gemeinsamen Obergrenzen von 50.000 Aufgaben und 99.000.000 Bytes
gelten immer. Nach Erreichen einer Grenze werden keine weiteren Aufgaben
bearbeitet. Fehler bei der Abfrage lassen die vorherige Datei bestehen; die
neue Ausgabe ersetzt sie erst beim erfolgreichen atomischen Schreiben.

## Erster eingecheckter Datenstand

Der initiale Export vom **29. Oktober 2026** enthält **zwei echte Aufgaben** aus
einer Dresdner Stichprobe mit der Bounding Box
**50.95 13.60 51.12 13.90**. Er ist kein vollständiger Deutschland-Export.
Die Kandidatensuche lieferte 19 Objekte auf einem veralteten französischen
Overpass-Spiegel. Die beiden passenden Objekte wurden deshalb vor der
Aufgabenerzeugung mit vollständigen aktuellen Tags und Geometrien aus der
OSM-Editing-API neu geladen und erneut durch den Klassifikator geprüft.

Die Aufgaben betreffen `way/580124359` (Einrichtungstyp und Zielgruppe ergänzen)
und `way/1088311816` (nur die fehlende Zielgruppe ergänzen). Ein regulärer
Generatorlauf mit aktuellen Overpass-Daten ersetzt diese Stichprobe durch die
gewählte Gebietsauswahl. Die gemeinsame Frischeprüfung für Overpass-Antworten
bleibt dabei aktiv; der Generator übernimmt keine veralteten Antworten.

## Tests und GitHub Actions

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_social_workshop -v
```

Der Workflow **Update Social Workshop Challenge Data** kann manuell auf einem
Branch gestartet werden. Er führt die Tests und den deutschlandweiten Generator
aus und committet ausschließlich `challenges/social_workshop/social_workshop.json`.
Es gibt keinen Zeitplan.
