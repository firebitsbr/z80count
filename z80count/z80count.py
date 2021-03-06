# -*- coding: utf-8 -*-

# Copyright (C) 2019 by Juan J. Martinez <jjm@usebox.net>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import collections
import configparser
import json
import sys
import os
import re
import argparse
from os import path

version = "0.8.1"

OUR_COMMENT = re.compile(r"(\[[0-9.\s/]+\])")
DEF_COLUMN = 50
DEF_TABSTOP = 8
DEF_CONFIG_FILE = "z80countrc"


def perror(message, *args, **kwargs):
    exc = kwargs.get("exc")
    if exc:
        print(exc, file=sys.stderr)
    print(message % args, file=sys.stderr)


#
# Program arguments
#

# NOTE: types as used in the schema are just the callables
# responsibles for converting strings to python values (when the value
# comes from the config file). They must accept python values as well
# (when the value comes from the defaults). If the value is invalid
# for its domain they must raise a ValueError or TypeError exception.

def boolean(x):
    if x in (True, "1", "on", "yes", "true"):
        return True
    elif x in (False, "0", "off", "no", "false"):
        return False
    raise ValueError(x)


Option = collections.namedtuple(
    "Option",
    "config_name, arg_name, default, type",
)


DEFAULTS = [
    Option("column",    "column",    DEF_COLUMN,  int),
    Option("debug",     "debug",     False,       boolean),
    Option("subtotals", "subt",      False,       boolean),
    Option("tab width", "tab_width", DEF_TABSTOP, int),
    Option("keep cycles", "no_update", False,     boolean),
    Option("use tabs",  "use_tabs",  False,       boolean),
]


def get_program_args():
    """Get program arguments.

    Main entry point for the config machinery.

    Gathers arguments from the ``DEFAULTS`` structure, a config file
    and the command line. Returns a ``argparse.Namespace`` object (as
    returned by ``argparse.Parser.parse_args``), containing the merged
    options.

    Values specified in the command line have the highest priority,
    then the options specified in the config file and finally the
    default values defined by ``DEFAULTS``.

    """
    config_file = locate_config_file()
    if config_file:
        config = load_config_file(config_file, DEFAULTS)
    else:
        config = {i.config_name: i.default for i in DEFAULTS}

    args = parse_command_line(
        {i.arg_name: config[i.config_name] for i in DEFAULTS}
    )

    return args


def load_config_file(config_file, schema):
    parser = configparser.ConfigParser()
    parser["z80count"] = {i.config_name: i.default for i in schema}
    try:
        parser.read(config_file)
    except configparser.Error as ex:
        perror("Error parsing config file. Using defaults.", exc=ex)

    section = parser["z80count"]
    res = {}
    for opt in schema:
        v = section.get(opt.config_name)
        try:
            v = opt.type(v)
        except (ValueError, TypeError):
            perror(
                "Error parsing config value for '%s'. Using default.",
                opt.config_name,
            )
            v = opt.default
        res[opt.config_name] = v

    return res


def locate_config_file():

    # TODO: check on windows

    z80count_rc = os.environ.get("Z80COUNT_RC")
    if z80count_rc and os.path.isfile(z80count_rc):
        return z80count_rc

    home_dir = os.path.expanduser("~")

    # NOTE: The XDG standard states:
    #
    # $XDG_CONFIG_HOME defines the base directory relative to which
    # user specific configuration files should be stored. If
    # $XDG_CONFIG_HOME is either not set or empty, a default equal to
    # $HOME/.config should be used.
    #
    # https://specifications.freedesktop.org/basedir-spec/latest/ar01s03.html

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home is None:
        xdg_config_home = os.path.join(home_dir, ".config")

    candidate = os.path.join(xdg_config_home, DEF_CONFIG_FILE)
    if os.path.isfile(candidate):
        return candidate

    candidate = os.path.join(home_dir, "." + DEF_CONFIG_FILE)
    if os.path.isfile(candidate):
        return candidate

    return None


def parse_command_line(defaults):
    parser = argparse.ArgumentParser(
        description='Z80 Cycle Count',
        epilog="Copyright (C) 2019 Juan J Martinez <jjm@usebox.net>")

    parser.add_argument(
        "--version", action="version", version="%(prog)s " + version)
    parser.add_argument('-d', dest='debug', action='store_true',
                        help="Enable debug (show the matched case)",
                        default=defaults["debug"])
    parser.add_argument('-s', dest='subt', action='store_true',
                        help="Include subtotal",
                        default=defaults["subt"])
    parser.add_argument('-n', dest='no_update', action='store_true',
                        help="Do not update existing count if available",
                        default=defaults["no_update"])
    parser.add_argument('-T', dest='tab_width', type=int,
                        help="Number of spaces for each tab (default: %d)" % DEF_TABSTOP,
                        default=defaults["tab_width"])
    parser.add_argument('-t', '--use-tabs', dest='use_tabs', action='store_true',
                        help="Use tabs to align newly added comments (default: use spaces)",
                        default=defaults["use_tabs"])
    parser.add_argument('-c', '--column', dest='column', type=int,
                        help="Column to align newly added comments (default: %d)" % DEF_COLUMN,
                        default=defaults["column"])

    parser.add_argument(
        "infile", nargs="?", type=argparse.FileType('r'), default=sys.stdin,
        help="Input file")
    parser.add_argument(
        "outfile", nargs="?", type=argparse.FileType('w'), default=sys.stdout,
        help="Output file")

    return parser.parse_args()


