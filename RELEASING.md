# Versioning and releases

## Version numbers

weewx-meteoalarm uses [Semantic Versioning](https://semver.org/):
**MAJOR.MINOR.PATCH**, starting at 1.0.0. The version appears in three places,
kept in step by `tools/bump_version.py`:

- `bin/user/meteoalarm.py` (`VERSION`, also sent as the User-Agent to meteoalarm.org)
- `install.py` (`version=`, shown by `weectl extension list`)
- `skins/Meteoalarm/skin.conf` (`SKIN_VERSION`)

### What counts as the public interface

A change is *breaking* if it can stop a working installation from working after
an upgrade, or make someone edit their configuration or templates. These are
the parts users and other skins rely on:

| Interface | Examples |
| --- | --- |
| `[Meteoalarm]` settings in `weewx.conf` | names, meanings and defaults of `emma_ids`, `polygon`, `min_level`, `cache_max_age`, ... |
| The `$meteoalarm` tag | its attributes and each warning's fields (`level`, `title`, `onset_text`, ...) and that text is already HTML-escaped |
| Generated files | names and locations under `meteoalarm/` (`index.html`, `summary.html`, `banner.html`, `meteoalarm.json`, `map/`), the JSON fields, and the `id`s other pages link to (`#alert1`, ...) |
| Setup code format | `MA1:<codes>:<level>:<polygon>` (a new format gets a new prefix, `MA2:`, and `MA1:` keeps working) |
| Command lines | `weectl extension install` options, `meteoalarm.py --setup/--map-link/--add-banner/--remove-banner` |
| The hosted map | its address (`.../v1/map/`), the fragment it understands (`lat`, `lon`, `areas`, `level`, `poly`) and the setup codes it writes; installed copies of this major version open it |
| The Seasons banner block | its markers, so `--remove-banner` can always find blocks added by older versions |
| Supported platforms | WeeWX 5.x on Python 3.7 or later |

The page layout, CSS, wording, map styling and anything in `tools/` or `tests/`
are **not** part of the interface.

### Which number to bump

| Bump | When | Examples |
| --- | --- | --- |
| **MAJOR** (2.0.0) | Something in the table above is removed, renamed or changes meaning; a supported WeeWX or Python version is dropped. | Renaming `emma_ids`; moving `summary.html`; requiring WeeWX 6. |
| **MINOR** (1.1.0) | New features that leave existing setups working unchanged. | A new setting with a default that keeps today's behaviour; a new `$meteoalarm` attribute; a new output file; outlines for Switzerland; supporting a newer WeeWX. |
| **PATCH** (1.0.1) | Fixes, and data refreshes that don't change what users configure. | A bug fix; a wording or CSS change; updated area names or aliases from MeteoAlarm; re-simplified outlines. |

When MeteoAlarm itself renames or removes EMMA codes, users' `emma_ids` can stop
matching. Release that as a **minor** version and say in the changelog which codes
changed and what to use instead. If a code the installer could have written is
removed, keep an alias for it in `aliases.json` if possible.

Deprecate before removing: a setting, attribute or option that is going away keeps
working, and logs a warning, for at least one minor release before a major release
removes it. List it under **Deprecated** in the changelog.

Pre-releases for wider testing use suffixes: `1.1.0-beta.1`, `1.1.0-rc.1`.

### The hosted map

GitHub Pages serves the area map from the `docs/` folder on `main`
(**Settings → Pages → Deploy from a branch → `main` / `/docs`**, with the
repository public). `docs/` is built from `site/` and the area data:

```sh
python3 tools/build_site.py      # then commit docs/ along with the change
```

`tools/check_release.py` fails if you forget. Every install opens whatever is
live, so the map must keep working for all installed versions of the same major
version:

- It is published under a folder per major version (`docs/v1/`, `docs/v2/` ...).
  `build_site.py` only replaces the current major version's folder, so after a
  major release the old folder stays for installs that still point at it.
- Within a major version, the map may improve freely, but it must keep reading
  the same fragment and must keep writing setup codes that version's installers
  accept. A new code format gets a new prefix (`MA2:`) and needs a major version.
- A change to area data (new or renamed areas) goes live for everyone at once;
  put it in the changelog even though the extension itself didn't change.

## Branches and changes

- `main` is always installable. Work happens on short-lived branches and reaches
  `main` through a pull request.
- Every pull request that changes behaviour adds a line under
  `## [Unreleased]` in `CHANGELOG.md`, in the right group: **Added**, **Changed**,
  **Deprecated**, **Removed**, **Fixed** or **Security**. Write it for users:
  what they will notice, and anything they need to do.
- The CI workflow (`.github/workflows/ci.yml`) runs `tools/check_release.py` and
  `tests/smoke_test.py` on every push and pull request, on Python 3.9 and 3.13.

## Making a release

Everything below can be done on the GitHub website instead of with git, as long
as the same files end up on `main`: upload them with **Add file → Upload files**,
and create the tag with **Releases → Draft a new release → Choose a tag → v1.1.0
(create on publish)**. If the release workflow doesn't run, attach the zip to the
release yourself (build it with `git archive`, or from **Code → Download ZIP**,
renamed to `weewx-meteoalarm-1.1.0.zip`).

1. **Pick the number** using the table above, looking at what is under
   `## [Unreleased]` in `CHANGELOG.md`.
2. **Bump it** on a branch:
   ```sh
   git checkout -b release-1.1.0 origin/main
   python3 tools/bump_version.py 1.1.0
   ```
   This updates the three files and turns `## [Unreleased]` into
   `## [1.1.0] - <today>` with a fresh, empty `Unreleased` above it. Read the
   section and tidy it.
3. **Check it:**
   ```sh
   python3 tools/check_release.py --release
   python3 tests/smoke_test.py          # needs WeeWX installed, see its header
   ```
4. **Try it on a real station** (see the checklist below), then open a pull
   request and merge it into `main`.
5. **Tag the merge commit** and push the tag:
   ```sh
   git checkout main && git pull
   git tag -a v1.1.0 -m "weewx-meteoalarm 1.1.0"
   git push origin v1.1.0
   ```
   The release workflow (`.github/workflows/release.yml`) checks that the tag
   matches the version in the files, builds
   `weewx-meteoalarm-1.1.0.zip`, and publishes a GitHub release with that
   zip attached and the changelog section as its notes. Tags with a pre-release
   suffix are published as pre-releases.
6. **Announce it**: users install or upgrade with
   ```sh
   weectl extension install https://github.com/Millardiang/weewx-meteoalarm/releases/download/v1.1.0/weewx-meteoalarm-1.1.0.zip
   ```
   (Release downloads only work without logging in if the repository is public.)

If something is wrong after tagging, don't move or reuse the tag: fix it and
release the next patch version.

### Manual test checklist

On a WeeWX 5 station with the Seasons skin, upgrading from the previous release:

- [ ] `weectl extension install <zip>` asks for the setup code; the printed map
      address opens; **Copy setup code** works; pasting it saves `[Meteoalarm]`.
- [ ] The link the installer prints opens the live map at the station, showing
      the current areas, level and polygon.
- [ ] Choosing **Y** for the banner adds it once, even when installing twice.
- [ ] After a restart and one report cycle: `meteoalarm/index.html`,
      `summary.html`, `banner.html` and `meteoalarm.json` are there and current.
- [ ] The map shows outlines (including UK counties) and its setup code is
      accepted by the installer being released and by the previous release of
      the same major version.
- [ ] `meteoalarm.py --setup` changes the areas; `--remove-banner` restores the
      Seasons template exactly.
- [ ] `weectl extension uninstall meteoalarm` removes everything it installed and
      Seasons still builds.
- [ ] Settings from the previous version still work unchanged.
