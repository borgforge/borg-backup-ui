# Plan fuer zweisprachige Dokumentation

Dieses Dokument definiert den deutschen und englischen Dokumentationsumfang
fuer Borg Backup UI vor einer Veroeffentlichung ueber Unraid Community Apps.
Es ist die verbindliche Abgrenzung fuer Issue `#22` und das
Lokalisierungs-Umbrella-Issue `#11`.

## Ziele

- Bedienungsrelevante Dokumentation ist auf Deutsch und Englisch verfuegbar.
- Begriffe und Bedienpfade stimmen mit der zweisprachigen UI ueberein.
- Bestehende deutsche Links bleiben gueltig.
- Interne Entwickler- und Release-Dokumentation muss nicht kuenstlich doppelt
  gepflegt werden.
- Oeffentliche Installations- und Release-URLs werden erst nach bestandener
  Veroeffentlichungsfreigabe publiziert.

## Aktueller Stand

| Bereich | Aktuelle Sprache | Oeffentlich/nutzerrelevant | Entscheidung |
|---|---|---:|---|
| `ui/docs/help.md` | Deutsch | ja, in der UI | Englisch ergaenzen und sprachabhaengig laden |
| `docs/handbuch/*.md` | Deutsch | ja | Englische Spiegelstruktur ergaenzen |
| `docs/README.md` | Englisch | teilweise | Deutschen Einstieg ergaenzen |
| `docs/manual-maintenance-tests.md` | Deutsch | nein, Maintainer | Deutsch bleibt ausreichend |
| `docs/release-workflow.md` | Deutsch | nein, Maintainer | Deutsch bleibt ausreichend |
| `docs/i18n-konzept-ui-und-logs.md` | Deutsch | nein, Konzept | Deutsch bleibt ausreichend |
| `docs/changelog.md` | historisch gemischt | nein, technische Historie | Nicht rueckwirkend uebersetzen |
| `AGENTS.md` | Deutsch | nein, Arbeitsanweisung | Nicht uebersetzen |
| `borg-backup-ui.plg` | Englisch/Release-Metadaten | Distribution | Im finalen Release separat pflegen |

Die Bestandspruefung fuer Issue `#22` hat keine konkrete oeffentliche
Installations- oder Release-URL in `docs/README.md`, `docs/handbuch/**` oder
`ui/docs/help.md` gefunden. Der interne Test-Channel in
`docs/release-workflow.md` ist Maintainer-Dokumentation und keine oeffentliche
Installationsanleitung.

## Verbindlicher Umfang vor Community Apps

### 1. In-App-Hilfe

Pflichtumfang:

- Deutsche Kurzhilfe bleibt unter `ui/docs/help.md` als bestehender Fallback
  erhalten.
- Eine inhaltlich gleichwertige englische Kurzhilfe wird unter
  `ui/docs/help.en.md` ergaenzt.
- Die Hilfe-Seite laedt anhand von `borg-backup-ui.language` beziehungsweise
  der aktiven i18n-Komponente die passende Datei.
- Unbekannte oder nicht ladbare Sprachen fallen auf Deutsch zurueck.
- Ein Sprachwechsel aktualisiert die bereits geoeffnete Hilfe ohne manuellen
  Browser-Reload.
- Links, Bilder, Codebeispiele und Sicherheitshinweise bleiben in beiden
  Sprachfassungen inhaltlich gleichwertig.

Die In-App-Hilfe ist ausgelieferter Plugin-Code. Ihre Umsetzung benoetigt die
fuer Plugin-Code geltenden Tests und Release-Schritte beziehungsweise die fuer
Issue `#11` genehmigte Deferred-Release-Regel.

### 2. Anwenderhandbuch

Die vorhandenen deutschen Pfade unter `docs/handbuch/` bleiben bestehen, damit
bestehende Links nicht brechen. Englisch wird ohne Verzeichnisumbau ergaenzt:

```text
docs/handbuch/README.md             # deutscher Einstieg, Sprachlink zu EN
docs/handbuch/01-...md              # bestehende deutsche Kapitel
docs/handbuch/en/README.md          # englischer Einstieg, Sprachlink zu DE
docs/handbuch/en/01-...md           # englische Spiegelkapitel
```

Pflichtumfang:

- Alle zwoelf bestehenden Kapitel erhalten eine englische Spiegeldatei mit
  demselben Dateinamen.
- Der deutsche und englische Einstieg verlinken gegenseitig aufeinander.
- Kapitelreihenfolge, Abschnittszweck, Sicherheitswarnungen und Bedienablauf
  bleiben inhaltlich gleichwertig.
- UI-Bezeichnungen verwenden die Begriffe aus `ui/i18n/de.json` und
  `ui/i18n/en.json`; technische Schluessel, Pfade und maschinenlesbare Werte
  werden nicht uebersetzt.
- Screenshots sind entweder sprachneutral oder werden als DE/EN-Paar gepflegt.
- Es werden keine Installations- oder Release-URLs aufgenommen, solange das
  Veroeffentlichungs-Gate nicht freigegeben ist.

### 3. Oeffentlicher Dokumentationseinstieg

