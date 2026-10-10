# Praktische Pre-/Post-Skripte (#557)

[English](README.md)

Sechs eigenstaendige Bash-Vorlagen fuer **Einstellungen > Skripte > Importieren
(.sh)**. Die Dateien liegen im Repository und werden nicht automatisch installiert
oder aktiviert. Jede Vorlage funktioniert ohne gemeinsame Hilfsdateien. Vor dem
Einsatz muessen die Einstellungen und Voraussetzungen zum eigenen System passen.

| Datei | Zweck | Vorschlag fuer Hook-Timeout |
| --- | --- | --- |
| [pre-check-source.sh](pre-check-source.sh) | Mount, Quellpfad und Kennungsdatei pruefen | 30 s |
| [pre-check-free-space.sh](pre-check-free-space.sh) | Freien Platz auf einem vorhandenen Staging-Mount pruefen | 30 s |
| [pre-wake-server.sh](pre-wake-server.sh) | Bei Bedarf Wake-on-LAN senden und TCP-Port abwarten | 150 s |
| [pre-dump-mariadb.sh](pre-dump-mariadb.sh) | Eine MariaDB-Datenbank im Docker-Container exportieren | 1800 s |
| [pre-dump-postgresql.sh](pre-dump-postgresql.sh) | Eine PostgreSQL-Datenbank im Docker-Container exportieren | 1800 s |
| [post-json-webhook.sh](post-json-webhook.sh) | Job-ID und Ergebnis vor Post an eigenen HTTPS-Empfaenger melden | 30 s |

## Import und Einrichtung

1. Vorlage und Anleitung lesen. Die reine `.sh`-Datei als UTF-8 speichern, nicht
   die HTML-Seite des Repositories. Die Bash-Shebang bleibt in der ersten Zeile.
2. Datei importieren und die Konstanten am Anfang anpassen. Keine Passwoerter
   oder Tokens in den Editor schreiben: Skripte lassen sich exportieren.
3. Erst nach Einrichtung der Voraussetzungen `CONFIGURED="yes"` setzen.
   Unveraenderte Vorlagen brechen mit Exitcode 2 vor der eigentlichen Aktion ab.
4. Aussagekraeftigen Namen und Timeout setzen, speichern und in Wizard-Schritt 9
   zuordnen. Der Import uebertraegt weder Beschreibung noch Timeout; die Tabelle
   liefert Startwerte, die fuer grosse Exporte angepasst werden muessen.
5. Mit einem Testjob pruefen, Log und Archiv kontrollieren und Datenbank-Dumps
   testweise wiederherstellen. Erst danach die Zeitplanung aktivieren.

Pro Job gibt es genau eine Pre- und eine Post-Auswahl. Mehrere importierte
Vorlagen werden nicht automatisch nacheinander ausgefuehrt. Fuer kombinierte
Ablaeufe ein gemeinsames Skript mit ausdruecklicher Fehlerbehandlung erstellen,
beispielsweise eine Platzpruefung vor einem Dump. Ganze Dateien mit ihren eigenen
Guards und Traps nicht einfach aneinanderhaengen.

## Verhalten der vorhandenen Hooks

- Pre laeuft nach der anfaenglichen Jobsperre, aber vor Netzwerk-Mounts,
  Container-/VM-Stopps, Repositoryvorbereitung und Backup. Fehler oder Timeout
  verhindern das Backup. Mount-Pruefungen eignen sich deshalb fuer Quellen, die
  Unraid oder der Administrator bereits eingebunden hat.
- Post laeuft nach Wiederherstellung der Dienste, Repositorywartung/-statistik
  und Freigaben-Cleanup. Jobsperren bestehen noch; Abschlussstatus und
  Benachrichtigungen folgen erst danach.
- Beim Webhook **Auch bei Fehler, Ueberspringen oder Abbruch** waehlen. Post kann
  nach fehlgeschlagenem Pre laufen. Bei anfaenglichem Sperrkonflikt laeuft kein Hook.
- Verfuegbar sind `BBUI_JOB_ID`, `BBUI_HOOK_PHASE` und fuer Post `BBUI_JOB_RESULT`.
  Borg-Zugangsdaten werden nicht geerbt. Auf Unraid laufen Hooks normalerweise
  mit root-Rechten.
- "Bei Erfolg" schliesst Borg-Warnungen ein. Ein Post-Fehler setzt den Gesamtjob
  auf Fehler, auch wenn bereits ein Archiv existiert. Der Webhook meldet das
  Ergebnis **vor Post**, keinen endgueltigen Abschluss oder Wiederherstellungsnachweis.
- Post hat einen Timeout, ist aber nicht ueber die UI abbrechbar. Keine Prozesse
  im Hintergrund starten. Das Beenden von lokalem `docker exec` garantiert nicht,
  dass der Prozess im Container ebenfalls beendet wurde. Nach abgebrochenen Dumps
  vor einem neuen Versuch auf weiterlaufende Exportprozesse pruefen.

## Quellenkennung und Speicherplatz

