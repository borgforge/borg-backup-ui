# 05 - Jobs und Wizard

## Ziel

Dieses Kapitel beschreibt, wie Jobs angelegt, geprüft und gespeichert werden.

## Neuen Job anlegen

1. **Jobs** öffnen.
2. **Neuer Job** wählen.
3. Jobname und Typ eintragen.
4. Speicherziel wählen: lokal, USB, SMB oder SSH/Storagebox.
5. Ein dazugehöriges vorhandenes Repository wählen.
6. Quellpfade eintragen.
7. Kompression und Retention setzen.
8. Optional Zeitplan aktivieren.
9. Vorschau prüfen und speichern.

## Quellpfade

Quellpfade sind die Daten, die gesichert werden. Sie sollten existieren und für den Backup-Prozess lesbar sein.

Typische Beispiele:

- `/boot/`
- `/mnt/user/appdata/`
- `/mnt/user/photos/`

## Repository

Das Repository ist das Borg-Ziel. Es wird vor dem Job auf der Seite
**Repositories** erstellt oder importiert. Der Job speichert ausschließlich die
Repository-ID. Pfad, Verschlüsselung und Secret-Verweis werden aus dem
Repository-Objekt aufgelöst:

- **local**: Dateisystempfad.
- **usb**: Pfad aus USB-Ziel plus Job-Unterpfad.
- **smb**: Mount-Pfad aus SMB-Profil plus Job-Unterpfad.
- **storagebox**: SSH-URI aus SSH-Profil plus Job-Unterpfad.

## Wizard-Vorschau

Die Vorschau zeigt Speicherziel, Repository und den zentral aufgelösten
Repository-Pfad. Der Wizard legt keine Repositorys an.

## Zeitplan

Der Wizard bietet Frequenz, Uhrzeit und Cron-Vorschau. Nach dem Speichern wird der Schedule für den Job angewendet.

## Ergebnis prüfen

Ein Job ist bereit, wenn er gespeichert ist, keine Wizard-Fehler zeigt und der erste manuelle Lauf erfolgreich war.

## Fehlerbilder

- **Kein Repository vorhanden**: Repository zuerst unter **Repositories**
  erstellen oder importieren.
- **Kein Profil vorhanden**: Passendes USB-, SMB- oder SSH-Profil in Einstellungen anlegen.
- **Quellpfad fehlt**: Pfad auf Unraid prüfen.
- **Passphrase-Datei fehlt**: Repository-Secret prüfen oder Repository erneut
  korrekt importieren.
