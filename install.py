# Installer for the weewx-meteoalarm extension.
#
#   weectl extension install weewx-meteoalarm.zip      (WeeWX 5)
#
# During installation you are asked to select your location(s) on the area map:
# the installer prints a link to the map (hosted on GitHub Pages; your station's
# position is only in the part after '#', which the browser keeps to itself). Pick
# areas or draw a polygon there and paste the setup code it shows into the terminal.
# Options, given after the zip file name:
#
#   --setup-code="MA1:UK258:2:"   use a setup code you copied earlier
#   --emma-ids=UK258,UK259        choose areas without the map
#   --polygon="lat,lon ..."       choose a polygon without the map
#   --min-level=2                 1 green, 2 yellow, 3 orange, 4 red
#   --no-map                      don't ask now (run bin/user/meteoalarm.py --setup later)
#   --banner / --no-banner        add (or don't add) a warning banner to the Seasons
#                                 home page without asking

import argparse
import importlib.util
import json
import os
import sys

from weecfg.extension import ExtensionInstaller

# Every file the extension installs. WeeWX also uses this list to uninstall,
# so it must be complete; tools/check_install_files.py verifies it.
FILES = [
    ('bin/user', ['bin/user/meteoalarm.py']),
    ('skins/Meteoalarm', [
        'skins/Meteoalarm/banner.html.tmpl',
        'skins/Meteoalarm/index.html.tmpl',
        'skins/Meteoalarm/meteoalarm-embed.js',
        'skins/Meteoalarm/meteoalarm.css',
        'skins/Meteoalarm/meteoalarm.json.tmpl',
        'skins/Meteoalarm/skin.conf',
        'skins/Meteoalarm/summary.html.tmpl',
    ]),
    ('skins/Meteoalarm/areas', [
        'skins/Meteoalarm/areas/AT.geojson',
        'skins/Meteoalarm/areas/BA.geojson',
        'skins/Meteoalarm/areas/BE.geojson',
        'skins/Meteoalarm/areas/BG.geojson',
        'skins/Meteoalarm/areas/CY.geojson',
        'skins/Meteoalarm/areas/CZ.geojson',
        'skins/Meteoalarm/areas/DE.geojson',
        'skins/Meteoalarm/areas/DK.geojson',
        'skins/Meteoalarm/areas/EE.geojson',
        'skins/Meteoalarm/areas/EI.geojson',
        'skins/Meteoalarm/areas/ES.geojson',
        'skins/Meteoalarm/areas/FI.geojson',
        'skins/Meteoalarm/areas/FR.geojson',
        'skins/Meteoalarm/areas/GR.geojson',
        'skins/Meteoalarm/areas/HR.geojson',
        'skins/Meteoalarm/areas/HU.geojson',
        'skins/Meteoalarm/areas/IE.geojson',
        'skins/Meteoalarm/areas/IL.geojson',
        'skins/Meteoalarm/areas/IS.geojson',
        'skins/Meteoalarm/areas/IT.geojson',
        'skins/Meteoalarm/areas/LT.geojson',
        'skins/Meteoalarm/areas/LU.geojson',
        'skins/Meteoalarm/areas/LV.geojson',
        'skins/Meteoalarm/areas/MD.geojson',
        'skins/Meteoalarm/areas/ME.geojson',
        'skins/Meteoalarm/areas/MK.geojson',
        'skins/Meteoalarm/areas/MT.geojson',
        'skins/Meteoalarm/areas/NL.geojson',
        'skins/Meteoalarm/areas/NO.geojson',
        'skins/Meteoalarm/areas/PL.geojson',
        'skins/Meteoalarm/areas/PT.geojson',
        'skins/Meteoalarm/areas/RO.geojson',
        'skins/Meteoalarm/areas/RS.geojson',
        'skins/Meteoalarm/areas/SE.geojson',
        'skins/Meteoalarm/areas/SI.geojson',
        'skins/Meteoalarm/areas/SK.geojson',
        'skins/Meteoalarm/areas/UK.geojson',
        'skins/Meteoalarm/areas/SOURCES.txt',
        'skins/Meteoalarm/areas/aliases.json',
        'skins/Meteoalarm/areas/index.json',
    ]),
    ('skins/Meteoalarm/icons', [
        'skins/Meteoalarm/icons/meteoalarm_000.svg',
        'skins/Meteoalarm/icons/meteoalarm_1.svg',
        'skins/Meteoalarm/icons/meteoalarm_10.svg',
        'skins/Meteoalarm/icons/meteoalarm_12.svg',
        'skins/Meteoalarm/icons/meteoalarm_13.svg',
        'skins/Meteoalarm/icons/meteoalarm_2.svg',
        'skins/Meteoalarm/icons/meteoalarm_3.svg',
        'skins/Meteoalarm/icons/meteoalarm_4.svg',
        'skins/Meteoalarm/icons/meteoalarm_5.svg',
        'skins/Meteoalarm/icons/meteoalarm_6.svg',
        'skins/Meteoalarm/icons/meteoalarm_7.svg',
        'skins/Meteoalarm/icons/meteoalarm_8.svg',
        'skins/Meteoalarm/icons/meteoalarm_9.svg',
        'skins/Meteoalarm/icons/meteoalarm_info.svg',
    ]),
]


