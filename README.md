# Pirate Weather Mobile

Home-Assistant-Integration für [Pirate Weather](https://pirateweather.net/), deren Standort einem `device_tracker` folgt – gedacht für Wohnmobile, Boote und alles andere, was sich bewegt.

- **Wetter-Entity** mit aktuellen Werten, Stunden- (7 Tage) und Tagesvorhersage (8 Tage)
- **Dynamischer Standort** aus einem beliebigen `device_tracker` mit GPS-Koordinaten
- **Robust bei Funklöchern**: letzte Vorhersage bleibt erhalten, eine Warnung statt Fehlerflut
- **Offline-Cache**: auch nach einem Neustart ohne Netz ist die letzte Vorhersage sofort da
- **Einzelne Sensoren** für Automationen (optional zuschaltbar)
- Einrichtung komplett über die Oberfläche, kein YAML

## Installation

### HACS (empfohlen)

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → URL dieses Repositories, Kategorie *Integration*
2. „Pirate Weather Mobile“ installieren, Home Assistant neu starten
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Pirate Weather Mobile*

### Manuell

Den Ordner `custom_components/pirateweather_mobile_usage` nach `<config>/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

| Feld | Beschreibung |
|---|---|
| Name | Gerätename, bestimmt die Entity-IDs (z. B. `weather.wohnmobil`) |
| API-Key | Kostenlos unter <https://pirate-weather.apiable.io/> |
| Device Tracker | Entity mit den Attributen `latitude` und `longitude` |

### Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| Aktualisierungsintervall | 15 min | Reguläre Abfrage |
| Neu abrufen nach Ortswechsel von | 2 km | Sofortige Abfrage, wenn sich das Fahrzeug so weit vom letzten Abfrageort entfernt hat (höchstens alle 5 min) |
| Vorhersage offline behalten für | 12 h | Danach werden die Entitäten „nicht verfügbar“ |
| Sprache | de | Sprache der Zusammenfassungstexte |

**API-Verbrauch:** Bei 15 min Intervall sind es ca. 2 900 Aufrufe/Monat plus Abfragen während der Fahrt (max. 12/h). Das kostenlose Kontingent liegt bei 10 000/Monat; der Sensor *Verbleibende API-Aufrufe* zeigt den Stand.

## Verhalten ohne Netz

| Situation | Verhalten |
|---|---|
| Verbindung bricht ab | **Eine** Warnung im Log, Entitäten behalten die letzte Vorhersage, Attribut `offline: true` |
| Weitere Fehlversuche | Nur Debug-Log; Wiederholung nach 2, 4, 8, … bis max. 60 min |
| Vorhersage älter als 1 h | Aktuelle Werte werden aus der Stundenvorhersage für die jetzige Stunde genommen; vergangene Stunden/Tage werden ausgeblendet |
| Verbindung wieder da | **Eine** Info-Meldung, normales Intervall, aktueller Standort |
| Monatskontingent erschöpft | Wie Netzausfall, Wiederholung stündlich |
| API-Key ungültig | Home Assistant fordert über eine Reparaturmeldung einen neuen Key an |
| Tracker ohne GPS (`unavailable`) | Letzter Abfrageort wird weiterverwendet |
| Start ohne Netz | Integration startet normal mit der gespeicherten Vorhersage (falls vorhanden) |

## Entitäten

**Wetter:** `weather.<name>` – Attribute zusätzlich: `forecast_latitude`, `forecast_longitude`, `location_source` (`tracker` / `last_known` / `home`), `last_update`, `offline`, `summary`.

**Standardmäßig aktiv:**

| Sensor | Inhalt |
|---|---|
| Wetterwarnungen | Anzahl aktiver Warnungen; Details (Titel, Schwere, Gültigkeit, Text) im Attribut `alerts` |
| Letzte Aktualisierung | Zeitpunkt des letzten erfolgreichen Abrufs |
| Verbleibende API-Aufrufe | Restkontingent im Monat |

**Optional** (unter *Entitäten* aktivieren): Temperatur, gefühlte Temperatur, Taupunkt, Luftfeuchtigkeit, Luftdruck, Windgeschwindigkeit, Windböen, Windrichtung, Bewölkung, Sichtweite, UV-Index, Niederschlagsintensität, Regenwahrscheinlichkeit, Niederschlagsart, Entfernung/Richtung nächstes Unwetter, Zusammenfassung, **Regenwahrscheinlichkeit nächste 3 h**, **Max. Windböen nächste 3 h**, Vorhersage-Zusammenfassung, Höchst-/Tiefsttemperatur heute, Regenwahrscheinlichkeit heute, Niederschlag heute, Zusammenfassung heute.

### Beispiel: Markise einfahren

```yaml
automation:
  - alias: Markise bei Wind oder Regen einfahren
    triggers:
      - trigger: numeric_state
        entity_id: sensor.wohnmobil_max_windboen_nachste_3_h
        above: 40   # km/h
      - trigger: numeric_state
        entity_id: sensor.wohnmobil_regenwahrscheinlichkeit_nachste_3_h
        above: 70
    actions:
      - action: notify.mobile_app_handy
        data:
          message: "Markise einfahren – {{ trigger.to_state.name }}: {{ trigger.to_state.state }}"
```

(Die Entity-IDs hängen von Name und Sprache ab – bitte unter *Entitäten* nachsehen.)

## Entwicklung

```bash
pip install -r requirements_test.txt   # Python 3.14
pytest
```

Datenquelle: Pirate Weather (SI-Einheiten; Home Assistant rechnet in die eigenen Einheiten um).

## Lizenz

MIT – siehe [LICENSE](LICENSE).
