# Release-Workflow

Dieses Repository entwickelt das Unraid-Plugin als Hauptprodukt. Praktische Tests
auf Unraid sind nur mit einer gebauten Plugin-Version sinnvoll moeglich.

## Codex-Startregel

Wenn Codex an Plugin-Code arbeitet, zuerst `AGENTS.md` und diese Datei lesen.
Danach gilt:

- Jede Aenderung braucht ein Issue, auch Kleinstkorrekturen, Doku und Tooling.
- Issue-Nummer, Nutzerwirkung und Changelog-Relevanz vor der Umsetzung klaeren.
- Codeaenderung fertigstellen und fokussiert testen.
- Changelog-Eintrag unter `###NEXT###` in `borg-backup-ui.plg` ergaenzen.
- `./plugin/build.sh` ausfuehren.
- Fuer testbare nutzerrelevante Aenderungen eine Test-Channel-Version mit
  `./plugin/deploy-test.sh <version>` erstellen und verifizieren.
- Test-Channel-PRs duerfen nicht nach `main` gemergt werden, solange die
  getestete Version nicht ausdruecklich vom Repository-Maintainer freigegeben
  wurde.
- Keine Stable-Release-Freigabe vorbereiten, bevor der Repository-Maintainer
  den Test ausdruecklich als erfolgreich freigegeben hat.
- Geaenderte Plugin-Dateien und neues `releases/borg-backup-ui-<version>.txz` im Abschluss nennen.
- Pull Request vorbereiten oder erstellen, sofern nicht explizit anders vereinbart.

Der `###NEXT###`-Block ist fuer nutzerrelevante Release Notes gedacht und soll
kurz bleiben. Technische Detailhistorie gehoert bei Bedarf nach
`docs/changelog.md`.

Changelog-Eintraege sollen Issue-Referenzen enthalten, sofern vorhanden. Die
Entscheidung, ob `borg-backup-ui.plg`, `docs/changelog.md` oder beides gepflegt
wird, richtet sich nach Nutzerwirkung und Issue-Labels.

## Branch und Pull Request

- Codex arbeitet lokal auf `main`, solange nichts anderes explizit gefordert ist.
- Fuer den eigentlichen Pull Request kann ein Feature-, Fix- oder Cleanup-Branch noetig sein.
- `main` ist die Zielbranch fuer Pull Requests.
- Vor einem Pull Request muss `./plugin/mr-preflight.sh` erfolgreich laufen.

### Voraussetzungen vor `mr-preflight.sh`

Vor dem finalen Lauf von `./plugin/mr-preflight.sh` muessen die lokalen
Branch- und Diff-Voraussetzungen bereits passen. Andernfalls scheitert der
Preflight nicht wegen eines fachlichen Problems, sondern wegen eines
vorbereitenden Workflow-Schritts.

Vorher pruefen:

```bash
git status --short --branch
git diff --stat origin/main...HEAD
```

Erwarteter Zustand:

- Arbeitsbranch ist nicht `main`.
- Es gibt ein Delta gegen `origin/main`.
- Alle gewuenschten Aenderungen sind committed.
- Es gibt keine vergessenen untracked Dateien, insbesondere keine neuen
  Screenshots, Release-Artefakte oder Doku-Dateien.
- Der Branch ist zu `origin/<branch>` gepusht und synchron.
- Bei Plugin-Code-Aenderungen sind Build-/Release-Artefakte gemaess diesem
  Workflow bereits erstellt oder bewusst durch eine genehmigte Ausnahme
  zurueckgestellt.

Typische Reihenfolge:

```bash
git status --short --branch
git add <geaenderte-dateien>
git commit -m "<english commit message>"
git push -u origin <branch>
./plugin/mr-preflight.sh
```

Wenn nach dem Preflight noch Aenderungen noetig sind, diese erneut committen,
pushen und `./plugin/mr-preflight.sh` erneut als finalen Check ausfuehren.

## Test-Channel und Go-Live

Der stabile Installationskanal zeigt auf `main`. Damit eine Version zuerst auf
einem eigenen Unraid-System getestet werden kann, gibt es zusaetzlich den
Branch `test-channel` mit einem separaten Manifest:

