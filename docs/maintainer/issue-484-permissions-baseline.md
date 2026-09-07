# Issue #484: main-version installation and reboot comparison

This is a reproduction protocol, not a packaging fix or a confirmed repair guide.
The maintainer requested a new test-channel build of unchanged main source before
implementing the fix. Baseline: `a5a02fe7b8488bc7de2664ab0a4f6655a145765e`
(stable version `2026.09.06.0112`). Issue #447 remains frozen; #486 is separate.

The baseline branch changes only this maintainer document. The release workflow
requires a non-main branch with a committed delta for its preflight. Verify that
the deployable source digest equals the baseline before publishing. Build and
publish through the existing preflight and test-channel scripts, without changing
the packaging scripts, directory modes or build umask to hide the defect.

## Evidence available before this test

- Issue #484 already contains an independent before/after installation report and
  archive listings showing mode `0775` for `/`, `/usr` and `/etc` in the stable
  `2026.09.06.0112` package.
- On 2026-09-07 the maintainer supplied two snapshots, labelled "After install
  Plugin" on TheTwist and "Fresh Installation of Unraid" on Tower. Both snapshots
  have identical modes and `root:root` ownership for the inspected paths:

  | Mode | Paths |
  | --- | --- |
  | `0755` | `/`, `/etc`, `/usr`, `/usr/local`, `/usr/local/emhttp`, `/usr/local/emhttp/plugins`, `/mnt`, `/var` |
  | `0700` | `/boot`, `/boot/config`, `/boot/config/plugins` |
  | `0777` | `/etc/rc.d` |

- The maintainer also reported uninstalling the plugin and restoring directories.
  The snapshots do not establish the sequence of install, manual restoration and
  reboot on a single host. They therefore do not disprove the earlier reproduction
  or establish that a reboot alone repairs the affected system.
- These are observed reference values, not a request to apply blanket chmod
  commands. In particular, do not turn `/boot` or `/etc/rc.d` into `0755` merely
  because other directories use that mode.

## Capture command

Run the same read-only command at each stage on the same Unraid test host. Copy
the output off the host before restarting; do not rely on RAM-backed logs surviving
the reboot. Record the exact Unraid version (`cat /etc/unraid-version`), plugin
version, installation output, and whether the plugin is installed at each stage.

```bash
stat -c '%a %U:%G %n' \
  / /boot /boot/config /boot/config/plugins \
  /etc /etc/rc.d \
  /usr /usr/local /usr/local/emhttp /usr/local/emhttp/plugins \
  /mnt /var
```

`%a` is the numeric permission mode, `%U:%G` the owner/group and `%n` the path.
The command does not change permissions. Keep `/usr/local/emhttp/plugins` as one
argument; an actual newline between its leading slash and `usr` changes the
command. Terminal visual wrapping alone is harmless.

`ls -ld` is a useful second view. Different directory sizes, link counts and
modification times do not by themselves indicate different permissions.

## Test stages

1. **Before installation:** capture permissions on the restored test host, before
   installing the new main-based test package. Record any manual repair already
   performed. Keep WebGUI or local-console access available because this known
   defect can affect SSH public-key login.
2. **Immediately after installation:** install the exact verified test-channel
   version through Unraid, save the installer output and repeat the capture
   command. Do not run chmod, uninstall or reboot between these two captures.
3. **After normal reboot, plugin still installed:** restart through the Unraid UI
   and capture again. Record that the plugin was still enabled for startup. This
   tests the maintainer's proposed reboot-only recovery in the actual installed
   state.
4. **If the wrong modes persist:** to distinguish base-system restoration from
   plugin reapplication, uninstall the affected test plugin through Unraid, capture
   once before reboot and once after reboot. Do not manually change modes between
   these captures. Retain existing plugin configuration and backup data.
5. **After the packaging fix:** repeat the installation and reboot comparisons
   with the corrected package. This is a separate candidate, prepared after the
   baseline results; the baseline package must not be described as fixed.

| Stage | Exact Unraid/plugin version | Plugin installed? | Captured modes | SSH key login, if configured |
| --- | --- | --- | --- | --- |
| Before installation | Pending | No | Pending | Pending |
| Immediately after installation | Pending | Yes | Pending | Pending |
| After normal reboot | Pending | Yes | Pending | Pending |
| After uninstall, before reboot (if needed) | Pending | No | Pending | Pending |
| After reboot without plugin (if needed) | Pending | No | Pending | Pending |
| Corrected package, install and reboot | Pending | Yes | Pending | Pending |

## Interpreting a reboot

Unraid loads its Linux core into RAM and subsequently loads installed plugins
during startup ([official boot-sequence documentation](https://docs.unraid.net/unraid-os/troubleshooting/common-issues/boot-and-startup-failures/#understanding-the-boot-sequence)).
Consequently, a reboot can restore base-system state while the affected package
can apply incorrect permissions again during plugin startup. That is a hypothesis
to distinguish using the captures above, not an observed outcome of this test.

Only recommend a reboot as recovery after the relevant sequence is verified on
the reported Unraid version. If recovery requires removing or updating the faulty
plugin first, that prerequisite must be part of the recommendation. A packaging
fix remains necessary to prevent future installs or updates from changing shared
directory permissions, regardless of whether reboot recovery succeeds.
