# AGENTS.md - borg-backup-ui (Unraid Plugin)

## Repository Scope

Dieses Repository ist vollstaendig eigenstaendig.

Alle fuer dieses Repository notwendigen Informationen befinden sich innerhalb dieses Repositories.

Treffe keine Annahmen ueber weitere Repositories, Services oder zukuenftige Architekturvarianten.

Arbeite ausschliesslich mit dem vorhandenen Code, der vorhandenen Dokumentation und den Anweisungen in diesem Repository.

---

## Zweck dieses Repositories

Dieses Repository ist die eigenstaendige Entwicklungs- und Produktionslinie fuer das Unraid-Plugin `borg-backup-ui`.

Das Plugin wird aktiv fuer Unraid weiterentwickelt und gepflegt.

---

## Rolle in der Architektur

Dieses Repository verantwortet:

* Unraid-Plugin-Funktionalitaet
* Unraid-spezifische Integration
* Benutzeroberflaeche
* Packaging
* Release-Erstellung
* Upgrade-Pfade fuer bestehende Nutzer

Neue Funktionen duerfen implementiert werden, sofern sie mit der bestehenden Architektur vereinbar sind.

---

## Erlaubte Aenderungen

* Bugfixes
* Security-Fixes
* Performance-Verbesserungen
* Verbesserte Fehlermeldungen
* Logging-Verbesserungen
* Wartungsarbeiten
* UI-Anpassungen
* Unraid-Integrationen
* Plugin-Manifest-Anpassungen
* Build- und Packaging-Anpassungen
* Neue Funktionen fuer das Unraid-Plugin

---

## Architekturregeln

Bewahre die bestehende Architektur.

Keine groesseren Refactorings ohne ausdrueckliche Freigabe.

Insbesondere keine:

* Framework-Wechsel
* FastAPI-Migration
* Datenbank-Migration
* API-Breaking-Changes
* Plugin-Layout-Aenderungen
* Grossflaechigen Verzeichnisumbauten
* Automatischen Modernisierungen

Wenn eine Architekturentscheidung unklar ist:

* Bestehendes Verhalten bevorzugen
* Rueckwaertskompatibilitaet bevorzugen (ggf. Nachfragen weil nicht jede Funktion Rueckwaertskompatibel sein muss)
* Nachfragen statt spekulieren

---

## Sicherheitsregeln

Niemals:

* Zugangsdaten committen
* Secrets in Logs ausgeben
* Secrets in Changelogs ausgeben
* Secrets in Releases ausgeben
* Nutzerdaten ohne Freigabe loeschen
* Borg-Repositories ohne Freigabe loeschen
* Konfigurationsdateien automatisch ueberschreiben

Sicherheitsrelevante Aenderungen muessen minimal-invasiv erfolgen.

---

## Arbeitsverzeichnis

Arbeite ausschliesslich innerhalb:

git/borg-backup-ui

Verwende keine temporaeren Arbeitsverzeichnisse ausserhalb des Repositories.

Arbeite insbesondere nicht in:

* /tmp
* zufaelligen Clone-Verzeichnissen
* separaten Test-Repositories

---

## Git-Regeln

Keine destruktiven Git-Kommandos ohne ausdrueckliche Freigabe.

Insbesondere nicht:

* git reset --hard
* git checkout --
* git clean -fd
* git push --force

Vor Arbeiten mit Remotes:

```bash
git fetch --prune origin
```

Immer den aktuellen Stand von `origin/main` beruecksichtigen.

Bereits gemergte Branches nicht weiterverwenden.

---

## Pull-Request-Regeln

Nach Codeaenderungen Pull Request vorbereiten oder erstellen, sofern nicht explizit anders vereinbart.

## Repository-Plattform

Dieses Repository wird aktuell auf GitLab betrieben.

Remote:

* origin fetch/push zeigt auf GitLab.

Codex-Regel:

* Wenn `origin` auf GitLab zeigt: `glab mr ...` verwenden.
* Wenn `origin` auf GitHub zeigt: `gh pr ...` verwenden.
* Bei Unklarheit zuerst `git remote -v` pruefen und nachfragen.

Falls GitHub verwendet wird:

```bash
gh pr create
```

Falls GitLab verwendet wird:

```bash
glab mr create
```

Vor Erstellung eines Pull Requests bzw. Merge Requests pruefen, ob bereits ein offener Request fuer den aktuellen Branch existiert.

Beschreibungen ASCII-sicher formulieren:

* keine typografischen Sonderzeichen
* Bulletpoints mit "-"

---

## Build- und Release-Regeln

Vor Abschluss jeder Codeaenderung:

```text
docs/release-workflow.md
```

lesen und befolgen.

Wenn Plugin-Code geaendert wurde:

1. Changelog unter `###NEXT###` pflegen
2. `./plugin/build.sh` ausfuehren
3. Release-Artefakt aktualisieren
4. Release-Ergebnis pruefen

Unter `releases/` bleiben in `main` ausschliesslich die letzten 5
`borg-backup-ui-*.txz`-Release-Artefakte.

Wenn ein neues Release-Artefakt hinzukommt und dadurch mehr als 5 Pakete
vorhanden waeren, das aelteste Release-Artefakt im selben Release- oder
Aufraeum-MR entfernen.

---

## Issue-Regeln

Alle Aenderungen laufen ueber ein Issue.

