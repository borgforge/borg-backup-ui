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

## Branch Protection

`main` ist durch ein GitHub Branch Ruleset geschuetzt.

Erwartete Regeln:

* keine Force Pushes auf `main`
* kein Loeschen von `main`
* Aenderungen an `main` nur ueber Pull Requests
* offene PR-Konversationen muessen vor dem Merge aufgeloest sein
* Required Status Checks erst aktivieren, wenn GitHub Actions/CI definiert sind

Der Branch `test-channel` ist ein Sonderbranch und wird nicht durch dieselben
Regeln wie `main` geschuetzt. Er wird ausschliesslich ueber
`./plugin/deploy-test.sh <version>` aktualisiert.

## Sprache und Kommunikation

Die direkte Kommunikation mit dem Repository-Maintainer erfolgt auf Deutsch.

GitHub-Artefakte werden auf Englisch formuliert:

* Issue-Titel und Issue-Beschreibungen
* Pull-Request-Titel und Pull-Request-Beschreibungen
* Commit-Messages
* Review-Kommentare
* Labels und Milestones

Ausnahmen nur, wenn der Nutzer ausdruecklich Deutsch fuer ein GitHub-Artefakt
verlangt.

Oeffentliche Installations- oder Release-URLs werden nicht in README-Dateien
oder oeffentlicher Nutzerdokumentation beworben, bis die Veroeffentlichung ueber
Unraid Community Apps freigegeben ist. Vorher erforderlich sind insbesondere
Zweisprachigkeit Deutsch/Englisch und definierte manuelle Maintests auf einem
frischen System.

## Repository-Plattform

Dieses Repository wird auf GitHub betrieben.

Remote:

* origin fetch/push zeigt auf GitHub.
* Erwartetes Repository: `borgforge/borg-backup-ui`.

Codex-Regel:

* Fuer Issues und Pull Requests `gh ...` verwenden.
* Vor Remote-Arbeiten zuerst `git remote -v` pruefen.
* Wenn `origin` nicht auf GitHub zeigt oder nicht zu `borgforge/borg-backup-ui`
  passt, nachfragen statt auf einer anderen Plattform weiterzuarbeiten.

Pull Requests werden erstellt mit:

```bash
gh pr create
```

Vor Erstellung eines Pull Requests pruefen, ob bereits ein offener Pull Request
fuer den aktuellen Branch existiert.

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

Nach Abschluss eines testbaren, nutzerrelevanten Tasks muss immer zuerst eine
Test-Channel-Version erstellt und verifiziert werden:

```bash
./plugin/deploy-test.sh <version>
```

Diese Test-Channel-Version ist die Testfreigabe fuer den Repository-Maintainer.
Sie ist keine Stable- oder Release-Freigabe.

Eine Stable-Release-Version fuer `main` darf erst vorbereitet oder promoted
werden, nachdem der Nutzer den Test ausdruecklich freigegeben hat, zum Beispiel
mit einer Formulierung wie:

```text
Test erfolgreich, Release erstellen
```

Ohne diese ausdrueckliche Freigabe bleibt der PR im Status "wartet auf
Nutzertest"; es wird keine neue Stable-Release-Freigabe erstellt.

Ausnahme fuer ausdruecklich freigegebene Umbrella-Features:

* Schrittweise Teil-PRs duerfen Plugin-Code ohne Release-Artefakt aendern,
  wenn der Nutzer dies fuer das Umbrella-Feature freigegeben hat.
* Diese Ausnahme gilt fuer die Zweisprachigkeit aus Issue `#11` und fuer das
  einheitliche UI-Redesign aus Umbrella-Issue `#27`.
* Die Redesign-Teil-Issues `#28` bis `#34` werden ohne stabile Release-Version
  oder stabiles Release-Artefakt gemergt. Test-Channel-Kandidaten duerfen
  jederzeit erstellt werden und bleiben vom PR-Arbeitsstand getrennt.
* Issue `#35` erstellt zuerst einen Test-Channel-Kandidaten. Eine stabile
  Release-Version und Promotion nach `main` erfolgen erst nach ausdruecklicher
  Freigabe des Nutzers.
* Der PR muss dokumentieren, dass der Release-Build bewusst auf den finalen
  Feature-Abschluss verschoben wird.
* Preflight muss in diesem Fall explizit mit
  `BORG_UI_ALLOW_DEFERRED_RELEASE=1 ./plugin/mr-preflight.sh` ausgefuehrt
  werden.
* Bugfixes, Security-Fixes und andere Maintenance- oder Feature-Releases
  bleiben von dieser Ausnahme unberuehrt. Der finale Redesign-Release folgt dem
  Test-Channel- und Freigabeablauf aus Issue `#35`.

Unter `releases/` bleiben in `main` ausschliesslich die letzten 5
`borg-backup-ui-*.txz`-Release-Artefakte.

Wenn ein neues Release-Artefakt hinzukommt und dadurch mehr als 5 Pakete
vorhanden waeren, das aelteste Release-Artefakt im selben Release- oder
Aufraeum-PR entfernen.

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

Commits, Pull Requests, `borg-backup-ui.plg`-Eintraege und
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
* Pull Request
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
