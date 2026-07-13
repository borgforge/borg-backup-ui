# Konzept: Repository-Objekte als auswählbare Ziele

- Issue: #184
- Status: Umgesetzt mit Issues #184 und #187
- Stand: 2026-07-11

## 1. Zusammenfassung

Die aktuelle Anwendung ist in vielen Bereichen job-zentriert: Ein Backup-Job
enthält seine Quelle, sein Ziel, seine Repository-Konfiguration und seine
Ausführungsregeln. Für technisch versierte Nutzer ist das nachvollziehbar, für
neue Nutzer wirkt es aber ungewohnt. Sie erwarten häufig diesen Ablauf:

1. Speicherziel einrichten.
2. Repository erstellen oder vorhandenes Repository importieren.
3. Backup-Job anlegen und Repository auswählen.

Die Anwendung verwaltet Borg-Repositories deshalb als eigene, auswählbare
Objekte. Jobs erzeugen keinen Repository-Pfad mehr, sondern referenzieren ein
vorhandenes Repository über dessen stabile ID.

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

## 3. Ausgangszustand vor Umsetzung

Vor Issue #184/#187 lagen repository-relevante Informationen an mehreren
Stellen:

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
| `storage_key` | stabile technische ID, z. B. `storage_storagebox_5bf81d53` |
| `storage_type` | `local`, `usb`, `smb`, `ssh`, später `rclone` |
| `location` | UI-/Job-Kategorie wie `local`, `usb`, `smb`, `storagebox` |
| `display_name` | sichtbarer Name |
| `profile_key` | bisherige Profil-ID während der Migration, z. B. `storage-1` |
| `base_path` | Basis-Pfad des Speicherziels |
| `mount_path` | lokaler Mount-Pfad, falls vorhanden |
| `host`, `port`, `user` | SSH-/Storagebox-Verbindungsdaten ohne Secrets |
| `server`, `share` | SMB-Zieldaten ohne Passwort |
| `ssh_key_path` | Pfad zum SSH-Key, kein Key-Inhalt |
| `mount_mode` | none, managed, external |
| `status` | letzter Verbindungs-/Mount-Status |

### 4.2 Repository

Ein Repository beschreibt ein konkretes Borg-Repository auf einem Storage Target.

Mögliche Felder:

