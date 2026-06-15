# Anwenderhandbuch

Dieses Verzeichnis beschreibt die Struktur für ein ausführliches Anwenderhandbuch. Die In-App-Hilfe bleibt kurz und handlungsorientiert; das Handbuch erklärt die Anwendung vollständig mit Voraussetzungen, Schrittfolgen, Prüfpunkten und Fehlerbildern.

## Ziel

- Neue Benutzer können die Anwendung ohne Vorwissen einrichten.
- Bestehende Benutzer finden konkrete Anleitungen für häufige Aufgaben.
- Support und Entwicklung haben eine gemeinsame Referenz für Begriffe, Bedienwege und erwartetes Verhalten.
- Sichtbare UI-Änderungen werden nachvollziehbar dokumentiert.

## Abgrenzung zur In-App-Hilfe

- **In-App-Hilfe**: kurze Zusammenfassung, schnelle Orientierung, typische Fehlerbilder.
- **Handbuch**: vollständige Anleitung mit Kontext, Beispielen, Prüfschritten und Troubleshooting.
- **Technische Doku**: Entwickler- und Architekturdetails bleiben in separaten Konzept- oder Produktionsdokumenten.

## Kapitel

- [01 - Überblick und Begriffe](./01-ueberblick-und-begriffe.md)
- [02 - Installation und Update auf Unraid](./02-installation-und-update.md)
- [03 - Grundeinstellungen und Systemstatus](./03-grundeinstellungen-und-systemstatus.md)
- [04 - Profile für Speicherziele](./04-profile-fuer-speicherziele.md)
- [05 - Jobs und Wizard](./05-jobs-und-wizard.md)
- [06 - Storage und Repository-Prüfungen](./06-storage-und-repository-pruefungen.md)
- [07 - Backup-Lauf, History und Berichte](./07-backup-lauf-history-berichte.md)
- [08 - Browse, Restore und Restore Tests](./08-browse-restore-restore-tests.md)
- [09 - Import, Export, Backups und Support-Paket](./09-import-export-backups-support.md)
- [10 - Migration und Wartung](./10-migration-und-wartung.md)
- [11 - Troubleshooting](./11-troubleshooting.md)
- [12 - Betrieb und Best Practices](./12-betrieb-und-best-practices.md)

## Kapitel-Format

Jedes Handbuchkapitel sollte gleich aufgebaut sein:

- **Ziel**: Was erreicht der Benutzer nach dem Kapitel?
- **Voraussetzungen**: Was muss vorher vorhanden sein?
- **Schritte**: Konkrete Bedienfolge in der UI.
- **Ergebnis prüfen**: Woran erkennt man Erfolg?
- **Fehlerbilder**: Typische Meldungen und passende Maßnahmen.
- **Hinweise**: Sicherheits- oder Betriebsdetails, falls relevant.

## Pflege-Regel

Bei sichtbaren UI-Änderungen wird geprüft:

- Muss die kurze In-App-Hilfe angepasst werden?
- Muss ein Handbuchkapitel angepasst oder ergänzt werden?
- Ändert sich ein Begriff, Button-Name oder Bedienpfad?
- Braucht der Testplan einen manuellen Prüfschritt für die Dokumentation?
