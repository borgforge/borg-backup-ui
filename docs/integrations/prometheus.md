# Prometheus and Grafana / Prometheus und Grafana (#534)

## English

Borg Backup UI contains an optional exporter. Enable it under **Settings >
Integrations > Prometheus & Grafana**. It is disabled by default. No Node Exporter,
Borg exporter script, Borg upgrade or additional plugin listener is required.
Prometheus and Grafana run separately, for example in containers.

1. Enable metrics and copy the newly generated read-only bearer token. It is
   displayed only on creation/replacement; normal settings responses never reveal it.
2. Copy the configuration shown in settings into Prometheus. If `scrape_configs`
   already exists, append the job below that existing key. Use the plugin address
   reachable **from Prometheus**, not the container's own `localhost`.
3. Reload Prometheus and verify that the target is UP.
4. Download the dashboard from settings, import it into Grafana, and select the
   Prometheus data source. Use the server, location, repository and job filters.

The included **Borg Backup UI · Backup Overview** template uses the approved V4
layout: an embedded plugin icon, active-job names near the top, equally sized
job cards, storage-efficiency panels, and consolidated backup/recovery tables
followed by repository inventory. It needs no additional Grafana plugins.
The **Dashboard data** checks show whether information could be read, independently
of whether a backup or restore test succeeded.

To update an existing standard dashboard, import the newly downloaded JSON and
confirm replacement of the dashboard with UID `borg-backup-ui`. Export any local
customizations first. The separate preview dashboards use different UIDs and
remain unchanged. The dashboard language is English; setup guidance in the
plugin is available in German and English.

**Running now** follows exporter, scrape and dashboard refresh intervals; short
operations can finish between samples. **No active jobs** requires a reachable
exporter, successful runtime collection and a snapshot less than three minutes
old. Missing data does not mean idle. Select one server at a time; location,
repository and job filters support multiple selections. The Job filter applies
to job/archive/restore panels, while repository totals follow the Repository and
Location filters. History starts when Prometheus begins collecting.

Example (replace the address and token):

```yaml
scrape_configs:
  - job_name: borg-backup-ui
    scrape_interval: 60s
    scrape_timeout: 30s
    metrics_path: /metrics
    scheme: http
    authorization:
      type: Bearer
      credentials: YOUR_PROMETHEUS_TOKEN
    static_configs:
      - targets: ['unraid.example:8765']
```

For production, Prometheus also accepts `credentials_file` instead of
`credentials`. Protect the configuration/token like a password and use HTTPS
through a trusted reverse proxy across untrusted networks. Tokens in URLs are
not supported. The token grants only access to `/metrics`; it cannot run backups,
change settings, read logs or access the Homepage widget. The normal API token
and browser session cannot replace this token.

Disabling metrics immediately makes `/metrics` return 404; it preserves the token
for re-enabling. Replacing the token invalidates its predecessor immediately.
Revoking removes the token and disables metrics. Settings survive restarts and
plugin updates in `config/.prometheus-exporter.json` (mode 0600, also included in
the existing secret-permission check). Like the Homepage token, it is not included
in configuration transfers: set up new credentials on a destination server.
This integration requires no data migration and does not change backup jobs.

### Data and interpretation

The endpoint reads existing plugin metadata only, with a 60-second process-memory
cache. It does not execute Borg, contact repositories, mount storage, rewrite
status files or create inventory lock files. Reading status/report files can
still access the disk holding those files once per cache refresh. With the
integration disabled, no metrics collection occurs. Regular application access
logging still follows its configured verbosity.

- Job metrics carry `job_id`, `job_name`, `location` and `repository`. Repository
  metrics carry `repository`, `repository_name` and `location`. Prometheus adds
  `instance` and its own `job` label. Archive names, file paths, credentials and
  free-form errors are deliberately absent.
- All exported metrics are **gauges**, including one-hot result/state series.
  They describe current snapshots, not cumulative event counters. A short run
  can finish between scrapes; use plugin History for the complete run history.
- `bbui_backup_last_result` describes the most recent result. Its states include
  success, warning, error, skipped, cancelled and unknown. A failed/skipped run
  does not reset `bbui_backup_last_success_timestamp_seconds` or replace the
  last archive's statistics with zero. Success lookup is limited to the status
  history still retained by the plugin.
- Archive statistics have a separate `bbui_backup_archive_timestamp_seconds`.
  Deduplicated archive bytes are newly stored bytes for that archive. Repository
  `deduplicated_bytes` represents cached `unique_csize`, not filesystem free space.
- Repository values remain cached until the normal repository refresh updates
  them. `bbui_repository_refresh_timestamp_seconds` is the **last attempt**, so
  read it together with `bbui_repository_refresh_result`. A failed attempt can
  leave older statistics in place. Repository metadata is not a live mount check.
- Restore evidence and overdue flags follow the existing plugin policy. The next
  configured test occurrence is separate from the evidence expiry. A configured
  schedule does not guarantee execution; installation, locks and storage availability
  still matter. Test levels do not prove full application recovery.
- Missing timestamps/statistics are omitted, not fabricated as zero. `unknown`
  and `never` expose missing evidence. An unreadable collector emits
  `bbui_collector_success{collector="..."} 0` and omits that section's samples.
  Check collector health as well as Prometheus `up`; HTTP 200 alone does not mean
  that every collector succeeded. Recovery/maintenance mode returns HTTP 503.
- `bbui_metrics_generated_timestamp_seconds` exposes snapshot freshness.
  Prometheus history starts when scraping is configured; old plugin history is
  not automatically backfilled. Grafana dashboard 14516 expects another exporter's
  schema; use the dashboard supplied with Borg Backup UI.

