# BRU Tea Maker für Home Assistant

Steuert die **BRU Maker One** Teemaschine lokal per Bluetooth LE – ohne Cloud und ohne die Handy-App.

## Funktionen
- Automatische Erkennung der Maschine über Bluetooth
- Koppeln mit Pairing-Code direkt im Einrichtungsdialog
- Auswahl von Temperatur, Brühzeit und Wassermenge, Schalter „Spülen“
- Eigene Teesorten (Name, Temperatur, Zeit, Menge, Spülen) mit Auswahlliste und eigenem Button je Sorte
- Buttons: Tee zubereiten, Abbrechen, Status aktualisieren
- Sensoren mit Klartext wie in der App: Status (z. B. „Brühen“, „Warnung: Bitte Deckel schließen“),
  Phase (z. B. „Ziehen lassen“, „Guten Tee!“), letztes Brüh-Ergebnis.
  Die internen Namen stehen in den Attributen `status_raw` / `substatus_raw` (für Automationen).
- Status läuft dauerhaft mit, ohne Verbindung: Die Maschine sendet ihn in ihren Bluetooth-Signalen (Advertisements).
  Verbunden wird nur zum Brühen und Abbrechen, die Handy-App bleibt also nutzbar.
- Dienst `bru_tea.brew` für Automationen

## Installation über HACS
1. HACS → ⋮ → **Benutzerdefinierte Repositories**
2. `https://github.com/ledil/bru-tea-homeassistant` eintragen, Typ **Integration**
3. „BRU Tea Maker“ herunterladen und Home Assistant neu starten

## Einrichten
1. BRU-App auf dem Handy schließen (die Maschine erlaubt nur eine Verbindung).
2. Einstellungen → Geräte & Dienste: Maschine unter „Entdeckt“ → **Konfigurieren**
   (oder „Integration hinzufügen“ → „BRU Tea Maker“).
3. An der Maschine **Setup → Bluetooth → Pairing** aktivieren und **Absenden** klicken.
4. Den angezeigten Code eingeben.

Voraussetzung: Bluetooth direkt am Home-Assistant-Rechner (eingebaut oder USB-Stick).
Koppeln mit Code funktioniert nicht über ESPHome-Bluetooth-Proxys.

## Eigene Teesorten
Einstellungen → Geräte & Dienste → BRU Tea Maker → **Konfigurieren**: Teesorten hinzufügen, bearbeiten oder löschen.
Für jede Sorte entsteht ein Button „<Name> zubereiten“, außerdem gibt es die Auswahlliste „Teesorte“.
Beim ersten Start sind Grüntee, Schwarztee, Weißer Tee und Kräutertee als Vorschläge angelegt.

```yaml
action: bru_tea.brew
data:
  tea: Grüntee
```

## Beispiel-Automation
```yaml
automation:
  - alias: Morgentee
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: bru_tea.brew
        data:
          temperature: "80"   # Kalt, 45–95 (5er-Schritte) oder max
          time: "3:00"        # 0:10–9:50 in 10-s-Schritten, 10:00–60:00
          water: 250          # 50–350 ml
```

## Protokoll
| | |
|---|---|
| Service | `aae28f00-71b5-42a1-8c3c-f9cf6ac969d0` |
| Notify | `aae28f01-71b5-42a1-8c3c-f9cf6ac969d0` |
| Write (ohne Response) | `aae28f02-71b5-42a1-8c3c-f9cf6ac969d0` |
| Rahmen | `FF <Länge> <Cmd> <Payload…> <Prüfsumme>` |
| Prüfsumme | `((-Summe der Bytes) & 0xFF) XOR 0x3A` |
| Brühen | Cmd `0x40`, Payload `[0, Temp, Zeit, Wasser, Spülen, 0, 0, Buzzer, 0, 0, 0]` (+ 60 Byte Identität ab Firmware 290626) |
| Status | Cmd `0x44` → Antwort `0x45` (Status, Unterstatus) |
| Advertisement | Herstellerdaten mit Firmen-ID davor: Byte 3 = Status, Byte 4 = Phase |
| Abbrechen | Cmd `0x42` |
| Brüh-Ergebnis | Antwort `0x41`: 0 OK, 1 Format, 3 Temp, 4 Zeit, 5 Wasser, 16 nicht bereit |

Unter `tools/bru_tea.py` liegt ein eigenständiges Kommandozeilen-Skript (benötigt `pip install bleak`).

## Hinweis
Inoffizielles Projekt, nicht mit BRU verbunden. Nutzung auf eigene Gefahr.