```text
https://raw.githubusercontent.com/borgforge/borg-backup-ui/test-channel/borg-backup-ui-test.plg
```

Der Test-Channel ist nur fuer eigene Testsysteme gedacht. Er darf unfertige
Builds enthalten und ist nicht die Freigabe fuer andere Nutzer.
Der Branch enthaelt absichtlich nur Testmanifest und Release-Paket, nicht den
kompletten Quellcode oder die komplette Git-Historie.

### Verbindlicher Test-Gate

Nach jedem abgeschlossenen testbaren Task mit nutzerrelevanter Wirkung wird
zuerst eine Test-Channel-Version erstellt. Das gilt fuer Bugfixes, Features,
UI-Aenderungen und Maintenance-Aenderungen mit Plugin-Auswirkung.

Der Ablauf ist verbindlich:

1. Implementierung abschliessen.
2. Fokussierte Tests und Preflight ausfuehren.
3. Test-Channel-Version mit `./plugin/deploy-test.sh <version>` erstellen.
4. Test-Channel-Manifest und Paket verifizieren.
5. PR vorbereiten oder aktualisieren und im Abschluss als "wartet auf
   Nutzertest" kennzeichnen.
6. Stable-Release oder Promotion nach `main` erst nach ausdruecklicher
   Nutzerfreigabe vorbereiten.

Eine gueltige Freigabe muss eindeutig sein, zum Beispiel:

```text
Test erfolgreich, Release erstellen
```

Vor dieser Freigabe ist der Test-Channel die einzige bereitgestellte Version.
Ein Merge nach `main` oder eine Stable-Release-Promotion darf nicht als
automatischer Folgeschritt erfolgen.

Wichtig: Ein offener PR, der eine Test-Channel-Version beschreibt, ist nur die
technische Vorbereitung fuer die spaetere Stable-Freigabe. Er darf erst nach
erfolgreichem Nutzertest gemergt werden. Konfliktloesungen, Rebase- oder
Merge-Arbeiten an solchen PRs duerfen keine Test-Version stillschweigend nach
`main` bringen.

Vor jedem Merge eines PRs mit Plugin-Code pruefen:

```bash
git show origin/main:borg-backup-ui.plg | grep 'ENTITY version'
git show origin/test-channel:borg-backup-ui-test.plg | grep 'ENTITY version'
```

Erwartung:

- `origin/main` zeigt weiterhin auf die letzte ausdruecklich freigegebene
  Stable-Version.
- `origin/test-channel` zeigt auf die aktuelle Testversion.
- Wenn beide Versionen gleich sind, muss klar dokumentiert sein, dass genau
  diese Version bereits freigegeben wurde.

### Testversion bereitstellen

Auf dem Arbeitsbranch:

```bash
./plugin/deploy-test.sh [version]
```

Das Skript:

- baut die aktuelle Arbeitskopie mit `plugin/build.sh`
- erzeugt `borg-backup-ui-test.plg`
- kopiert Manifest und Release-Paket in den Branch `test-channel`
- pusht den Test-Channel
- laesst den Arbeitsbranch mit den gebauten Stable-Dateien fuer den spaeteren PR stehen

Die Version kann explizit angegeben werden. Ohne Angabe wird ein Zeitstempel im
Format `YYYY.MM.DD.HHMM` verwendet.

GitHub-Fetch- oder Push-Schritte im Deploy koennen mehrere Minuten ohne neue
Konsolenausgabe laufen. Den Deploy nicht vorschnell abbrechen. Wenn unklar ist,
ob der Prozess noch laeuft, zuerst in einer zweiten Shell den Prozess- und
Remote-Zustand pruefen, statt `Ctrl-C` zu senden.

Paket-Builds sind aktuell nicht garantiert byte-identisch reproduzierbar. Ein
erneuter Build derselben Version kann daher eine andere MD5 erzeugen. Relevant
ist immer der vollstaendig abgeschlossene Deploy-Lauf:

