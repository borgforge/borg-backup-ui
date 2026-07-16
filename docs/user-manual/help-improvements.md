# Help and UI Improvement Review

Status: 2026-07-16  
Issue: #236

This review records wording and contextual-help improvements discovered while rebuilding the bilingual in-app help and user manual. It does not change the documented product behavior.

## Deutsch

### Prioritaet Hoch

| Bereich | Beobachtung | Empfehlung |
| --- | --- | --- |
| Repository erstellen | Verschluesselungsarten sind sicherheitsrelevant, ihre Folgen sind im Assistenten aber nur knapp sichtbar. | Info-Icon neben **Verschluesselung** mit Hinweis, ob nur eine Passphrase oder zusaetzlich ein Keyfile fuer Disaster Recovery benoetigt wird. Link direkt zum Handbuchabschnitt. |
| Repository-Wartung | **Check**, **Daten pruefen**, **Prune** und **Compact** koennen fuer Einsteiger wie gleichwertige Reparaturaktionen wirken. | Pro Aktion ein kurzer Quick-Hint: Zweck, ungefaehre Last, moegliche Dauer und ob Daten/Archive geloescht werden koennen. |
| Restore-Konflikte | **Nicht ueberschreiben**, **Ersetzen** und **Umbenennen** haben unmittelbare Auswirkungen auf bestehende Dateien. | Kontextkarte in Schritt 4 mit einem konkreten Dateibeispiel je Strategie. **Ersetzen** visuell als riskante Option kennzeichnen. |
| Werkseinstellungen | Die Funktion ist korrekt stark abgesichert, die genaue Trennung zwischen Plugin-Installation, externer Repository-Ablage und geloeschten Betriebsdaten muss vor der ersten Bestaetigung klar sein. | Vor der Sicherheitskette eine kompakte Liste **Wird geloescht / Bleibt erhalten** anzeigen. |
| Support-Paket | `sanitized` kann als anonym missverstanden werden. | Direkt am Erstellen-Button: **Secrets werden maskiert. Das Paket ist nicht anonym und muss vor der Weitergabe geprueft werden.** |

### Prioritaet Mittel

| Bereich | Beobachtung | Empfehlung |
| --- | --- | --- |
| Restore-Testlevel | `L1`, `L2` und `L3` sind ohne Kontext nicht selbsterklaerend. | Info-Icon mit Prueftiefe, typischer Dauer und I/O-Auswirkung. In der Auswahlliste Kurzbeschreibung nach dem Level anzeigen. |
| Reminder-Diagnose | **Erwarteter Lauf**, **Ueberfaellig ab**, **Gesendet** und **Naechster Reminder** sind fachlich korrekt, aber ohne Berechnungsregel schwer zu deuten. | Oberhalb der Tabelle die aktuell wirksame Formel als Satz zeigen, zum Beispiel: *Geplanter Lauf + 6 Stunden Toleranz; danach alle 24 Stunden.* |
| Speicherziel vs. Repository | Neue Nutzer verwechseln Basispfad, Repository-Verzeichnis und vollstaendigen Repository-Pfad. | Einheitliche Begriffe und ein kleines Pfadbeispiel: `Speicherziel /mnt/backup` + `Verzeichnis borg-appdata` = `Repository-Pfad /mnt/backup/borg-appdata`. |
| Docker-/VM-Steuerung | Bei selektiver Steuerung ist die Auswirkung im Startdialog wichtiger als die technische Konfiguration. | Im Startdialog Anzahl und Namen der tatsaechlich zu stoppenden laufenden Ziele zeigen; lange Listen einklappbar halten. |
| Migration | **angewendet** und **keine Aktion erforderlich** sind technisch korrekt, beantworten aber nicht immer, ob Nutzerdaten geaendert wurden. | Detailzeile mit betroffenen Objekten, Backup-Pfad und Link auf das strukturierte Audit-Log. |

### Prioritaet Niedrig

- Fachbegriffe wie *Retention*, *Offsite*, *Deduplizierung* und *Append-only* beim ersten Auftreten mit einem kurzen Tooltip erklaeren.
- Leere Tabellen nicht nur mit `-`, sondern mit einem kurzen Grund anzeigen, beispielsweise **Noch kein Lauf vorhanden**.
- Fehlerbanner mit Request-ID sollten eine direkte Aktion **Support-Paket erstellen** oder **Technische Details kopieren** anbieten.
- Zeitangaben konsistent als Datum plus Uhrzeit und bei langen Laufzeiten zusaetzlich als relative Dauer darstellen.

