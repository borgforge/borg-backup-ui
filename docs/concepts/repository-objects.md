# Konzept: Repository-Objekte als auswählbare Ziele

- Issue: #184
- Status: Konzept, keine Implementierung
- Stand: 2026-07-09

## 1. Zusammenfassung

Die aktuelle Anwendung ist in vielen Bereichen job-zentriert: Ein Backup-Job
enthält seine Quelle, sein Ziel, seine Repository-Konfiguration und seine
Ausführungsregeln. Für technisch versierte Nutzer ist das nachvollziehbar, für
neue Nutzer wirkt es aber ungewohnt. Sie erwarten häufig diesen Ablauf:

1. Speicherziel einrichten.
2. Repository erstellen oder vorhandenes Repository importieren.
3. Backup-Job anlegen und Repository auswählen.

Dieses Konzept schlägt deshalb vor, Borg-Repositories als eigene, auswählbare
Objekte einzuführen. Jobs sollen langfristig nicht mehr primär einen
Repository-Pfad erzeugen, sondern ein bestehendes Repository referenzieren.

Das ist keine reine UI-Änderung. Es ist eine kleine Architekturverschiebung,
die aber gut zur bestehenden Anwendung passt, wenn sie schrittweise umgesetzt
wird.

## 2. Zielbild

Ein Benutzer sieht unter Storage oder einer neuen Repository-Ansicht eine Liste
verwalteter Repositories:

| Repository | Storage | Typ | Pfad/URI | Status | Verwendet von |
| --- | --- | --- | --- | --- | --- |
| Appdata - Lokal | Lokal | local | /mnt/backup/borg-backup-appdata | OK | appdata_local |
| Appdata - USB | USB-5TB | usb | /mnt/disks/USB-5TB/borg-backup-appdata | OK | appdata_usb |
| Appdata - Storagebox | Storagebox | ssh | ssh://.../borg-backup-appdata | OK | appdata_storagebox |

Im Job-Wizard wählt der Nutzer dann:

> Repository: Appdata - USB

statt einen Repository-Pfad direkt in den Job zu tippen oder indirekt erzeugen
zu lassen.

## 3. Ist-Zustand

Aktuell liegen repository-relevante Informationen an mehreren Stellen:

- Job-Metadaten enthalten `repo.conf_key` und `repo.default`.
- `backup.conf` enthält Repository-Keys und weitere Laufzeitwerte.
- Settings enthalten Storage-Profile wie USB-, SMB- und SSH/Storagebox-Profile.
- Restore, Reports, Dashboard und History lesen repository-nahe Daten häufig
  über den Job-Kontext.
- Per-Repository-Passphrasen existieren bereits als eigenständigeres Konzept,
  sind aber weiterhin stark an vorhandene Repository-Pfade gebunden.

Das funktioniert betrieblich, aber es vermischt drei fachliche Ebenen:

- Storage-Ziel: Wo liegt etwas?
- Repository: Welches Borg-Repository wird genutzt?
- Job: Welche Daten werden wann in welches Repository gesichert?

## 4. Zielmodell

### 4.1 Storage Target

Ein Storage Target beschreibt den erreichbaren Speicherort oder das Profil.

Beispiele:

- Lokales Verzeichnis
- USB-Profil
- SMB-Profil
- SSH/Storagebox-Profil
- später Rclone/WebDAV

Mögliche Felder:

| Feld | Bedeutung |
| --- | --- |
| `storage_key` | stabile technische ID |
| `type` | `local`, `usb`, `smb`, `ssh`, später `rclone` |
| `display_name` | sichtbarer Name |
| `profile_key` | Referenz auf USB-/SMB-/SSH-Profil, falls vorhanden |
| `mount_mode` | none, managed, external |
| `status` | letzter Verbindungs-/Mount-Status |

### 4.2 Repository

Ein Repository beschreibt ein konkretes Borg-Repository auf einem Storage Target.

Mögliche Felder:

| Feld | Bedeutung |
| --- | --- |
| `repository_key` | stabile technische ID, z. B. `repo_appdata_usb` |
| `display_name` | sichtbarer Name |
| `storage_key` | Referenz auf Storage Target |
| `repo_path` | lokaler Pfad oder relativer Pfad auf dem Storage |
| `repo_uri` | effektive Borg-URI, falls remote |
| `borg_repo_id` | optional aus `borg info`, falls verfügbar |
| `passphrase_ref` | optionaler Secret-/Passphrase-Verweis |
| `last_test_status` | letzter Repository-Test |
| `last_check_status` | letzter Borg Check |
| `last_seen_at` | letzter erfolgreicher Zugriff |
| `created_by` | `wizard`, `import`, `migration`, `manual` |
| `offsite_candidate` | Hinweis für spätere Strategie-Features |
| `separate_medium_candidate` | Hinweis für spätere Strategie-Features |

### 4.3 Backup Job

Ein Job referenziert künftig ein Repository:

```json
{
  "job_key": "appdata_usb",
  "source_paths": ["/mnt/user/appdata"],
  "repository_key": "repo_appdata_usb"
}
```

Der Job kann für eine Übergangszeit weiterhin `repo.default` speichern, aber die
führende Quelle wäre langfristig `repository_key`.

## 5. Warum das wichtig ist

### 5.1 Besseres Nutzerverständnis

Der Nutzer kann zuerst ein Repository anlegen oder importieren und später in
mehreren UI-Bereichen wiederverwenden.