Das gilt auch fuer Kleinstkorrekturen, Dokumentation, Build-/Tooling-Aenderungen
und reine Wartungsarbeiten.

Vor Beginn einer Aenderung muss klar sein:

* Issue-Nummer
* Ziel der Aenderung
* Nutzerwirkung
* Changelog-Relevanz

Wenn kein passendes Issue existiert, zuerst ein Issue erstellen oder den Nutzer
bitten, ein Issue anzulegen.

Commits, Merge Requests, `borg-backup-ui.plg`-Eintraege und
`docs/changelog.md`-Eintraege sollen die Issue-Nummer nennen, sofern vorhanden.

Empfohlene Labels/Tags:

* `type::bug`
* `type::feature`
* `type::security`
* `type::maintenance`
* `type::docs`
* `impact::user-visible`
* `impact::internal`
* `release-note::yes`
* `release-note::no`
* `area::<bereich>`

---

## Changelog-Regeln

`borg-backup-ui.plg` enthaelt nur nutzerrelevante Release Notes fuer das
Plugin-Manifest.

Eintraege unter `###NEXT###` muessen kurz und installationsnah sein.

In `borg-backup-ui.plg` gehoeren:

* sichtbare Features
* wichtige Bugfixes
* Security-Fixes
* geaenderte Nutzerablaeufe
* Upgrade-, Migrations- oder Kompatibilitaetshinweise
* Aenderungen aus Issues mit `release-note::yes`
* Aenderungen aus Issues mit `impact::user-visible`

Nicht in `borg-backup-ui.plg` gehoeren:

* interne Refactorings ohne Nutzerwirkung
* reine Test-, CI- oder Build-Details
* Codex-/Agenten-Arbeitsnotizen
* kleine technische Zwischenkorrekturen ohne Nutzerwert
* Aenderungen aus Issues mit `release-note::no`, sofern keine Nutzerwirkung
  vorliegt

Ausfuehrlichere technische Historie kann in `docs/changelog.md` gepflegt
werden.

Das Manifest-Changelog soll regelmaessig gekuerzt werden, sodass nur die
letzten nutzerrelevanten Releases im Plugin-Manifest bleiben. Aeltere Eintraege
koennen in `docs/changelog.md` archiviert werden.

---

## Test-Channel-Regeln

Der Branch `test-channel` ist kein normaler Entwicklungsbranch.

Er enthaelt ausschliesslich:

* borg-backup-ui-test.plg
* zugehoerige Release-Pakete

Deploys ausschliesslich ueber:

```bash
./plugin/deploy-test.sh <version>
```

Nach jedem Deploy pruefen:

```bash
git fetch origin test-channel
git show origin/test-channel:borg-backup-ui-test.plg
```

Verifizieren:

* Version
* pluginURL
* pkgurl
* MD5

---

## Mindesttests

Nach jeder Aenderung:

* Python-Code ohne Syntaxfehler
* API-Endpunkte starten
* Plugin-Seiten laden
* Bestehende Backup-Jobs bleiben funktionsfaehig

Zusatztests durchfuehren, wenn die Aenderung dies erfordert.

Falls Tests nicht moeglich sind:

* Begruendung dokumentieren

---

## Abschlussbericht

Vor Abschluss nennen:

* Branch
* Commit
* Pull Request oder Merge Request
* Release-Version
* Testergebnis
* Preflight-Ergebnis
* Verbleibender git status

---

## GitHub-Konfiguration

Für dieses Repository kann optional eine lokale GitHub-Konfigurationsdatei verwendet werden:

```text
/env/github_borg-backup-ui.env
```

Diese Datei befindet sich außerhalb des Repositorys und darf niemals in Git eingecheckt werden.

Sie kann Informationen wie folgende enthalten:

* GitHub Organisation
* Repository-Name
* SSH-Remote
* GitHub Token für borg-codex-bot
* Standard-Branch

Die Datei dient ausschließlich lokalen Entwicklungs- und Automatisierungszwecken.

## borg-codex-bot

Der Benutzer `borg-codex-bot` darf für dieses Repository verwendet werden.

Erlaubt:

* Issues erstellen und aktualisieren
* Pull Requests erstellen und aktualisieren
* Kommentare auf Issues und Pull Requests erstellen
* Branches für Entwicklungsarbeiten anlegen
* Änderungen committen und pushen

Nicht erlaubt:

* Direktes Arbeiten auf `main`
* Direktes Pushen auf `main`
* Löschen von Repositorys
* Ändern von Repository-Einstellungen
* Umgehen des Pull-Request-Prozesses

## Entwicklungsworkflow

Änderungen erfolgen grundsätzlich nach folgendem Ablauf:

1. Bestehendes Issue verwenden oder neues Issue erstellen
2. Feature-Branch anlegen
3. Implementierung durchführen
4. Tests ausführen
5. Pull Request erstellen
6. Nach Review mergen

Direkte Änderungen auf `main` sind nicht zulässig.

---

## Definition of Done

Die Aufgabe ist abgeschlossen wenn:

* keine Regression erkennbar ist
* Rueckwaertskompatibilitaet erhalten bleibt
* notwendige Dokumentation aktualisiert wurde
* Build erfolgreich war
* relevante Tests erfolgreich waren
* Release-Schritte erledigt oder begruendet wurden
* Arbeitsverzeichnis sauber dokumentiert ist
* offene Punkte explizit genannt wurden