| Feld | Bedeutung |
| --- | --- |
| `repository_key` | stabile technische ID mit Hash-Suffix, z. B. `repo_appdata_usb_7f3c45ab` |
| `display_name` | sichtbarer Name |
| `storage_key` | Referenz auf Storage Target |
| `repository_name` | Name des Borg-Repositories, z. B. `borg-backup-appdata` |
| `relative_path` | relativer Repository-Pfad auf dem Storage |
| `relative_path` | kanonischer Pfad relativ zum Storage Target |
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
  "schema_version": 3,
  "job_key": "appdata_usb",
  "source_paths": ["/mnt/user/appdata"],
  "repository_key": "repo_appdata_usb_7f3c45ab"
}
```

Der Job speichert ausschließlich `repository_key`. Repository-Pfad,
Verschlüsselung und Passphrase-Verweis werden zur Laufzeit aus dem
Repository-Objekt aufgelöst; Storage- und Profilinformationen stammen über
`storage_key` aus dem Storage-Objekt. Die früheren Jobfelder `repo`,
`passphrase`, `encryption` sowie direkte Storage-/Profil-Keys werden einmalig
migriert und danach entfernt.

Quellpfade sind ab Job-Schema 3 ausschließlich als JSON-Liste gespeichert.
Dadurch bleiben Leerzeichen Bestandteil eines einzelnen Pfades und werden nicht
mehr als Trennzeichen interpretiert. Das frühere Objekt `paths` und die
Laufzeitvariable `BACKUP_PATHS` werden nach der einmaligen Migration nicht mehr
verwendet.

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

## 6. Umgesetzte Migration

Da die Anwendung noch nicht öffentlich über Community Apps veröffentlicht ist,
sollte keine dauerhafte Legacy-Parallelwelt aufgebaut werden. Trotzdem dürfen
vorhandene Tester-Daten nicht verloren gehen.

Die Baseline-Migration `canonical_data_model_v1` führt folgende Schritte
idempotent aus:

1. Alle Job-Metadaten lesen.
2. Für jeden eindeutigen Repository-Pfad oder jede eindeutige URI ein
   Repository-Objekt erzeugen.
3. Storage-Typ und Profil aus Job-Location, Profil-Key und Repo-URI ableiten.
4. Job um `repository_key` ergänzen.
5. Alte Repository-, Passphrase-, Verschlüsselungs- und Profilfelder aus den
   Job-Metadaten entfernen.
6. Übergangsfelder aus dem Repository-Inventar entfernen, nachdem Storage- und
   Repository-Objekte vollständig verknüpft sind.
7. Das Endmodell vollständig validieren.
8. Erst nach erfolgreicher Validierung die obsolete `settings.json` entfernen.
9. Migration und Cleanup im zentralen Migrationslog protokollieren.

Beispiel:

```json
{
  "migration_id": "canonical_data_model_v1",
  "status": "applied",
  "actions": [
    "created repository repo_appdata_usb_7f3c45ab from job appdata_usb",
    "linked job appdata_usb to repo_appdata_usb_7f3c45ab"
  ]
}
```

Unterstützte Ausgangszustände sind der aktuelle Stable-Stand mit Legacy-Jobs,
teilweise migrierte Testinstallationen und bereits kanonische Installationen.
Bestehende kanonische Storage- und Repository-IDs bleiben erhalten. Vor der
ersten Änderung wird unter `config/migration-backups/` ein Lauf-Backup erstellt.
Schlägt eine Phase oder die Abschlussvalidierung fehl, werden die betroffenen
Dateien zurückgespielt und der Fehler samt Phase und Rollback-Ergebnis im Audit
protokolliert.

Wichtig: Die Migration darf keine Borg-Repositories initialisieren, löschen oder
verändern. Sie erstellt und bereinigt nur UI-Metadaten.

## 7. Datenablage

Repository-Objekte werden getrennt von Jobs und allgemeinen Einstellungen
gespeichert:

```text
/boot/config/borg-backup/config/repositories.json
```

Storage Targets liegen entsprechend in `storages.json`. Effektive lokale Pfade
oder SSH-URIs werden zur Laufzeit aus `storage_key` und `relative_path`
aufgelöst und nicht redundant persistiert.

Allgemeine Anwendungseinstellungen verbleiben in `backup.conf`. Eine separate
`settings.json` ist nach erfolgreicher Baseline-Migration nicht mehr Bestandteil
des Datenmodells.

Der kompakte aktuelle Zustand steht in `config/migration-state.json`. Der
append-only Audit mit Lauf-ID, Phasen, Objektänderungen, Validierung und
Rollback-Ergebnis steht in `config/migrations.log.jsonl`. Die früheren
Teil-Migrations-IDs können bei Testinstallationen als historische Einträge
vorhanden bleiben, steuern aber keine neuen Läufe mehr und werden in der
normalen Systemzustandsansicht ausgeblendet.

## 8. API-Vertrag

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/api/repositories` | Repositorys listen |
| GET | `/api/repositories/browse` | Verzeichnisse innerhalb eines kanonischen Speicherziels fuer den Repository-Import auflisten |
| POST | `/api/repositories` | Repository anlegen/importieren |
| POST | `/api/repositories/test` | Repository testen |
| DELETE | `/api/repositories` | Repository entfernen oder Borg-Daten nach doppelter Bestätigung löschen |

Löschregel:

- Ein Repository-Objekt darf nicht gelöscht werden, wenn Jobs es verwenden.
- Das reine Entfernen des UI-Objekts löscht keine Borg-Daten.
- Das physische Löschen ist eine getrennte, auditierte Aktion mit doppelter
  Bestätigung und nur ohne Job-Verwendung möglich.

## 9. Auswirkungen auf bestehende Bereiche

### 9.1 Job-Wizard

Der Wizard zeigt eine Repository-Auswahl an:

- vorhandenes Repository auswählen
- neues Repository über Storage-/Repository-Wizard erstellen
- vorhandenes Repository importieren

### 9.2 Repositories

Die Seite **Repositories** gruppiert Repositorys nach Speicherziel und bietet
Informationen, Archive, Wartung und Verwaltung pro Repository. Storage-Profile
werden getrennt unter **Einstellungen** verwaltet.

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

## 10. Verbindliche Architektur

- Jobs speichern ausschließlich `repository_key` als Repository-Verweis.
- Repositorys speichern `storage_key`, `relative_path`, Verschlüsselung und
  Secret-/Keyfile-Verweise.
- Storage Targets speichern Verbindung, Basis-Pfad und Profilinformationen.
- Borg-Laufzeitpfade werden zentral aufgelöst.
- Alte Job- und Repository-Vertragsfelder werden nur innerhalb einmaliger
  Migrationen gelesen; produktive APIs akzeptieren sie nicht.