### 5.2 Bestehende Repositories werden sichtbar

Ein vorhandenes Borg-Repository muss nicht "neu erfunden" werden. Es kann
importiert, geprüft und anschließend einem Job zugeordnet werden.

### 5.3 Grundlage für 3-2-1-0-0

Die 3-2-1-0-0-Strategie darf Jobs nicht nur anhand von Namen gruppieren. Ein
Repository-Objekt kann ausdrücken:

- Welcher Storage-Typ wird genutzt?
- Ist das Ziel offsite?
- Ist es ein separates Medium?
- Welche Jobs schreiben in dieses Repository?

### 5.4 Weniger doppelte Logik

Dashboard, Reports, Restore, Repository-Checks und Wizard könnten langfristig
auf dieselbe Repository-Auflösung zugreifen.

## 6. Migrationsidee

Da die Anwendung noch nicht öffentlich über Community Apps veröffentlicht ist,
sollte keine dauerhafte Legacy-Parallelwelt aufgebaut werden. Trotzdem dürfen
vorhandene Tester-Daten nicht verloren gehen.

Vorgeschlagene Migration:

1. Alle Job-Metadaten lesen.
2. Für jeden eindeutigen Repository-Pfad oder jede eindeutige URI ein
   Repository-Objekt erzeugen.
3. Storage-Typ und Profil aus Job-Location, Profil-Key und Repo-URI ableiten.
4. Job um `repository_key` ergänzen.
5. Bestehende `repo`-Information zunächst erhalten, aber als abgeleitet
   behandeln.
6. Migration idempotent protokollieren.

Beispiel:

```json
{
  "migration_id": "repository_objects_v1",
  "status": "applied",
  "actions": [
    "created repository repo_appdata_usb from job appdata_usb",
    "linked job appdata_usb to repo_appdata_usb"
  ]
}
```

Wichtig: Die Migration darf keine Borg-Repositories initialisieren, löschen oder
verändern. Sie erstellt nur UI-Metadaten.

## 7. Datenablage

Eine mögliche Ablage:

```text
/boot/config/borg-backup/config/repositories.json
```

oder, falls das bestehende Settings-Modell bevorzugt wird:

```json
{
  "repositories": []
}
```

Für Wartbarkeit spricht eine eigene Datei, weil Repositorys fachlich näher an
Jobs, Restore, Reports und Storage liegen als an allgemeinen Einstellungen.

## 8. API-Entwurf

Mögliche Endpunkte:

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/api/repositories` | Repositorys listen |
| POST | `/api/repositories` | Repository anlegen/importieren |
| POST | `/api/repositories/test` | Repository testen |
| PUT | `/api/repositories/<key>` | Metadaten aktualisieren |
| DELETE | `/api/repositories/<key>` | Repository-Objekt entfernen, nicht Borg-Daten löschen |

Löschregel:

- Ein Repository-Objekt darf nicht gelöscht werden, wenn Jobs es verwenden.
- Das Löschen des UI-Objekts darf niemals das Borg-Repository auf dem Datenträger
  löschen.

## 9. Auswirkungen auf bestehende Bereiche

### 9.1 Job-Wizard

Der Wizard sollte Repository-Auswahl anzeigen:

- vorhandenes Repository auswählen
- neues Repository über Storage-/Repository-Wizard erstellen
- vorhandenes Repository importieren

### 9.2 Storage

Storage zeigt nicht nur Profile, sondern darunter zugehörige Repositories.

### 9.3 Restore

Restore kann weiterhin jobbasiert starten, sollte aber die Repository-Metadaten
aus dem Repository-Objekt beziehen.

### 9.4 Reports

Reports können klarer zeigen, welches Repository analysiert wird und ob mehrere
Jobs dasselbe Repository nutzen.

### 9.5 Systemzustand

Neue Prüfungen:

- Job referenziert fehlendes Repository.
- Repository referenziert fehlendes Storage-Profil.
- Repository-Pfad ist leer oder nicht plausibel.
- Repository wird von keinem Job genutzt.

## 10. Offene Fragen

- Soll ein Repository von mehreren Jobs genutzt werden dürfen?
- Soll die UI davor warnen, wenn mehrere Jobs in dasselbe Repository schreiben?
- Wie stark sollen Repository-Namen automatisch aus Jobnamen erzeugt werden?
- Soll ein Repository ein eigenes Check-Intervall besitzen oder weiter der Job?
- Wo liegt die Grenze zwischen Storage Target und Repository bei SSH-URIs?

## 11. Umsetzungsvorschlag

### Phase 1: Konzept und Datenmodell

- Repository-Objektmodell festlegen.
- Migrationsplan finalisieren.
- API-Vertrag entwerfen.

### Phase 2: Read-only Repository-Inventar

- Repositorys aus bestehenden Jobs ableiten.
- Repository-Liste anzeigen.
- Keine Änderung am Job-Wizard.

### Phase 3: Migration und Job-Verknüpfung

- `repositories.json` einführen.
- Jobs mit `repository_key` ergänzen.
- Systemzustand um Repository-Prüfungen erweitern.

### Phase 4: Wizard-Integration

- Job-Wizard nutzt Repository-Auswahl.
- Neues Repository wird über den Storage-/Repository-Wizard erzeugt.

### Phase 5: Aufräumen

- Alte direkte Repository-Pfad-Eingabe nur noch als erweiterter Modus.
- Doppelte Repository-Auflösung reduzieren.