- Nach einem erfolgreichen `deploy-test.sh` die lokal veraenderten Dateien
  `borg-backup-ui.plg` und `releases/borg-backup-ui-<version>.txz` erneut
  committen, falls das Deploy-Skript sie geaendert hat.
- Die MD5 in `borg-backup-ui.plg`, im Remote-Test-Manifest und vom Remote-Paket
  muessen identisch sein.
- Erst danach die Testversion als bereit melden.

### Go-Live vorbereiten

Nach erfolgreichem Test auf Unraid:

1. Den fuer den Release erforderlichen Umfang aus
   [`docs/manual-maintenance-tests.md`](./manual-maintenance-tests.md)
   vollstaendig mit `PASS` abschliessen und das Ergebnis dokumentieren.
2. Bei der ersten Community-Apps-Veroeffentlichung sowohl den Fresh-Install-
   als auch den Update-Durchlauf ausfuehren.
3. Arbeitsbranch pruefen und die durch den Test-Build entstandenen Dateien committen.
4. Keine neue Version bauen, damit exakt das getestete Paket freigegeben wird.
5. Go-Live-PR erstellen:

```bash
./plugin/promote-release.sh <version>
```

Das Skript pusht den aktuellen Branch und erstellt oder zeigt den passenden
Pull Request gegen `main`. Vor dem Merge muss weiterhin gelten:

```bash
./plugin/mr-preflight.sh
```

Erst der Merge nach `main` ist die Freigabe fuer den stabilen Kanal.

### Status pruefen

```bash
./plugin/release-status.sh
```

Das Skript zeigt lokale Version, `origin/main`, `origin/test-channel`, lokale
Release-Artefakte und offene Pull Requests.

### Test-Channel-Deploy pruefen

Nach jedem Test-Channel-Deploy muss das erzeugte Remote-Manifest direkt
geprueft werden:

```bash
git fetch origin test-channel
git show origin/test-channel:borg-backup-ui-test.plg
git show origin/test-channel:releases/borg-backup-ui-<version>.txz >/dev/null
```

Dabei pruefen:

- `version` entspricht der getesteten Version
- `pluginURL` zeigt auf `https://raw.githubusercontent.com/borgforge/borg-backup-ui/test-channel/borg-backup-ui-test.plg`
- `pkgurl` zeigt auf `https://raw.githubusercontent.com/borgforge/borg-backup-ui/test-channel/releases/borg-backup-ui-<version>.txz`
- `MD5` ist gesetzt und passt zum neu gebauten Paket
- `borg-backup-ui-test.plg` enthaelt keine durch `sed` verdoppelten XML-Entities

Wichtig: In `sed`-Replacement-Strings ist `&` ein Sonderzeichen fuer den
vollstaendigen Treffer. XML-Entities wie `&name;` und `&version;` muessen
escaped werden oder aus einem Template kommen.

Nach `deploy-test.sh` immer den Arbeitsbaum pruefen:

```bash
git status --short
```

Wenn der Test-Deploy nur den Test-Channel aktualisieren sollte, lokale
Stable-Build-Dateien wie `borg-backup-ui.plg`, `borg_backup_ui.py` und
`releases/borg-backup-ui-<version>.txz` nicht ungeprueft in einen PR uebernehmen.

Nach erfolgreichem Test-Channel-Deploy zusaetzlich pruefen:

```bash
git fetch origin main test-channel
git show origin/main:borg-backup-ui.plg | grep 'ENTITY version'
git show origin/test-channel:borg-backup-ui-test.plg | grep 'ENTITY version'
git show origin/test-channel:borg-backup-ui-test.plg | grep '<MD5>'
git show origin/test-channel:releases/borg-backup-ui-<version>.txz | md5sum
```

Die Test-Channel-Version und die MD5 muessen zusammenpassen. `origin/main` muss
weiterhin auf der letzten freigegebenen Stable-Version bleiben, solange keine
explizite Stable-Freigabe vorliegt.

Wenn ein PR-Konflikt geloest wird, danach erneut diese Main/Test-Channel-Pruefung
durchfuehren. Ein Konflikt-Fix darf weder die Stable-Version erhoehen noch
Test-Code nach `main` bringen, ausser der Maintainer hat genau diese Version
freigegeben.