### Modulare Integration

1. Das vollstaendige Handbuch unter `docs/user-manual/` ist die kanonische Langform.
2. `ui/docs/help.md` und `ui/docs/help.en.md` bleiben aufgabenorientierte Kurzfassungen in derselben Kapitelstruktur.
3. Jede H2-Ueberschrift ist ein stabiles Hilfethema. Die Funktion `openHelpTopic(topicId)` kann spaeter von Info-Icons und Dialogen aufgerufen werden.
4. Seitenspezifische Quick-Hints bleiben kurz und verlinken auf das passende Hilfethema, statt Inhalte mehrfach zu pflegen.
5. Jede neue sichtbare Funktion benoetigt im Review eine Entscheidung zu Handbuch, In-App-Hilfe, Quick-Hint und Screenshot.
6. Deutsch und Englisch werden in Tests auf gleiche Kapitelstruktur und vorhandene Ressourcen geprueft.

## English

### High Priority

| Area | Observation | Recommendation |
| --- | --- | --- |
| Create repository | Encryption modes have security consequences, but the wizard shows only limited guidance. | Add an info icon next to **Encryption** explaining whether disaster recovery needs only a passphrase or an additional keyfile. Link to the manual section. |
| Repository maintenance | **Check**, **Verify Data**, **Prune**, and **Compact** can appear to beginners as equivalent repair actions. | Add a short quick hint for every action: purpose, expected load, possible duration, and whether data or archives can be removed. |
| Restore conflicts | **Do not overwrite**, **Replace**, and **Rename** directly affect existing files. | Show a contextual card in step 4 with one concrete file example per strategy. Present **Replace** as the risk-bearing choice. |
| Factory reset | The workflow is correctly protected, but the difference between plugin installation, external repositories, and deleted operational data must be clear before confirmation starts. | Show a concise **Will be deleted / Will remain** list before the confirmation chain. |
| Support bundle | Users may mistake `sanitized` for anonymous. | Display next to the action: **Secrets are masked. The bundle is not anonymous and must be reviewed before sharing.** |

### Medium Priority

| Area | Observation | Recommendation |
| --- | --- | --- |
| Restore test levels | `L1`, `L2`, and `L3` are not self-explanatory. | Add an info icon describing verification depth, expected duration, and I/O impact. Include a short description in the selector. |
| Reminder diagnostics | **Expected run**, **Overdue at**, **Sent**, and **Next reminder** are accurate but hard to interpret without the calculation. | Show the active formula above the table, for example: *Scheduled run + 6 hours tolerance; repeat every 24 hours.* |
| Storage target vs. repository | New users confuse base path, repository directory, and full repository path. | Use consistent terminology and show an example: `target /mnt/backup` + `directory borg-appdata` = `repository path /mnt/backup/borg-appdata`. |
| Docker/VM control | For selective control, the start dialog must communicate the actual effect more clearly than the configuration detail. | Show count and names of the running targets that will actually be stopped; keep long lists collapsible. |
| Migration | **applied** and **no action required** do not always tell users whether data changed. | Add affected objects, backup path, and a link to the structured audit log. |

### Low Priority

- Explain terms such as *retention*, *offsite*, *deduplication*, and *append-only* on first use.
- Replace bare empty values with a short reason such as **No run recorded yet**.
- Error banners with a request ID should offer **Create support bundle** or **Copy technical details**.
- Use a consistent date-time format and add a relative duration for long-running operations.

### Modular Integration

1. The complete manual under `docs/user-manual/` is the canonical long-form source.
2. `ui/docs/help.md` and `ui/docs/help.en.md` remain task-oriented summaries with the same chapter structure.
3. Every H2 heading is a stable help topic. The `openHelpTopic(topicId)` function can later be called by info icons and dialogs.
4. Page-level quick hints stay concise and link to the matching topic instead of duplicating long content.
5. Every new visible feature requires an explicit review decision for the manual, in-app help, quick hint, and screenshot.
6. Tests verify equal German and English chapter structure and resource completeness.
