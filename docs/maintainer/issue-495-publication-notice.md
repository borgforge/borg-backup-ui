# Issue #495: publication notice draft

Publish these notices with the eventual stable release and in the forum announcement.
This document is a draft; it does not authorize stable promotion or post to the forum.

## Deutsch

**Bitte neue Konfigurationssicherungen erstellen:** Mit dieser Version erhalten Jobs
dauerhafte IDs und speichern ihre Einstellungen direkt. Nach dem Update und der
erfolgreichen Migration bitte neue Job- und Profilexporte erstellen. Die bisherigen
Job- und Profilexporte werden beim Import abgelehnt, bevor Daten geschrieben werden.
Vorhandene Borg-Backup-Archive bleiben verwendbar und müssen nicht neu erstellt werden.

Restore-Tests verwenden für große Archive weiterhin eine Dateistichprobe in Gruppen.
Die Umschaltung richtet sich jetzt ausschließlich nach der eingestellten Archivgröße
(standardmäßig 500 GB). Die bisherige Sonderregel für die Typen `photos` und `vms`
entfällt; bei kleineren Archiven wird dadurch künftig der vollständige Dry-Run verwendet.
Die angestrebte Abdeckung beträgt standardmäßig 5 %, mit höchstens 1.000 regulären
Dateien. Verzeichnisse zählen nicht mit. Bei 100.000 Dateien entsprechen 1.000
geprüfte Dateien einer Abdeckung von 1 %.

## English

**Create fresh configuration backups:** This version gives jobs permanent IDs and
stores their effective settings directly. After updating and successfully completing
the migration, create new job and profile exports. Previous job and profile exports
are rejected before any import data is written. Existing Borg backup archives remain
usable and do not need to be recreated.

Restore tests continue to use file samples in groups for large archives. Switching
now depends only on the configured archive size (500 GB by default). The former
`photos` and `vms` type rule is removed, so smaller archives now use the full dry-run.
The default target coverage is 5%, capped at 1,000 regular files. Directories do not
count towards the sample or coverage. For 100,000 files, testing 1,000 files gives
1% coverage.