## Wann ist ein Build erforderlich?

Ein neuer Plugin-Build ist erforderlich, sobald Plugin-Code geaendert wird.
Dazu zaehlen insbesondere:

- `borg_backup_ui.py`
- `api/*.py`
- `runtime/**`
- `ui/**`
- `plugin/*.page`
- `plugin/rc.borg_backup_ui`
- `borg_backup_ui.conf.example`
- `borg-backup-ui.plg`

In diesem Fall ausfuehren:

```bash
./plugin/build.sh
```

### Deferred release build for approved umbrella features

The default rule remains strict: plugin-code changes require a release build in
the same branch.

For explicitly approved umbrella features, incremental pull requests may defer
the release build until the feature is complete. This is intended for large
user-facing work that would otherwise create half-finished release artifacts.

Current approved umbrella feature:

- German and English localization, tracked by issue `#11`
- unified UI redesign, tracked by umbrella issue `#27`

Rules for deferred release-build PRs:

- Use one branch and one PR per sub-issue.
- Keep `main` functional after every merge.
- Do not update `borg-backup-ui.plg`, `borg_backup_ui.py`, or
  `releases/borg-backup-ui-*.txz` solely to create a partial feature release.
- Document in the PR that the release build is intentionally deferred.
- Run preflight explicitly with:

```bash
BORG_UI_ALLOW_DEFERRED_RELEASE=1 ./plugin/mr-preflight.sh
```

Redesign-specific sequence:

- Merge incremental redesign issues `#28` through `#34` without a stable
  release version or stable release artifact.
- Test-channel candidates may be deployed at any time during the redesign. The
  generated stable build files must be removed from the incremental PR branch
  after the remote test-channel manifest and package have been verified.
- In issue `#35`, build and deploy a test-channel candidate first.
- Create and promote the stable release only after the user explicitly approves
  the tested candidate.

Bug fixes, security fixes, and unrelated maintenance or feature releases must
still include the normal changelog, build, release artifact, and test-channel
workflow. The final redesign release follows the approval sequence above.

Fuer neue Releases muss `borg-backup-ui.plg` genau einen `###NEXT###`-Block
enthalten. `plugin/build.sh` ersetzt diesen Block durch die neue Version und
bricht ab, wenn dadurch doppelte Changelog-Versionen entstehen wuerden.

Fuer Rebuilds einer bereits getesteten Version darf `###NEXT###` fehlen, wenn
der passende `###<version>###`-Block bereits im Changelog vorhanden ist.

Der Build aktualisiert typischerweise:

- `borg_backup_ui.py`
- `borg-backup-ui.plg`
- `releases/borg-backup-ui-<version>.txz`

Diese Dateien gehoeren dann mit in denselben Commit oder zumindest in denselben
Branch, damit der PR auf Unraid installierbar und testbar ist.

## Wann ist kein Build erforderlich?

Kein neuer Plugin-Build ist erforderlich bei reinen Repo- oder
Dokumentationsaenderungen, zum Beispiel:

- `docs/**`
- `AGENTS.md`
- `.gitignore`
- Analyse- und Konzeptdokumente
- Tests oder Preflight-Skripte ohne Aenderung am ausgelieferten Plugin-Code
- Entfernen von versehentlich getrackten Build- oder Bytecode-Artefakten

## Release-Artefakt-Aufbewahrung

Im Repository werden nur die letzten 5 Plugin-Release-Pakete unter `releases/`
behalten. Aeltere `borg-backup-ui-*.txz`-Artefakte sollen in einem
Aufraeum-PR entfernt werden, sobald neuere Releases erfolgreich getestet und
gemergt sind.

## Preflight

`./plugin/mr-preflight.sh` prueft:

- nicht auf `main` oder `master` zu arbeiten
- Python-Syntax
- `pytest -q`
- Delta gegen `origin/main`
- Release-Build-Regel fuer Plugin-Codeaenderungen
- ob der Branch auf GitHub existiert
- ob lokaler und remote Branch synchron sind