`MOUNT_PATH` muss der echte Mountpunkt sein, nicht irgendein Unterordner.
`SOURCE_PATH` darf dieser Mountpunkt oder ein Unterverzeichnis sein. Dort eine
kleine regulaere Datei `.backup-source-id` mit einer eindeutigen Textkennung
anlegen und dieselbe Kennung in `EXPECTED_ID` eintragen. Das Skript legt keine
Kennungsdatei an und mountet nichts. Ein abschliessender Zeilenumbruch ist erlaubt.
Die Kennung erkennt versehentlich falsche Quellen, ist aber kein kryptografischer
Identitaetsnachweis. Ein Mount kann nach der Pruefung verschwinden; die Vorlage
sperrt das Dateisystem nicht.

Die Platzpruefung vergleicht verfuegbare KiB aus `df` mit `MIN_FREE_GIB`. Den
wirklich verwendeten lokalen Dump-/Staging-Mount angeben. Die Pruefung reserviert
keinen Platz, schaetzt keine Backupgroesse und kontrolliert keine Remote-Quota.
Sie ersetzt keine Unraid-Share-/Pool-Pruefung: Ein zusammengefasster User-Share
kann andere Werte liefern als der Pool oder die Platte, die eine Datei aufnimmt.

## Wake-on-LAN

Benoetigt `python3` mit Standardbibliothek, einen fuer WOL eingerichteten Zielhost
und ein Netzwerk, das den Broadcast zulaesst. MAC mit Doppelpunkten, numerische
IPv4-Adressen, TCP-Port und Wartezeit einstellen. Das Skript installiert keine
Pakete und aendert keine Netzwerkeinstellungen. Ist der TCP-Port bereits offen,
wird kein Paket gesendet. Andernfalls wird einmal ein UDP-Magic-Packet an Port 9
gesendet. Hook-Timeout einige Sekunden ueber `WAIT_SECONDS` setzen. Ein offener
TCP-Port beweist weder Authentifizierung noch Bereitschaft einer konkreten Freigabe.

