#!/usr/bin/env python
#
# PyBorg ascii file input module
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

import logging
import string
import sys

import pyborg


class ModFileIn:
    """
    Module for file input. Learning from ASCII text files.
    """

    # Command list for this module
    commandlist = "FileIn Module Commands:\nNone"
    commanddict = {}

    def __init__(self, borg, args):
        for filename in args:
            self.learn_file(borg, filename)

    def learn_file(self, borg, filename):
        with open(filename, 'r') as f:
            buffer = f.read()

        logging.info("I knew %d words (%d lines) before reading %s",
            borg.settings.num_words, len(borg.brain.lines), filename)

        buffer = pyborg.filter_message(buffer, borg)
        try:
            borg.learn(buffer)
        except KeyboardInterrupt, e:
            # Close database cleanly
            print "Premature termination :-("

        logging.info("I know %d words (%d lines) now!",
            borg.settings.num_words, len(borg.brain.lines))

    def shutdown(self):
        pass

    def start(self):
        sys.exit()

    def output(self, message, args):
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    if len(sys.argv) < 2:
        print "Specify a filename."
        sys.exit()

    my_pyborg = pyborg.Pyborg()
    ModFileIn(my_pyborg, sys.argv[1:])
    my_pyborg.save_all()
