# 04 - Profile für Speicherziele

## Ziel

Dieses Kapitel beschreibt USB-, SMB- und SSH-Profile als Grundlage für wiederverwendbare Backup-Ziele.

## USB-Profile

USB-Profile beschreiben wechselbare lokale Ziele. Sie werden in **Einstellungen > USB-Profile** gepflegt und danach im Job-Wizard ausgewählt.

Prüfen:

- Profilname ist eindeutig.
- Zielpfad ist vorhanden, wenn ein Lauf gestartet wird.
- Gerät ist gemountet, bevor der Job läuft.

## SMB-Profile

SMB-Profile werden in **Einstellungen > SMB-Profile** angelegt. Ein Profil enthält Server, Share, Mount-Pfad und Zugangsdaten.

Schritte:

1. Profil anlegen.
2. Speichern.
3. Profilstatus prüfen.
4. In **Storage > SMB** mounten.
5. Danach Repository-Test ausführen.

Der reine Job-Check prüft nur Profilreferenz und Pfad-Plausibilität. Ob das Repository erreichbar ist, wird über den Storage-Test geprüft.

## SSH-Profile

SSH-Profile werden in **Einstellungen > SSH-Profile** verwaltet. Sie gelten für Storagebox, Synology oder generische SSH-Ziele.

Wichtige Felder:

- Name
- Host
- Port
- User
- Basispfad
- SSH-Key-Pfad
- Zieltyp

Für Storagebox ist ein relativer Basispfad wie `./backup` typisch. In der Repository-URI wird daraus ein Pfad mit Slash nach dem Port, z. B. `:23/./backup/...`.

## Profiltest

Der SSH-Profiltest prüft Verbindung, Zieltyp, Borg-Verfügbarkeit oder Storagebox-Sonderfall, Basispfad und Schreibzugriff. Er bestätigt das Profil, aber nicht automatisch jedes konkrete Job-Repository.

## Ergebnis prüfen

Ein Profil ist einsatzbereit, wenn es gespeichert ist, der Profiltest erfolgreich ist und ein Job es ohne Warnung referenzieren kann.

## Fehlerbilder

- **Profil kann nicht gelöscht werden**: Es wird noch von Jobs verwendet.
- **SMB nicht gemountet**: Erst mounten, dann Repo testen.
- **SSH-Key falsch**: Key-Pfad und Berechtigungen prüfen.
- **Basispfad falsch**: Bei Storagebox `./backup` statt `backup` oder fehlerhafter URI-Fragmente verwenden.