Ein allgemeines Abschaltskript ist bewusst nicht enthalten. Ein einzelner Hook
kann nicht verlaesslich erkennen, ob andere Jobs, Nutzer oder Rechner den Server
noch benoetigen oder ob dieser Job ihn ueberhaupt aufgeweckt hat. Gemeinsame
Nutzung benoetigt eine eigene Koordination (siehe Repository-Issue #89).

## Datenbank-Dumps

Auf dem Host werden Bash, Docker-CLI, `mountpoint`, `realpath`, `stat`, `mktemp`
und uebliche Unix-Werkzeuge benoetigt. Der laufende Container muss den passenden
Dump-Client enthalten. Voraussetzungen werden nicht automatisch installiert.

Ein vorhandenes privates Ausgabeverzeichnis mit Modus `0700` und Eigentum des
Hook-Nutzers (normalerweise root) **unterhalb des konfigurierten Mountpunkts**
einrichten. Auch uebergeordnete Verzeichnisse duerfen nicht fuer unberechtigte
Nutzer schreibbar sein. Dauerhaften Speicher mit ausreichend Platz verwenden,
nicht den Unraid-Bootstick. Dieses Verzeichnis ausdruecklich als Backupquelle
aufnehmen und Ausschluesse kontrollieren. Ein erzeugter Dump ist nicht automatisch
Bestandteil eines Archivs.

Jeder Lauf erzeugt ein eigenes privates Verzeichnis und schreibt `dump.partial`.
Erst ein erfolgreicher, nicht leerer Export wird zu `database.sql` beziehungsweise
`database.dump` umbenannt. Bei normalen Fehlern und behandelten Signalen entfernt
das Skript nur seine eigene Teildatei und das leere Laufverzeichnis. Vorhandene
fertige Exporte bleiben bestehen; keine automatische Loeschung oder Ueberschreibung.
Eine getrennte Aufbewahrung fuer lokale Dumps planen: Borg-Prune entfernt diese
Dateien nicht. Ein harter Prozessabbruch oder Hostausfall kann Teildateien
hinterlassen; manuell kontrollieren. Andere Backupjobs sollen dieses Verzeichnis
nicht gleichzeitig waehrend eines Exports sichern. Dumps enthalten sensible Daten.

Client-Fehlerausgaben werden unterdrueckt, damit Verbindungsdetails nicht im
Joblog landen. Fehler nennen die betroffene Aktion. Fuer genauere Diagnose den
Client separat in einer geschuetzten Administrator-Sitzung pruefen.

### MariaDB

Container, Datenbank und `CLIENT_CONFIG` einstellen. Letzteres ist eine absolute
Optionsdatei **im Container**, separat eingerichtet und nur fuer den vorgesehenen
Container-Nutzer lesbar. Im Abschnitt `[client]` stehen die benoetigten
Backup-Zugangsdaten. Der Container muss `mariadb-dump` bereitstellen; die Vorlage
ersetzt ihn nicht automatisch durch MySQL-Werkzeuge und liest keine Passwoerter
aus der Containerumgebung aus.

Der Aufruf verwendet `--single-transaction --quick --skip-lock-tables --databases`.
Die Konsistenz setzt transaktionale Tabellen wie InnoDB und keine gleichzeitigen
Schemaaenderungen voraus. Fuer MyISAM oder andere nichttransaktionale Tabellen
wird keine konsistente Sicherung zugesichert. Gespeicherte Routinen/Events,
Datenbankkonten/Berechtigungen und die Abstimmung mit Anwendungsdateien sind nicht
Teil dieser Vorlage. Benoetigte Objekte und Wiederherstellung konkret pruefen.

### PostgreSQL

Container, Datenbank, Datenbanknutzer und `PGPASS_FILE` einstellen. Die Passwortdatei
liegt **im Container**, ist fuer dessen Ausfuehrungsnutzer lesbar und hat die von
PostgreSQL geforderten restriktiven Rechte (normalerweise `0600`). Der Client nutzt
TCP `127.0.0.1`, die libpq-Porteinstellungen des Containers beziehungsweise deren
Standard und `--no-password`; die Passwortdatei muss dazu passen. Die Vorlage
akzeptiert einfache Datenbanknamen, keine Verbindungs-URI. `pg_dump --format=custom`
exportiert eine Datenbank; mit passenden PostgreSQL-Werkzeugen (`pg_restore`)
die Wiederherstellung pruefen. Clusterrollen/Tablespaces und Konsistenz mit
externen Anwendungsdateien sind nicht enthalten. Weitere libpq-Einstellungen
im Container bleiben wirksam.

## Allgemeiner Post-Webhook

Benoetigt `curl` und `python3`. Eine vertrauenswuerdige regulaere curl-Konfigurationsdatei
mit Modus `0600` im Eigentum des Hook-Nutzers unter geschuetzten Verzeichnissen
anlegen. Sie darf **nur eine HTTPS-`url` und optionale Authentifizierungs-`header`**
enthalten. Echte Zugangsdaten separat einrichten und nicht ins Skript uebernehmen.
Nicht funktionsfaehiges Schema mit Platzhaltern:

```text
url = "https://monitor.example.invalid/backup-result"
header = "Authorization: Bearer REPLACE_LOCALLY"
```

Es werden keine anbieterspezifischen URL-Endungen ergaenzt. Der Empfaenger muss
HTTP-POST mit `Content-Type: application/json` und diesem Format verstehen:

```json
{"job_id": "example-job", "result": "warning"}
```

Moegliche Ergebnisse: `success`, `warning`, `failed`, `cancelled`, `skipped`.
Warnungen beim Empfaenger getrennt von fehlerfreiem Erfolg behandeln. Nur HTTP
2xx gilt als zugestellt. Keine Weiterleitungen oder Wiederholungsversuche;
Verbindungs-Timeout 5 Sekunden, Gesamtdauer maximal 20 Sekunden. Antwortinhalte
und curl-Fehler werden nicht geloggt. Trotz Timeout kann der Empfaenger die Meldung
bereits angenommen haben; dies beim Empfaenger beruecksichtigen. Die Vorlage ist
nicht direkt mit jedem Monitoring-Anbieter kompatibel. Ausgebliebene Laeufe erkennt
der Empfaenger nur mit eigener erwarteter Zeitplanung beziehungsweise Frist.

## Vorschlag zur Bereitstellung und Tests

Als ersten Schritt diese versionierten Einzeldateien mit zweisprachiger Anleitung
verwenden. Spaeter koennte eine Vorlagenauswahl im Plugin eine Kopie als ungespeicherten
Entwurf oeffnen. Dadurch bleiben eigene Anpassungen und Jobzuordnungen getrennt
von mitgelieferten Beispielen. Automatisches Befuellen des Skriptbestands und ein
gehostetes Downloadangebot sind nicht Bestandteil von #557.

Automatische Tests pruefen den echten Import und fuehren die Vorlagen mit simulierten
Docker-, Dateisystemabfrage- und curl-Befehlen sowie isolierter Socket-Simulation
fuer WOL aus. Fehlerhafte/leere Exporte, Erhalt vorhandener Dumps, ungueltige
Ergebnisse, fehlende Mounts, falsche Kennungen und Zustellfehler werden ohne externe
Nebenwirkungen geprueft. Aufruf:

```bash
mkdir -p .release-tmp/hook-tests
TMPDIR="$PWD/.release-tmp/hook-tests" pytest -q tests/test_practical_job_hooks.py --basetemp="$PWD/.release-tmp/hook-tests/pytest"
```

Echte Unraid-Mounts, Hardware-WOL, Datenbankinhalte/Wiederherstellung und ein echter
Empfaenger bleiben manuell zu testen. Der Paketbau kopiert diese Sammlung nicht
ins Plugin; ein Test-Channel-Paket wuerde die Dateien nicht ausliefern. Deshalb
werden diese Beispiele per manuellem Import getestet. Kein Stable-Release in
diesem Schritt.