def loader():
    return MeteoalarmInstaller()


class MeteoalarmInstaller(ExtensionInstaller):
    def __init__(self):
        super().__init__(
            version="1.0.0",
            name="meteoalarm",
            description="Weather warnings from www.meteoalarm.org, with an area picker map.",
            author="Ian Millard",
            config={
                "Meteoalarm": {
                    "emma_ids": "",
                    "polygon": "",
                    "min_level": "2",
                    "cache_max_age": "300",
                },
                "StdReport": {
                    "Meteoalarm": {
                        "skin": "Meteoalarm",
                        "HTML_ROOT": "meteoalarm",
                        "enable": "true",
                    },
                },
            },
            files=FILES,
        )
        self.options = self._parse([])

    @staticmethod
    def _parse(args):
        p = argparse.ArgumentParser(prog="weectl extension install <zip>", add_help=False)
        p.add_argument("--setup-code", default="")
        p.add_argument("--emma-ids", default="")
        p.add_argument("--polygon", default="")
        p.add_argument("--min-level", default="2")
        p.add_argument("--no-map", action="store_true")
        p.add_argument("--banner", action="store_true")
        p.add_argument("--no-banner", action="store_true")
        options, _unknown = p.parse_known_args(args)
        return options

    def process_args(self, args):
        self.options = self._parse(args or [])

    def configure(self, engine):
        """Ask for the warning areas: from the command line, or with the map."""
        if getattr(engine, "dry_run", False):
            return False
        weewx_root = engine.root_dict["WEEWX_ROOT"]
        module_path = os.path.join(weewx_root, "bin", "user", "meteoalarm.py")
        later = "To choose your areas later, run:  %s %s --setup" % (sys.executable or "python3", module_path)
        keep = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec = importlib.util.spec_from_file_location("meteoalarm_setup", module_path)
            ma = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ma)
        except (OSError, ImportError, SyntaxError) as e:
            print("Could not load %s (%s). %s" % (module_path, e, later))
            return False
        finally:
            sys.dont_write_bytecode = keep

        opts, config_dict = self.options, engine.config_dict
        skin_dir = os.path.join(weewx_root, "skins", "Meteoalarm")
        try:
            with open(os.path.join(skin_dir, "areas", "index.json"), encoding="utf-8") as fh:
                known = json.load(fh)
        except (OSError, ValueError):
            known = None

        changed = self._choose_areas(ma, opts, config_dict, weewx_root, skin_dir, known, later)
        self._offer_banner(ma, opts, config_dict, weewx_root, module_path)
        return changed

    @staticmethod
    def _choose_areas(ma, opts, config_dict, weewx_root, skin_dir, known, later):
        sel = None
        try:
            if opts.setup_code:
                sel = ma.parse_setup_code(opts.setup_code, known)
            elif opts.emma_ids or opts.polygon:
                sel = ma.clean_selection(opts.emma_ids, opts.polygon, opts.min_level, known)
        except ValueError as e:
            print("Ignoring the area options: %s. %s" % (e, later))
            return False
        if sel:
            ma.apply_selection(config_dict, sel)
            print("Warning areas: " + ma.describe_selection(sel, known))
            return True

        if opts.no_map:
            print(later)
            return False
        if not sys.stdin.isatty():
            print("Not running in a terminal, so you weren't asked for your areas. " + later)
            return False
        sel = ma.interactive_setup(config_dict, weewx_root, skin_dir)
        if not sel:
            print("No areas chosen. " + later)
            return False
        ma.apply_selection(config_dict, sel)
        return True

    @staticmethod
    def _offer_banner(ma, opts, config_dict, weewx_root, module_path):
        """Offer to put a warning banner on the Seasons home page."""
        if opts.no_banner:
            return
        template, _site = ma.seasons_paths(config_dict, weewx_root)
        if not os.path.isfile(template):
            if opts.banner:
                print("No Seasons skin found at %s, so no banner was added." % template)
            return
        if not opts.banner:
            if not sys.stdin.isatty():
                return
            print()
            try:
                answer = input("Show a warning banner on your Seasons home page when a warning is in force? [Y/n] ")
            except EOFError:
                return
            if answer.strip().lower() in ("n", "no"):
                return
        try:
            ma.add_seasons_banner(config_dict, weewx_root)
        except (OSError, ValueError) as e:
            print("Could not add the banner: %s" % e)
            return
        print("Added the warning banner to %s" % template)
        print("(A copy of the original is kept next to it as index.html.tmpl.before-meteoalarm.")
        print(" To take the banner out (do this before uninstalling):  %s %s --remove-banner)"
              % (sys.executable or "python3", module_path))
