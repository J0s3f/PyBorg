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
    settings = dict()
    execfile(filename, settings)
    return dict((k, v) for k, v in settings.iteritems() if not k.startswith('_'))


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
        keys = dict()
        for name, default in self._defaults.iteritems():
            value = getattr(self, name, None)
            keys[name] = Setting(default.comment, value)
        _save_config(self._filename, keys)