#
# z80count
#

def z80count(line,
             parser,
             total,
             subt,
             no_update,
             column=50,
             use_tabs=False,
             tab_width=8,
             debug=False,
             ):
    out = line.rstrip() + "\n"
    entry = parser.lookup(line)
    if entry:
        total, total_cond = update_counters(entry, total)
        out = format_line(
            line, entry, total, total_cond, subt, update=not no_update,
            column=column, debug=debug, use_tabs=use_tabs,
            tab_width=tab_width,
        )
    return (out, total)


def update_counters(entry, total):
    if entry["_t_states_met"]:
        total_cond = total + entry["_t_states_met"]
    else:
        total_cond = 0
    total = total + entry["_t_states_or_not_met"]

    return (total, total_cond)


def format_line(line, entry, total, total_cond, subt, update, column,
                debug, use_tabs, tab_width):
    cycles = entry["cycles"]
    line = line.rstrip().rsplit(";", 1)
    comment = "; [%s" % cycles
    if subt:
        if total_cond:
            comment += " .. %d/%d]" % (total_cond, total)
        else:
            comment += " .. %d]" % total
    else:
        comment += "]"
    if debug:
        comment += " case{%s}" % entry["case"]

    if len(line) == 1:
        comment = comment_alignment(
            line[0], column, use_tabs, tab_width) + comment
    out = line[0] + comment
    if len(line) > 1:
        if update:
            m = OUR_COMMENT.search(line[1])
            if m:
                line[1] = line[1].replace(m.group(0), "")
        out += " "
        out += line[1].lstrip()
    out += "\n"

    return out


def comment_alignment(line, column, use_tabs=False, tab_width=8):
    """Calculate the spacing required for comment alignment.

    :param str line: code line
    :param int column: column in which we want the comment to start
    :param bool use_tabs: use tabs instead of spaces
    :param int tab_width: tab width

    :returns: the spacing
    :rtype: str

    """

    expected_length = column - 1
    length = line_length(line, tab_width)
    if length >= expected_length:
        return " "  # add an space before the colon

    if use_tabs:
        tab_stop = (expected_length // tab_width) * tab_width + 1
        if tab_stop > length:
            extra_tabs = (tab_stop - length) // tab_width
            if length % tab_width > 1:
                extra_tabs += 1  # complete partial tab
            extra_spaces = expected_length - tab_stop
        else:
            extra_tabs = 0
            extra_spaces = expected_length - length
    else:
        extra_tabs = 0
        extra_spaces = expected_length - length

    return "\t" * extra_tabs + " " * extra_spaces


def line_length(line, tab_width):
    """Calculate the length of a line taking TABs into account.

    :param str line: line of code
    :param int tab_width: tab width

    :returns: The length of the line
    :rtype: int

    """
    length = 0
    for i in line:
        if i == "\t":
            length = ((length + tab_width) // tab_width) * tab_width
        else:
            length += 1
    return length


class Parser(object):

    """Simple parser based on a table of regexes."""

    # [label:] OPERATOR [OPERANDS] [; comment]
    _LINE_RE = re.compile(r"^([$.\w]+:)?\s*(?P<operator>\w+)(?P<rest>\s+.*)?$")

    def __init__(self):
        self._table = self._load_table()

    def lookup(self, line):
        mnemo = self._extract_mnemonic(line)
        line = self._remove_label(line)
        if mnemo is None or mnemo not in self._table:
            return None
        for entry in self._table[mnemo]:
            if "_initialized" not in entry:
                self._init_entry(entry)
            if entry["cregex"].search(line):
                return entry
        return None

    @classmethod
    def _load_table(cls):
        table_file = path.join(
            path.dirname(path.realpath(__file__)), "z80table.json")
        with open(table_file, "rt") as fd:
            table = json.load(fd)

        table.sort(key=lambda o: o["w"])
        res = {}
        for i in table:
            mnemo = cls._extract_mnemonic(i["case"])
            assert mnemo is not None
            if mnemo not in res:
                res[mnemo] = []
            res[mnemo].append(i)
        return res

    @classmethod
    def _extract_mnemonic(cls, line):
        match = cls._LINE_RE.match(line)
        if match:
            return match.group("operator").upper()
        return None

    @classmethod
    def _remove_label(cls, line):
        match = cls._LINE_RE.match(line)
        if match:
            rest = match.group("rest") or ""
            return match.group("operator") + rest
        return None

    @staticmethod
    def _init_entry(entry):
        entry["cregex"] = re.compile(
            r"^\s*" + entry["regex"] + r"\s*(;.*)?$", re.I)
        cycles = entry["cycles"]
        if "/" in cycles:
            c = cycles.split("/")
            t_states_or_not_met = int(c[1])
            t_states_met = int(c[0])
        else:
            t_states_or_not_met = int(cycles)
            t_states_met = 0
        entry["_t_states_or_not_met"] = t_states_or_not_met
        entry["_t_states_met"] = t_states_met
        entry["_initialized"] = True


def main():
    args = get_program_args()
    in_f = args.infile
    out_f = args.outfile
    parser = Parser()
    total = 0
    for line in in_f:
        output, total = z80count(
            line, parser, total, args.subt, args.no_update,
            args.column, args.use_tabs, args.tab_width,
            args.debug,
        )
        out_f.write(output)

if __name__ == "__main__":
    main()
