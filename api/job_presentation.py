"""Preserve legacy automatic presentation without retaining mutable identity."""

ICON_KEYS = frozenset({
    'flash', 'appdata', 'photos', 'vms', 'sonstiges', 'docker', 'folder',
    'cloud', 'archive', 'database', 'server', 'home', 'music', 'video',
    'documents', 'code', 'camera', 'usb', 'shield',
})
LEGACY_TYPE_COLORS = {'flash': 'blue', 'appdata': 'orange', 'photos': 'violet', 'vms': 'green'}


def legacy_automatic_icon(meta):
    """Only materialize a recognized old automatic icon; explicit values win."""
    if str(meta.get('icon') or '').strip():
        return None
    previous = str(meta.get('backup_type') or '').strip().lower()
    return previous if previous in ICON_KEYS else None


def legacy_presentation_defaults(meta):
    """Keep the previous list appearance using existing explicit palette keys.

    Legacy cards colored an explicitly selected icon by backup_type, while the
    editor preview already used the icon itself. Preserve the recorded jobs'
    list colors when switching to the consistent icon-based canonical UI.
    """
    updates = {}
    automatic = legacy_automatic_icon(meta)
    if automatic is not None:
        updates['icon'] = automatic
    icon = str(meta.get('icon') or '').strip().lower()
    previous = str(meta.get('backup_type') or '').strip().lower()
    if icon in ICON_KEYS and icon != previous and not str(meta.get('icon_color') or '').strip():
        if previous in LEGACY_TYPE_COLORS:
            updates['icon_color'] = LEGACY_TYPE_COLORS[previous]
        elif icon in LEGACY_TYPE_COLORS:
            updates['icon_color'] = 'gray'
    return updates
