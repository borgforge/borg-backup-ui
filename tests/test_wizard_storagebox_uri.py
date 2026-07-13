from api.repositories_api import effective_repository_path


def test_wizard_storagebox_relative_base_path_becomes_uri_path():
    storage = {
        "location": "storagebox",
        "storage_type": "ssh",
        "user": "u123",
        "host": "u123.your-storagebox.de",
        "port": "23",
        "base_path": "./backup",
    }
    assert effective_repository_path(storage, "borg-backup-flash") == (
        "ssh://u123@u123.your-storagebox.de:23/./backup/borg-backup-flash"
    )
