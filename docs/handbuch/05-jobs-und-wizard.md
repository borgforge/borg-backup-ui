# 05 - Jobs und Wizard

## Ziel

Dieses Kapitel beschreibt, wie Jobs angelegt, geprüft und gespeichert werden.

## Neuen Job anlegen

1. **Jobs** öffnen.
2. **Neuer Job** wählen.
3. Jobname und Typ eintragen.
4. Location wählen: `local`, `usb`, `smb` oder `storagebox`.
5. Quellpfade eintragen.
6. Zielprofil oder Repository prüfen.
7. Verschlüsselung, Passphrase, Kompression und Retention setzen.
8. Optional Zeitplan aktivieren.
9. Vorschau prüfen und speichern.

## Quellpfade

Quellpfade sind die Daten, die gesichert werden. Sie sollten existieren und für den Backup-Prozess lesbar sein.

Typische Beispiele:

- `/boot/`
- `/mnt/user/appdata/`
- `/mnt/user/photos/`

## Repository

Das Repository ist das Borg-Ziel. Je nach Location entsteht es unterschiedlich:

- **local**: Dateisystempfad.
- **usb**: Pfad aus USB-Ziel plus Job-Unterpfad.
- **smb**: Mount-Pfad aus SMB-Profil plus Job-Unterpfad.
- **storagebox**: SSH-URI aus SSH-Profil plus Job-Unterpfad.

## Wizard-Vorschau

Die Vorschau zeigt den resultierenden Repository-Pfad. Bei SSH-/Storagebox-Jobs prüft der Wizard zusätzlich, ob das Repository gefunden wurde oder ob die Anlage bestätigt werden muss.

## Zeitplan

Der Wizard bietet Frequenz, Uhrzeit und Cron-Vorschau. Nach dem Speichern wird der Schedule für den Job angewendet.

## Ergebnis prüfen

Ein Job ist bereit, wenn er gespeichert ist, keine Wizard-Fehler zeigt und der erste manuelle Lauf erfolgreich war.

## Fehlerbilder

- **Remote-Repository-Anlage bestätigen**: Repository konnte nicht sicher als vorhanden erkannt werden.
- **Kein Profil vorhanden**: Passendes USB-, SMB- oder SSH-Profil in Einstellungen anlegen.
- **Quellpfad fehlt**: Pfad auf Unraid prüfen.
- **Passphrase-Datei fehlt**: Job-Passphrase prüfen oder Secret importieren.
