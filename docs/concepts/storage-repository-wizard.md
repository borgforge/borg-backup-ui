# Konzept: Geführter Storage- und Repository-Wizard

- Issue: #187
- Status: Umgesetzt mit Issues #184 und #187
- Stand: 2026-07-11

## 1. Zusammenfassung

> **Umsetzungsstand:** Der Assistent verwendet nun vorhandene Storage- und
> Repository-Objekte, kann Local, USB, SMB und SSH/Storagebox geführt anlegen,
> prüft das Speicherziel vor dem nächsten Schritt und erstellt oder importiert
> Repositorys. Der Job-Wizard wählt nur noch vorhandene Repositorys nach dem
> exakten Speicherziel. Die folgenden Abschnitte dokumentieren die fachliche
> Herleitung dieser Umsetzung.

Tester-Feedback zeigt, dass die Einrichtung von Storage-Zielen und Borg-
Repositories aktuell zu technisch wirkt. Besonders SMB ist schwer verständlich,
weil Nutzer einen Mount-Pfad selbst angeben müssen und nicht klar ist, warum
dieser Pfad überhaupt existiert.

Der geplante Wizard soll die Denkweise ändern:

> Nicht: "Fülle technische Profile aus und tippe Repository-Pfade in Jobs."
>
> Sondern: "Richte ein Speicherziel ein, erstelle oder importiere ein
> Repository und wähle es später im Job aus."

Dieses Konzept hängt fachlich eng mit #184 zusammen. Der Wizard sollte auf
Repository-Objekte hinarbeiten, nicht nur die bestehende Job-Pfad-Eingabe hübsch
verpacken.

## 2. Zielgruppe

Der Wizard richtet sich an:

- Nutzer, die Borg Backup UI zum ersten Mal einrichten.
- Nutzer mit vorhandenen Borg-Repositories.
- Nutzer, die SMB/USB/SSH-Ziele einrichten wollen, ohne Mount-Details selbst zu
  planen.
- Fortgeschrittene Nutzer, die trotzdem manuell eingreifen können wollen.

Power-User verwalten Storage-Profile weiterhin in den erweiterten
Einstellungen; Repository-Pfade werden jedoch auch dort nicht mehr in Jobs
gespeichert.

## 3. Grundprinzipien

### 3.1 Das System schlägt sichere Defaults vor

Der Nutzer soll bei SMB nicht selbst einen temporären Mount-Pfad erfinden
müssen. Die Anwendung sollte einen verwalteten Pfad vorschlagen, zum Beispiel
unter einem eigenen Runtime-/Mount-Bereich.

Der genaue Pfad ist ein technisches Detail. Die UI kann ihn zeigen, aber nicht
als Pflichtwissen behandeln.

### 3.2 Repositorys werden bewusst erstellt oder importiert

Der Wizard soll zwei Wege anbieten:

- Neues Repository erstellen.
- Bestehendes Borg-Repository importieren.

Ein Import darf das Repository nicht verändern, sondern nur prüfen und als
verwaltetes Repository-Objekt aufnehmen.

### 3.3 Jobs wählen Repositorys aus

Nach Abschluss des Wizards steht ein Repository bereit. Der Job-Wizard wählt
dieses Repository aus, statt selbst stillschweigend neue Repository-Pfade zu
erzeugen.

## 4. Vorgeschlagener Wizard-Ablauf

### Schritt 1: Zieltyp wählen

Kartenansicht:

| Typ | Beschreibung |
| --- | --- |
| Lokal | Pfad auf dem Unraid-System |
| USB | Unassigned Devices oder lokaler Datenträger |
| SMB | Netzwerkfreigabe mit Benutzer/Passwort |
| SSH / Storagebox | Remote-Repository per SSH |
| Rclone / WebDAV | späterer Zieltyp |

Die Karte sollte kurz erklären, wann der Typ sinnvoll ist.

### Schritt 2: Verbindung oder Profil

Je nach Typ:

- Lokal: Basispfad auswählen.
- USB: vorhandenes USB-Profil wählen oder neues Profil anlegen.
- SMB: Server, Share, Benutzer, Passwort.
- SSH: Host, Port, User, Key/Passwort, Basisverzeichnis.

Bei SMB sollte zusätzlich angezeigt werden:

> Borg Backup UI verwaltet den technischen Mount-Pfad automatisch. Du musst nur
> die Freigabe und Zugangsdaten angeben.

### Schritt 3: Zugriff testen

Der Wizard prüft:

- Ziel erreichbar?
- Authentifizierung OK?
- Mount möglich, falls erforderlich?
- Lese-/Schreibtest möglich?
- Pfad plausibel?

Bei Fehlern muss die Meldung handlungsorientiert sein:

- "Zugangsdaten wurden abgelehnt."
- "SMB-Freigabe wurde erreicht, aber der Schreibtest ist fehlgeschlagen."
- "Der Host ist nicht erreichbar."

### Schritt 4: Repository erstellen oder importieren

Auswahl:

1. Neues Repository erstellen.
2. Vorhandenes Repository importieren.

#### Neues Repository

Felder:

- Anzeigename
- Repository-Name oder Unterordner
- optionale Passphrase
- Zusammenfassung des effektiven Pfads/URI

Aktion:

- `borg init` erst nach expliziter Bestätigung.

#### Vorhandenes Repository importieren

Felder:

- Anzeigename
- Repository-Pfad oder Unterordner
- Passphrase/Secret, falls nötig

Prüfung:

- `borg info` oder vergleichbare sichere Prüfung.
- Repository-ID, Archivanzahl und letzter Zugriff anzeigen, wenn verfügbar.

