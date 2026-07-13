# Migration strukturierter Job-Quellpfade

## Zweck

Migration `job_source_paths_v1` stellt vorhandene Job-Metadaten auf
Job-Schema 3 um. Quellpfade werden danach ausschließlich als JSON-Liste
gespeichert:

```json
{
  "schema_version": 3,
  "source_paths": [
    "/mnt/cache/isos/Intel UHD Graphics 630 - Treiber",
    "/mnt/user/appdata"
  ]
}
```

Das alte Feld `paths.default` enthielt einen einzelnen String. Weil Leerzeichen
dort zugleich Bestandteil eines Pfadnamens und Trennzeichen mehrerer Pfade sein
konnten, war das Format nicht eindeutig.

## Ablauf

1. Die Migration läuft beim Anwendungsstart nach `canonical_data_model_v1`.
2. Alle Jobdateien werden vollständig geprüft, bevor eine davon geändert wird.
3. Vor der ersten Änderung wird der Status `pending` protokolliert.
4. Die betroffenen Originaldateien und ein Manifest werden unter
   `config/migration-backups/job_source_paths_v1-<run-id>/` gesichert.
5. Die Jobdateien werden atomar als Schema 3 geschrieben und erneut validiert.
6. Erfolg oder Fehler werden in `config/migration-state.json` und
   `config/migrations.log.jsonl` protokolliert.

Ein erfolgreicher erneuter Start führt keine zweite Änderung aus.

## Eindeutige Konvertierung

- Eine bereits vorhandene JSON-Liste wird validiert und übernommen.
- Zeilengetrennte Altwerte werden als einzelne Pfade interpretiert.
- Ein strukturell einzelner absoluter Pfad wird als genau ein Pfad übernommen,
  auch wenn er Leerzeichen enthält; dafür wird kein Mount geöffnet.
- Mehrere durch einen neuen absoluten Pfad erkennbare Werte werden nur dann
  getrennt, wenn alle erkannten Verzeichnisse existieren.
- Ein einzelner nicht vorhandener absoluter Pfad bleibt strukturell eindeutig;
  der Systemzustand meldet anschließend separat, dass die Quelle fehlt.

## Nicht eindeutig migrierbare Werte

Die Migration rät nicht. Wenn ein Altwert mehrere mögliche absolute Pfade
enthält und mindestens einer davon nicht existiert, erhält die Migration den
Status `failed`.

In diesem Fall:

- wird keine Jobdatei geändert,
- nennt der Systemzustand den betroffenen Job und die Ursache,
- bleiben Backup-Lauf und Jobbearbeitung für das alte Format gesperrt,
- kann der Betreiber die vorherige Plugin-Version wiederherstellen, den Job
  dort korrigieren und speichern und danach das Update erneut installieren.

Schlägt erst das Schreiben oder die Abschlussvalidierung fehl, werden alle
bereits geänderten Jobdateien aus der Laufzeitsicherung zurückgeschrieben. Der
Rollback-Status und mögliche Rollback-Fehler stehen im Migrationsaudit.

## Import älterer Job-Sicherungen

Alte Job-Bundles werden ausschließlich an der Importgrenze mit derselben Logik
in Schema 3 umgewandelt. Nicht ausgewählte Jobs werden nicht geprüft oder
verändert. Ein mehrdeutiger ausgewählter Job stoppt den Import vor dem Schreiben
von Job- oder Inventardaten mit einer konkreten Fehlermeldung.

Im normalen Wizard-, Health- und Backup-Laufzeitcode existiert kein Fallback auf
`paths.default` oder `BACKUP_PATHS`.
