# -*- coding: utf-8 -*-
#
# PyBorg: The python AI bot.
#
# Copyright (c) 2000, 2006 Tom Morton, Sebastien Dailly
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#

import collections
from itertools import izip, count
import os


def _load_config(filename):
    """
    Load a config file returning dictionary of variables.
    """
    if not os.access(filename, os.R_OK):
        return

    with open(filename, 'r') as f:
        settings = {}

        for line, i in izip(f, count(1)):
            line = line.rstrip()
            if not line or line.startswith('#'):
                continue

            # TODO: add multiline values back in
            #read if the string is above multiple lines
            #while s.rfind("\\") > -1:
            #    s = s[:s.rfind("\\")] + f.readline()
            #    line = line + 1

            try:
                key, value = line.split('=', 1)
            except ValueError:
                raise ValueError("Malformed config line {0} in config file {1}: missing '=' in {2}".format(i, filename, repr(line)))

            key, value = key.strip(), value.strip()
            settings[key] = eval(value)

    return settings


def _save_config(filename, fields):
    """
    fields should be a dictionary. Keys as names of
    variables containing tuple (string comment, value).
    """
    with open(filename, 'w') as f:
        for key, data in sorted(fields.iteritems(), key=lambda f: f[0]):
            comment, value = data
            value_str = repr(value)
            f.write('# {0}\n{1} = {2}\n\n'.format(comment, key, value_str))


Setting = collections.namedtuple('setting', ['comment', 'default'])


class Settings(object):

    def __init__(self, defaults):
        self._defaults = defaults
        for key, setting in defaults.iteritems():
            setattr(self, key, setting.default)

    def load(self, filename):
        """
        Defaults should be key=variable name, value=
        tuple of (comment, default value)
        """
        self._filename = filename

        # Try to laad the existing config.
        config = _load_config(filename)
        if not config:
            self.save()
            return

        self.__dict__.update(config)

    def save(self):
        """
        Save borg settings
        """
        keys = {}
        for i in self.__dict__.keys():
            # reserved
            if i == "_defaults" or i == "_filename":
                continue
            if self._defaults.has_key(i):
                comment = self._defaults[i][0]
            else:
                comment = ""
            keys[i] = (comment, self.__dict__[i])
        # save to config file
        _save_config(self._filename, keys)

