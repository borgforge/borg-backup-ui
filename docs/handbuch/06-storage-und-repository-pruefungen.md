# 06 - Speicherziele und Repository-Wartung

## Ziel

Dieses Kapitel erklärt den Unterschied zwischen Profiltest, Job-Check,
Repository-Information und Borg-Wartung.

## Drei Arten von Prüfungen

- **Profiltest**: Prüft, ob ein SMB- oder SSH-Profil grundsätzlich nutzbar ist.
- **Job-Check**: Prüft schnell lokale Plausibilität, z. B. Profilreferenz, URI-Syntax, Quellpfade und Passphrase-Datei.
- **Repository-Information**: Lädt Identität, Archive, Größe und
  Verschlüsselung des konkreten Borg-Repositorys.
- **Repository-Wartung**: Führt Check, Datenprüfung, Prune oder Compact bewusst
  für genau dieses Repository aus.

## Repository-Seite verwenden

1. **Repositories** öffnen.
2. Speicherziel und Repository in der Seitenleiste wählen.
3. Unter **Übersicht** die Repository-Informationen aktualisieren.
4. Unter **Archive** vorhandene Archive prüfen.
5. Unter **Wartung** nur die benötigte Borg-Aktion auswählen.
6. Status und verständliche Fehlerdetails lesen.

## SMB-Besonderheiten

Ein SMB-Repository kann nur sinnvoll geöffnet werden, wenn das SMB-Ziel
gemountet ist. Ein vorhandenes Profil allein reicht dafür nicht aus.

## SSH-Besonderheiten

Ein erfolgreicher SSH-Profiltest bedeutet, dass Verbindung und Basiszugriff funktionieren. Das konkrete Job-Repository kann trotzdem fehlen oder einen anderen Pfad haben.

## Borg-Check

Ein Borg-Check ist intensiver als ein einfacher Zugriffstest. Er sollte bewusst eingesetzt werden, weil er je nach Repository-Größe länger laufen kann.

## Ergebnis prüfen

Ein Repository gilt als erreichbar, wenn seine Informationen erfolgreich
geladen werden und keine Authentifizierungs-, Pfad- oder Passphrase-Fehler
angezeigt werden.

## Fehlerbilder

- **Permission denied**: Zugangsdaten, SSH-Key oder SMB-Credentials prüfen.
- **Repository not found**: Pfad oder initiale Repository-Anlage prüfen.
- **Passphrase incorrect**: Passphrase-Datei oder importierte Secrets prüfen.
- **SMB nicht gemountet**: Mount ausführen, danach erneut testen.
