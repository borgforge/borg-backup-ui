# 06 - Storage und Repository-Prüfungen

## Ziel

Dieses Kapitel erklärt den Unterschied zwischen Profiltest, Job-Check und Repository-Test.

## Drei Arten von Prüfungen

- **Profiltest**: Prüft, ob ein SMB- oder SSH-Profil grundsätzlich nutzbar ist.
- **Job-Check**: Prüft schnell lokale Plausibilität, z. B. Profilreferenz, URI-Syntax, Quellpfade und Passphrase-Datei.
- **Repository-Test**: Prüft den Zugriff auf das konkrete Borg-Repository.

## Storage-Seite verwenden

1. **Storage** öffnen.
2. Zielbereich wählen.
3. Bei SMB zuerst Mount-Status prüfen.
4. Falls nötig mounten.
5. Repository-Test ausführen.
6. Details lesen, wenn der Test fehlschlägt.

## SMB-Besonderheiten

Ein SMB-Repository kann nur sinnvoll getestet werden, wenn das SMB-Ziel gemountet ist. Ein vorhandenes Profil reicht dafür nicht aus.

## SSH-Besonderheiten

Ein erfolgreicher SSH-Profiltest bedeutet, dass Verbindung und Basiszugriff funktionieren. Das konkrete Job-Repository kann trotzdem fehlen oder einen anderen Pfad haben.

## Borg-Check

Ein Borg-Check ist intensiver als ein einfacher Zugriffstest. Er sollte bewusst eingesetzt werden, weil er je nach Repository-Größe länger laufen kann.

## Ergebnis prüfen

Ein Repository gilt als erreichbar, wenn der Repo-Test erfolgreich ist und Details keine Authentifizierungs-, Pfad- oder Passphrase-Fehler zeigen.

## Fehlerbilder

- **Permission denied**: Zugangsdaten, SSH-Key oder SMB-Credentials prüfen.
- **Repository not found**: Pfad oder initiale Repository-Anlage prüfen.
- **Passphrase incorrect**: Passphrase-Datei oder importierte Secrets prüfen.
- **SMB nicht gemountet**: Mount ausführen, danach erneut testen.
