# Borg Backup UI product flyer

This directory contains the editable source and current live-application
screenshots for the German Borg Backup UI product flyer.

## Generate the flyer

The generator requires Python, ReportLab and Pillow. A local virtual
environment can be prepared with:

```bash
python3 -m venv .flyer-venv
.flyer-venv/bin/pip install -r docs/flyer/requirements.txt
.flyer-venv/bin/python docs/flyer/generate_flyer.py
```

The generated PDF is written to:

```text
output/pdf/borg-backup-ui-flyer-de.pdf
```

The screenshots were captured from the current application in German. They do
not contain login credentials or repository secrets.