### Manual acceptance test

Verify disabled/authenticated/unauthenticated access, revoke and replace the
token, then restart the plugin and confirm the setting persists. Test jobs with
success, error, skipped and no prior run; check restore evidence and planned dates.
Import the dashboard, select a server/job/location/repository and compare values
with plugin History and repository information. Verify that normal backups and
restore tests still work while Prometheus scrapes. Confirm the refreshed dashboard
shows a failed collector or unreachable plugin distinctly from a healthy backup.

## Deutsch

Unter **Einstellungen > Integrationen > Prometheus & Grafana** kann der eingebaute
Exporter aktiviert werden. Standardmäßig ist er aus. Prometheus und Grafana werden
separat betrieben; ein zusätzlicher Exporter ist nicht erforderlich.

1. Metriken aktivieren und das neue, ausschließlich lesende Token kopieren.
2. Die angezeigte Konfiguration in Prometheus ergänzen. Eine bereits vorhandene
   `scrape_configs`-Liste erweitern, nicht ein zweites Mal anlegen. Die Serveradresse
   muss aus Prometheus erreichbar sein; `localhost` im Container zeigt auf den Container.
3. In Prometheus prüfen, dass das Ziel als UP angezeigt wird.
4. Das Dashboard aus den Einstellungen herunterladen, in Grafana importieren und
   die Prometheus-Datenquelle auswählen. Nach Server, Ort, Repository und Job filtern.

Die mitgelieferte Vorlage **Borg Backup UI · Backup Overview** verwendet das
freigegebene V4-Layout: eingebettetes Plugin-Icon, aktive Jobs im oberen Bereich,
gleich große Job-Kacheln, Speichereffizienz und zusammengeführte Backup-/Restore-
Tabellen mit anschließendem Repository-Inventar. Zusätzliche Grafana-Plugins sind
nicht erforderlich. **Dashboard data** zeigt, ob Informationen gelesen werden
konnten; erfolgreiche Backups und Restore-Tests werden separat ausgewiesen.

Zum Aktualisieren eines vorhandenen Standard-Dashboards die neu heruntergeladene
JSON-Datei importieren und das Ersetzen des Dashboards mit der UID
`borg-backup-ui` bestätigen. Eigene Anpassungen vorher exportieren. Die separaten
Vorschau-Dashboards verwenden andere UIDs und bleiben erhalten. Das Dashboard
ist englischsprachig; die Einrichtungshinweise im Plugin gibt es auf Deutsch
und Englisch.

**Running now** folgt den Intervallen von Exporter, Prometheus und Dashboard;
kurze Vorgänge können zwischen zwei Abfragen liegen. **No active jobs** setzt
einen erreichbaren Exporter, erfolgreich gelesene Laufzeitdaten und einen weniger
als drei Minuten alten Datenstand voraus. Fehlende Daten bedeuten keinen
Leerlauf. Es wird jeweils ein Server ausgewählt; Standort, Repository und Job
erlauben Mehrfachauswahl. Der Job-Filter gilt für Job-/Archiv-/Restore-Panels;
Repository-Summen folgen den Filtern Repository und Location. Verlaufsdaten
entstehen erst ab Beginn der Prometheus-Erfassung.

Das Token wird nur beim Erzeugen/Ersetzen vollständig angezeigt. Deaktivieren
sperrt den Endpunkt sofort, behält das Token aber für eine spätere Aktivierung.
Ersetzen macht das alte Token ungültig; Widerrufen entfernt es und deaktiviert
Metriken. Einstellung und Token bleiben bei Neustarts und Updates erhalten.
Konfigurationsexporte enthalten dieses Token nicht. Auf einem anderen Server muss
es neu eingerichtet werden. Über nicht vertrauenswürdige Netze HTTPS verwenden.

Die Messwerte stammen aus vorhandenen Daten und werden für 60 Sekunden im
Arbeitsspeicher gehalten. Abfragen starten keine Borg-Befehle und schreiben keine
Statusdateien. Das Lesen der Status- und Testberichte kann auf den Datenträger
zugreifen, auf dem diese Dateien gespeichert sind. Ausgeschaltet erfolgt keine
Metrikerfassung. Die normale Zugriffsprotokollierung richtet sich weiterhin nach
der eingestellten Ausführlichkeit.

Fehlende Daten werden nicht als erfolgreiche Sicherung oder Größe null dargestellt.
Der letzte erfolgreiche Lauf und die letzten Archivwerte bleiben nach einem Fehler
oder übersprungenen Lauf erkennbar, solange die zugehörigen Statusdateien aufbewahrt
werden. Repository-Zahlen können älter sein; der angezeigte Aktualisierungszeitpunkt
bezeichnet den letzten Versuch und muss zusammen mit dessen Ergebnis gelesen werden.

Der nächste geplante Restore-Test und die Gültigkeit des Testnachweises sind
unterschiedliche Angaben. Termine garantieren keine Ausführung, etwa bei einem
belegten Repository. Testlevel bestätigen keine vollständige Anwendungswiederherstellung.

Prometheus speichert den Verlauf ab Beginn seiner Erfassung. Alte Plugin-Verläufe
werden nicht nachträglich importiert. Die Metriken sind Momentaufnahmen, keine
vollständige Liste aller Läufe. Dafür bleibt die History zuständig. Das mitgelieferte
Dashboard zeigt auch Erreichbarkeit, Erfassungsfehler und Alter der Messwerte.
