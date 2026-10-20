# Richtung von Stop- und Vorfahrt-gewähren-Knoten

`directions.py` erzeugt Richtungsvorschläge für die manuelle Prüfung in
MapRoulette. `forward` und `backward` bezeichnen die betroffene **Fahrtrichtung**
relativ zum OSM-Way, siehe [OSM-Dokumentation](https://wiki.openstreetmap.org/wiki/Tag:highway%3Dstop#Direction).

## Bisherige Fehlerursachen

- Bei langen Ways entschied hauptsächlich die Zahl der Wegpunkte bis zum
  Way-Ende. Eine kurze, detailliert gezeichnete Kurve konnte dadurch weiter
  entfernt erscheinen als ein langes gerades Straßenstück.
- Bei Ways unter 50 m zeigte die Regel bei ungleichen Way-Mitgliedschaften zur
  weniger verbundenen Seite. Bei Gleichstand wurde pauschal `backward` gewählt.
- Die Abfrage lud nur Ways durch richtungslose Schilder. Die anschließenden
  Mitgliedschaftszahlen enthielten daher keinen vollständigen Kreuzungskontext.
  Way-Splits, Flächen und Fußwege konnten außerdem als Kreuzung erscheinen.

## Neue Berechnung

Die erste Abfrage bestimmt die Kandidaten. Pro 100 Kandidaten lädt eine weitere
Abfrage sämtliche Straßen im Radius von 120 m mit vollständigen Wegpunkten.
Nur die ausgewählten Kandidaten können Aufgaben erzeugen; weitere Schilder im
Kontext werden nicht versehentlich übernommen.

Ein Graph aus eindeutigen Straßenkanten wird vom Schild aus in beide Richtungen
verfolgt. Zwei Nachbarn bedeuten eine Fortsetzung, auch über die Grenze zweier
OSM-Ways hinweg. Ab drei verschiedenen Nachbarn liegt eine mögliche Kreuzung
vor. Die Entfernung wird entlang der Straße in Metern gemessen.

Ein Vorschlag entsteht nur, wenn eine Kreuzung höchstens 60 m entfernt ist und
die Gegenseite mindestens doppelt so weit sowie mindestens 10 m weiter entfernt
belegt ist. Ein unvollständiger Ast liefert nur die nachgewiesene Entfernung,
keine unendliche Entfernung. Die Suche endet spätestens nach 120 m und schaut
nicht über einen weiteren Stop-/Vorfahrt-gewähren-Knoten hinaus.

Flächen, reine Fuß-/Radwege, Grundstückszufahrten, Parkgassen und ähnliche
untergeordnete Servicewege dienen nicht als Kreuzungsbeleg. Schilder auf diesen
Wegen werden vorerst ausgelassen. Ein Schild auf einem gemeinsamen Knoten von
Straße und Zufahrt bleibt mehrdeutig und wird ebenfalls ausgelassen.
Schleifen, mehrfach vorkommende Way-Knoten, Schilder auf Kreuzungen oder
Way-Endpunkten sowie unklare Entfernungsverhältnisse erhalten keinen Vorschlag.
Vorhandenes `direction` oder `stop:direction` bleibt erhalten.

Diese Regeln bevorzugen weniger, dafür besser begründete Aufgaben. Die nächste
Straßenkreuzung ist weiterhin eine Heuristik: Sonderregelungen, falsche
Schildpositionen oder fehlende Straßen lassen sich daraus nicht sicher erkennen.

## Prüfung der gemeldeten Challenge 51016

Am 18.10.2026 wurden die 227 Aufgaben aus `challenge_51016_tasks.csv` mit ihren
ursprünglichen MapRoulette-Vorschlägen und aktuellen OSM-Straßengeometrien
verglichen. Alle Aufgaben haben den Status `Not_An_Issue`. Dieser Status allein
beweist keinen Richtungsfehler: Kommentare nennen auch Flächenkonflikte,
separat eingezeichnete Schilder und bereits korrekte Richtungen.

Drei Schildknoten sind inzwischen gelöscht. Für die übrigen 224 Situationen
ergibt ein hypothetischer erneuter Durchlauf ohne bereits gesetztes `direction`:

| Ergebnis gegenüber dem ursprünglichen Vorschlag | Fälle |
| --- | ---: |
| Gegenrichtung vorgeschlagen | 86 |
| Kein ausreichend begründeter Vorschlag | 68 |
| Bisherige Richtung beibehalten | 70 |

78 Knoten haben heute ein explizites `direction=forward/backward`. Der alte
Vorschlag widerspricht diesem Tag in 62 Fällen. Die neue Heuristik stimmt in
40 Fällen überein, enthält 5 Widersprüche und lässt 33 Fälle aus. Das ist ein
Abgleich mit heutigen Tags, **keine gemessene Gesamtfehlerquote**: Die Stichprobe
enthält nur abgelehnte Aufgaben, und Geometrie oder Tags können sich seit der
Aufgabenerstellung geändert haben. Im normalen Generator werden diese bereits
getaggten Knoten ohnehin übersprungen.

| Beispiel | Befund |
| --- | --- |
| [4578279678](https://www.openstreetmap.org/node/4578279678) / [Aufgabe 320542193](https://maproulette.org/challenge/51016/task/320542193) | Kurzer Feldweg: Hauptstraße 7,0 m voraus, Feldwegabzweig 19,4 m zurück. Jetzt `forward` statt `backward`, passend zum Kommentar. |
| [8579458001](https://www.openstreetmap.org/node/8579458001) | Straßenkreuzung 3,5 m zurück. Jetzt `backward` statt `forward`, passend zum heutigen Tag. |
| [8579457797](https://www.openstreetmap.org/node/8579457797) | Flächenkonflikt und nur 1,6 m belegte Gegenstrecke: kein Vorschlag. |
| [5220280435](https://www.openstreetmap.org/node/5220280435) | Kommentar bestätigt ausdrücklich `backward`; die Richtung bleibt erhalten. |

Offene Widersprüche sind die Knoten
[2161808340](https://www.openstreetmap.org/node/2161808340) und
[3953725971](https://www.openstreetmap.org/node/3953725971): Kommentare und heutige
Tags nennen `forward`, die Kreuzung liegt aber 11,8 beziehungsweise 5,9 m in
`backward`-Richtung. Die zugehörigen Ways wurden seit 2023 beziehungsweise 2019
nicht verändert. Diese Fälle benötigen eine Prüfung der tatsächlichen
Beschilderung. Auch die heutigen Tags an
[3304148653](https://www.openstreetmap.org/node/3304148653),
[11248560587](https://www.openstreetmap.org/node/11248560587) und
[842303689](https://www.openstreetmap.org/node/842303689) widersprechen der neuen
Heuristik und sind nicht als behoben zu zählen.

Die vollständigen heruntergeladenen Daten und der Vergleich liegen lokal im
ignorierten Verzeichnis `.venv/stopsign-analysis/` (`tasks/`, `osm_maps/`,
`comparison.json`, `compare.py`). Die OSM-Karten umfassen jeweils 210 m um den
ursprünglichen Aufgabenpunkt. Vier kleine Geometrieauszüge sind als
`tests/fixtures/stopsign_51016_examples.json` für Offline-Regressionen erhalten.
OSM-Daten: [© OpenStreetMap-Mitwirkende, ODbL](https://www.openstreetmap.org/copyright).

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_stopsign*.py" -v
```

Die Tests prüfen echte Beispielsituationen, kurze Straßen, unterschiedliche
Knotendichte, Way-Splits, Flächen, Fußwege, Zufahrten, Schleifen, fehlenden
Kontext, Distanzgrenzen, Way-Umkehr und die Trennung von Kandidaten und Kontext.
Fehlgeschlagene Downloads dürfen die bisherige Ausgabedatei nicht ersetzen.
