# 12 - Betrieb und Best Practices

## Ziel

Dieses Kapitel beschreibt empfohlene Betriebsabläufe für verlässliche Backups.

## Neuer Job

1. Speicherziel-Profil vorbereiten.
2. Repository erstellen oder importieren.
3. Job im Wizard anlegen und Repository auswählen.
4. Vorschau prüfen.
5. Manuell starten.
6. History prüfen.
7. Repository-Informationen und bei Bedarf Wartungsstatus prüfen.
8. Restore-Test einplanen.
9. Erst danach Zeitplan produktiv verwenden.

## Regelmäßige Prüfungen

- Sidebar-Systemstatus regelmäßig beachten.
- Restore Tests nicht dauerhaft überfällig lassen.
- Nach Updates einen manuellen Lauf durchführen und Repository-Informationen
  aktualisieren.
- History auf wiederkehrende Warnungen prüfen.
- Berichte auf Laufzeit- und Größenänderungen prüfen.

## Secrets

- Passphrases und Keys nicht in Tickets, Screenshots oder Chat-Nachrichten kopieren.
- Secret-Dateien restriktiv berechtigen.
- Verschlüsselte Exporte für Umzüge verwenden.
- Support-Paket statt manuell zusammengestellter Diagnose verwenden.

## Updates

- Release-Version notieren.
- Nach Update Systemstatus prüfen.
- Migrations- und Wartungspunkte lesen.
- Bei größeren Änderungen erst einen Testjob oder weniger kritischen Job prüfen.

## Aufräumen

- Nicht mehr genutzte Jobs deaktivieren oder löschen.
- Profile erst löschen, wenn kein Job sie mehr verwendet.
- Cleanup-Kandidaten in `backup.conf` bewusst bearbeiten.
- Alte Config-Backups nur löschen, wenn ein aktueller Rückfallpunkt vorhanden ist.

## Ergebnis prüfen

Der Betrieb ist stabil, wenn Backups regelmäßig laufen, Restore Tests erfolgreich sind, offene Systempunkte zeitnah geprüft werden und Secrets kontrolliert verwaltet bleiben.