`docs/README.md` bleibt der englische technische Einstieg. Vor Community Apps
wird `docs/README.de.md` als deutscher Einstieg ergaenzt. Beide Einstiege:

- verlinken sichtbar auf die jeweils andere Sprache,
- verlinken auf den passenden Handbuch-Einstieg,
- beschreiben Voraussetzungen, Zweck und unterstuetzte Funktionsbereiche
  inhaltlich gleichwertig,
- enthalten vor Freigabe keine konkrete Installations- oder Release-URL.

Eine kuenftige Repository-Startseite darf diese beiden Einstiege verlinken,
aber die URL-Sperre nicht umgehen.

### 4. Community-Apps- und Installationsinformationen

Diese Inhalte werden erst im gesonderten Publikationsschritt erstellt oder
veroeffentlicht:

- Community-Apps-Template und Kurzbeschreibung,
- oeffentliche Installationsanleitung,
- stabile Plugin-Installations-URL,
- Support-, Projekt- und Dokumentationslinks,
- gegebenenfalls Screenshots fuer das Listing.

Die Community-Apps-Kurzbeschreibung muss Englisch enthalten. Eine deutsche
Beschreibung oder ein klarer deutscher Dokumentationslink wird zusaetzlich
bereitgestellt. Installationsschritte muessen in beiden Sprachen denselben
Voraussetzungen- und Sicherheitshinweis enthalten.

## Nicht erforderliche Uebersetzungen

Folgende Inhalte duerfen in ihrer aktuellen Arbeitssprache bleiben:

- Arbeitsanweisungen und interne Konzepte,
- Build-, Preflight-, Test-Channel- und Release-Workflow-Dokumentation,
- manuelle Maintest-Protokolle,
- technische Changelog-Historie bestehender Releases,
- Commit-, Issue- und Pull-Request-Texte,
- technische Log-, E-Mail-, Report- und Benachrichtigungsausgaben, die gemaess
  Produktentscheidung ausschliesslich Englisch sind,
- unveraenderte Ausgaben externer Werkzeuge wie Borg, SSH oder Unraid.

Diese Abgrenzung verhindert doppelten Pflegeaufwand ohne Nutzen fuer die
Bedienung des Plugins.

## Pflege- und Paritaetsregeln

Nach Umsetzung der Folge-Issues gelten diese Regeln:

1. Eine nutzerrelevante Dokumentationsaenderung aktualisiert Deutsch und
   Englisch im selben Pull Request.
2. Ist eine sofortige Doppelpflege begruendet nicht moeglich, blockiert ein
   verlinktes Folge-Issue die naechste oeffentliche Veroeffentlichung.
3. Handbuchdateien muessen zwischen Deutsch und Englisch dieselbe Dateimenge
   und Kapitelnummerierung besitzen.
4. Die In-App-Hilfe muss fuer jede unterstuetzte UI-Sprache eine ladbare Quelle
   oder den dokumentierten deutschen Fallback besitzen.
5. Interne Links und referenzierte Bilder werden automatisiert oder im
   Preflight geprueft.
6. Der Maintest aus `docs/manual-maintenance-tests.md` prueft beide Sprachen,
   Login/Hilfe und die wichtigsten Bedienpfade auf einem frischen System.
7. Geheimnisse, echte Zugangsdaten und produktive Repository-Pfade gehoeren in
   keine Sprachfassung.

## Veroeffentlichungs-Gate fuer URLs

Konkrete oeffentliche Installations- oder Release-URLs duerfen erst in README,
Handbuch, In-App-Hilfe oder Community-Apps-Metadaten aufgenommen werden, wenn
alle folgenden Punkte erfuellt sind:

1. In-App-Hilfe ist auf Deutsch und Englisch verfuegbar.
2. Handbuch und oeffentlicher Dokumentationseinstieg sind auf Deutsch und
   Englisch verfuegbar.
3. Fresh-Install- und Update-Durchlauf aus
   `docs/manual-maintenance-tests.md` sind fuer exakt den Release-Kandidaten mit
   `PASS` dokumentiert.
4. Der finale Release fuer Issue `#11` wurde gebaut, ueber den Test-Channel
   installiert und erfolgreich geprueft.
5. Version, Paket, Manifest und MD5 stimmen zwischen Test und Promotion
   ueberein.
6. Der Maintainer hat die Community-Apps-Veroeffentlichung ausdruecklich
   freigegeben.

Vor Erfuellung aller Punkte bleiben interne Test-Channel-Informationen auf
Maintainer-Dokumente beschraenkt.

## Folgearbeiten

Die Umsetzung wird bewusst getrennt, damit ausgelieferte UI-Hilfe,
umfangreiches Handbuch und Publikationsmetadaten unabhaengig geprueft werden
koennen:

- In-App-Hilfe lokalisieren und Sprachwechsel testen: Issue `#54`.
- Englisches Handbuch und deutschen Dokumentationseinstieg ergaenzen:
  Issue `#53`.
- Community-Apps-Metadaten und oeffentliche Installationsdokumentation erst
  nach bestandenem Gate vorbereiten: Issue `#55`.