Wichtig:

- Kein `borg init`.
- Keine Änderung am Repository.

### Schritt 5: Zusammenfassung

Beispiel:

```text
Storage-Ziel: USB-5TB
Repository: Appdata USB
Effektiver Pfad: /mnt/disks/USB-5TB/borg-backup-appdata
Status: Zugriff erfolgreich
Verwendung: Kann im Job-Wizard ausgewählt werden
```

Buttons:

- Repository speichern
- Repository speichern und Job erstellen
- Abbrechen

## 5. SMB-spezifisches Verhalten

SMB ist der wichtigste Schmerzpunkt aus dem Feedback.

### 5.1 Verwalteter Mount-Pfad

Die UI sollte nicht fragen:

> Welchen temporären Mount-Pfad möchtest du verwenden?

Sondern:

> Borg Backup UI verwaltet den technischen Mount-Pfad automatisch.

Intern könnte ein Pfad aus Profil-Key und Share erzeugt werden. Das genaue
Schema ist Implementierungsdetail, muss aber stabil und konfliktarm sein.

Beispiel:

```text
/mnt/user/borg_backup_ui/mounts/smb/<profile-key>
```

oder ein runtime-naher Pfad, falls passend zur bestehenden Architektur.

Offene technische Prüfung: Der Pfad muss zu Unraid, Reboots, Permissions und
laufenden Backup-Prozessen passen.

### 5.2 Erweiterter Modus

Für Power-User:

- "Mount-Pfad manuell festlegen"
- klare Warnung, dass falsche Pfade zu Konflikten führen können
- Validierung gegen zu breite oder gefährliche Pfade

## 6. Bestehende Repositories importieren

Import ist fachlich wichtig, weil viele Nutzer Borg bereits verwenden.

### 6.1 Import-Ablauf

1. Storage-Ziel auswählen oder neu einrichten.
2. Repository-Pfad angeben oder auswählen.
3. Passphrase/Secret angeben, falls nötig.
4. Repository prüfen.
5. Metadaten speichern.

### 6.2 Import-Ergebnis

Nach erfolgreichem Import:

- Repository erscheint in der Repository-Liste.
- Repository ist im Job-Wizard auswählbar.
- Reports und Restore können darauf zugreifen, sobald ein Job zugeordnet ist.

### 6.3 Sicherheit

Import darf niemals:

- Archive löschen.
- Repository initialisieren.
- Prune/Compact ausführen.
- Passphrase im Klartext speichern oder loggen.

## 7. UI-Konzept

### 7.1 Einstiegspunkte

- Seite **Repositories**: **Repository hinzufügen**
- Job-Wizard: Auswahl eines bereits verwalteten Repositorys
- Seite **Einstellungen**: lokale, USB-, SMB- und SSH-Profile verwalten

### 7.2 Grobe Layout-Idee

```text
Repository einrichten

[1 Zieltyp] -> [2 Verbindung] -> [3 Test] -> [4 Repository] -> [5 Zusammenfassung]

┌──────────────────────────────────────────────────────────────┐
│ Zieltyp wählen                                                │
│                                                              │
│ [ Lokal ] [ USB ] [ SMB ] [ SSH / Storagebox ] [ Rclone ]     │
│                                                              │
│ SMB: Netzwerkfreigabe einbinden. Borg Backup UI verwaltet     │
│ den technischen Mount-Pfad automatisch.                       │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 Statusdarstellung

Jeder technische Test sollte sichtbar werden:

| Prüfung | Status | Hinweis |
| --- | --- | --- |
| Host erreichbar | OK | Verbindung hergestellt |
| Anmeldung | OK | Benutzer akzeptiert |
| Mount | OK | Freigabe eingebunden |
| Schreibtest | Fehler | Keine Schreibrechte im Zielordner |

## 8. Auswirkungen auf den Job-Wizard

Der Job-Wizard fragt im Ziel-Schritt nicht nach einem Repository-Pfad, sondern
zuerst nach dem Speicherziel und danach nach einem dazugehörigen Repository:

```text
Repository auswählen
[ Appdata - Lokal        v ]

[ Repository auf der Repository-Seite verwalten ]
```

## 9. Benötigte Backend-Funktionen

- Storage-Profil erstellen/aktualisieren.
- Storage-Zugriff testen.
- Mount verwalten, falls erforderlich.
- Repository importieren.
- Repository initialisieren.
- Repository testen.
- Repository-Objekt speichern.
- Job mit Repository-Objekt verknüpfen.

## 10. Fehler- und Warnmeldungen

Gute Fehlermeldungen sind zentral. Beispiele:

- "Die SMB-Freigabe wurde gefunden, aber die Anmeldung wurde abgelehnt."
- "Der Schreibtest ist fehlgeschlagen. Prüfe die Berechtigungen auf der Freigabe."
- "Dieser Ordner enthält kein Borg-Repository. Du kannst ein neues Repository erstellen oder einen anderen Pfad wählen."
- "Das Repository ist erreichbar, aber die Passphrase ist falsch."
- "Dieses Repository wird bereits von einem anderen Job verwendet."

## 11. Umgesetzter Datenfluss

1. Storage Target unter **Einstellungen** anlegen oder auswählen.
2. Repository unter **Repositories** erstellen oder importieren.
3. Der Repository-Manager speichert Verschlüsselung und Secret-Verweise im
   Repository-Objekt.
4. Der Job-Wizard filtert Repositorys nach dem gewählten Storage Target.
5. Der Job speichert ausschließlich `repository_key`.
6. Backup, Restore, Restore-Test, Reports und Wartung verwenden dieselbe
   zentrale Repository-Auflösung.
