# Authentication User Store Recovery

Borg Backup UI fails closed when an existing
`/boot/config/borg-backup/config/users.json` cannot be read or validated. Normal
API access, login and administrator bootstrap remain unavailable until the file
is recovered locally.

## Preferred recovery

1. Stop Borg Backup UI from the Unraid plugin control panel.
2. Back up the complete `/boot/config/borg-backup` directory before changing
   authentication files.
3. Restore `config/users.json` from a trusted backup.
4. Start Borg Backup UI and verify that an administrator can sign in.

## Recovery without a trusted user-store backup

Use this only from the local Unraid console as an explicit administrator
recovery action:

1. Stop Borg Backup UI.
2. Move, do not silently overwrite, the damaged `config/users.json` to a
   timestamped recovery file outside the active config path.
3. Move `config/sessions.json` aside as well so that no session from the old
   user store can be reused.
4. Start Borg Backup UI and complete the administrator bootstrap immediately.
5. Recreate any additional users and verify their roles.
6. Keep the damaged files only for local diagnosis and do not attach them to a
   public issue because they contain authentication metadata.

Deleting or moving a valid user store is not a password-reset function. It is
an emergency recovery procedure that intentionally removes all configured user
accounts from the active installation.
