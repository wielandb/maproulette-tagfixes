# Add mapped objects to stop areas

This generator finds existing OSM equipment and access infrastructure near
German `railway=station` objects and suggests membership in an existing
`public_transport=stop_area` relation. It does not create equipment or stop areas.

The catalogue follows the OSM Wiki's [accessibility guide for public transport
stops](https://wiki.openstreetmap.org/wiki/DE:Leitfaden_-_Barrierefreiheit_an_Haltestellen),
with additional tag variants from the [DELFI attribute mapping](https://wiki.openstreetmap.org/wiki/DELFI_Attribute_-_Barrierefreiheit_im_%C3%96ffentlichen_Personenverkehr),
[departures-board documentation](https://wiki.openstreetmap.org/wiki/Key:departures_board)
and [stop-area member documentation](https://wiki.openstreetmap.org/wiki/Tag:public_transport%3Dstop_area).

## Candidate catalogue

| Category | OSM tags |
| --- | --- |
| Seats, shelters, waste baskets | `amenity=bench`, `amenity=shelter`, `amenity=waste_basket` |
| Ticket machines | `amenity=vending_machine` + `vending=public_transport_tickets`, including semicolon-separated vending lists |
| Lifts | `highway=elevator` |
| Printed timetables and electronic departure boards | `departures_board=yes/timetable/realtime/delay`, `passenger_information_display=yes`, or `tourism=information` + `information=board` + `board_type=public_transport` |
| Public transport information offices and intercoms | `tourism=information` + `information=office/phone` + `information:public_transport=yes` |
| Emergency intercoms | `emergency=phone` |
| Public transport maps | `tourism=information` + `information=map` + `map_type=public_transport` |
| Tactile maps | `tourism=information` + `information=tactile_map` |
| Ticket sales, including offices and kiosks | `tickets:public_transport=yes/only` |
| Taxi stands, toilets, car and bicycle parking | `amenity=taxi/toilets/parking/bicycle_parking` |
| Luggage lockers | `amenity=locker` + `locker=luggage/handbag` |
| Luggage trolley bays | `amenity=trolley_bay` |
| Station entrances | `railway=train_station_entrance/subway_entrance` |
| Doors and other entrances | `indoor=door`, or `entrance=yes/main/secondary/service/emergency/exit/staircase` |
| Access paths, ramps and indoor corridors | `highway=footway/path/corridor` |
| Steps, escalators and stairs with lifts | `highway=steps`, including `conveying=*` and `platform_lift=*` variants |
| Road and rail crossings | `highway=crossing`, `railway=crossing/tram_crossing` |
| Individual steps, kerbs and cycle barriers | `barrier=step/kerb/cycle_barrier` |
| Tactile paving and separately mapped guidance strips | `tactile_paving=yes/contrasted/incorrect/primitive` |

Slashes in the table list alternative values, not literal tag values.
The exact rules live in `TARGET_TAG_SETS` in `generate.py`. Exact matches and
regular expressions are shared by the Overpass query, local candidate filter
and task descriptions; descriptions show the object's actual tag values.

## Review and scope

Selection starts with stations tagged `railway=station`, not every bus stop or
`railway=halt`. Candidates are collected within 200 m of these stations, with
stop areas collected within 400 m. Each candidate is proposed for the nearest
collected stop-area centre within 300 m. Already assigned members are excluded;
the current target relation is checked again against the OSM editing API.

These distances only generate suggestions. Mappers must check actual station
ownership and connectivity, particularly for paths, doors, crossings, nearby
parking and toilets. Each task contains all proposed additions in one editable
OSC change. Remove unsuitable additions before uploading; if none belong, do
not apply the change. Existing members, roles and relation tags are preserved;
new equipment and access members use an empty role.

Platform, station and stop-position objects are excluded from equipment
suggestions, including legacy tags and their `disused:`, `abandoned:`,
`construction:` and `proposed:` forms. An attribute such as
`passenger_information_display=yes` on a platform does not represent a separate
display. Portable ramps and platform lifts are also platform attributes in the
guide; they do not create extra objects to add. Their independently mapped
access infrastructure is covered by lifts, paths and steps. Negative values
such as `departures_board=no`, or accessibility attributes such as
`wheelchair=yes` or `speech_output=yes` alone, are not candidate objects.

## Generate a local sample

From the repository root:

```powershell
New-Item -ItemType Directory -Force .venv/live-challenges | Out-Null
.\.venv\Scripts\python.exe challenges/add_objects_to_stop_area/generate.py --bbox 51.025 13.70 51.09 13.79 --max-tasks 5 --output .venv/live-challenges/stop_area_dresden.json
```

Omit `--bbox` to scan Germany. Generation saves task data only; importing and
publishing a MapRoulette challenge is a separate step. Existing generated files
must be regenerated to include catalogue changes.
