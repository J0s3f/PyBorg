# -*- coding: utf-8 -*-
"""
# PyBorg: The python AI bot.
#
# Copyright (c) 2000, 2006 Tom Morton, Sebastien Dailly
#
#
# This bot was inspired by the PerlBorg, by Eric Bock.
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
# Tom Morton <tom@moretom.net>
# Seb Dailly <seb.dailly@gmail.com>
"""

from __future__ import division

from itertools import izip, count
import logging
import marshal    # buffered marshal is bloody fast. wish i'd found this before :)
import os
import random
import re
import struct
import sys
import time
import zipfile

from cfgfile import Setting, Settings


def command(fn):
    fn.is_command = True
    return fn


def owner_command(fn):
    fn.is_owner_command = True
    return command(fn)


class Brain(object):

    def __init__(self, settings):
        self.settings = settings

    def filter_message(self, message):
        """
        Filter a message body so it is suitable for learning from and
        replying to. This involves removing confusing characters,
        padding ? and ! with ". " so they also terminate lines
        and converting to lower case.
        """
        message = message.lower()

        # remove garbage
        replacements = {
            '"': '',
            "'": '',
            '; ': ', ',
            '?': ' ? ',
            '!': ' ! ',
            '.': ' . ',
            ',': ' , ',
            '#nick:': '#nick :',
        }
        for repl_from, repl_to in replacements.iteritems():
            message = message.replace(repl_from, repl_to)

        # remove matching brackets (unmatched ones are likely smileys :-) *cough*
        # should except out when not found.
        subs = -1
        while subs != 0:
            message, subs = re.subn(r'(?x) \( ([^)]*) \)', r'\1', message)

        # No sense in keeping URLS
        message = re.sub(r"https?://[^ ]* ", "", message)
        message = re.sub(r'\s+', ' ', message)
        return message

    def learn(self, body):
        raise NotImplementedError

    def reply(self, body):
        raise NotImplementedError

    def save(self):
        pass


class MegahalBrain(Brain):

    def __init__(self, settings):
        super(MegahalBrain, self).__init__(settings)
        import mh_python

    def learn(self, body):
        return mh_python.learn(body)

    def reply(self, body):
        return mh_python.doreply(body)


class PyborgBrain(Brain):

    saves_version = "1.1.0"

    log = logging.getLogger('PyborgBrain')

    def __init__(self, settings):
        super(PyborgBrain, self).__init__(settings)

        self.log.info("Reading dictionary...")
        try:
            zfile = zipfile.ZipFile('archive.zip', 'r')
        except (EOFError, IOError):
            self.log.debug("No archive.zip found to unarchive")
        else:
            # Unarchive all the files from the zip.
            for filename in zfile.namelist():
                data = zfile.read(filename)
                with open(filename, 'w+b') as data_file:
                    data_file.write(data)

        try:
            with open('version', 'rb') as version_file:
                content = version_file.read()
            if content != self.saves_version:
                self.log.error("Dictionary is version %s but version %s is required. Please convert the dictionary.",
                    content, self.saves_version)
                # TODO: use an exception here
                sys.exit(1)

            with open('words.dat', 'rb') as words_file:
                self.words = marshal.load(words_file)
            with open('lines.dat', 'rb') as lines_file:
                self.lines = marshal.load(lines_file)
        except (EOFError, IOError):
            self.log.info("Couldn't read saved dictionary, so using a new database.")
            self.words = {}
            self.lines = {}

        # Is a resizing required?
        if len(self.words) != self.settings.num_words:
            self.log.info("Re-counting words and contexts (settings reported %d but counted %d)...",
                self.settings.num_words, len(self.words))

            self.settings.num_words = len(self.words)
            self.settings.num_contexts = sum(len(line[0].split()) for line in self.lines.itervalues())

            self.settings.save()

        # Is an aliases update required ?
        compteur = 0
        for x in self.settings.aliases.keys():
            compteur += len(self.settings.aliases[x])
        if compteur != self.settings.num_aliases:
            print "check dictionary for new aliases"
            self.settings.num_aliases = compteur

            for x in self.words.keys():
                #is there aliases ?
                if x[0] != '~':
                    for z in self.settings.aliases.keys():
                        for alias in self.settings.aliases[z]:
                            pattern = "^%s$" % alias
                            if re.search(pattern, x):
                                print "replace %s with %s" % (x, z)
                                self.replace_word(x, z)

            for x in self.words.keys():
                if not (x in self.settings.aliases.keys()) and x[0] == '~':
                    print "unlearn %s" % x
                    self.settings.num_aliases -= 1
                    self.unlearn_word(x)
                    print "unlearned aliases %s" % x

        # Unlearn words in the unlearn.txt file.
        try:
            with open('unlearn.txt', 'r') as unlearn_file:
                for word in unlearn_file:
                    word = word.strip()
                    if word and word in self.words:
                        self.unlearn_word(word)
        except (EOFError, IOError):
            # No words to unlearn.
            pass

    def apply_aliases(self, word):
        for repl_word, patterns in self.settings.aliases.iteritems():
            for pattern in patterns:
                alias_re = re.compile(r'^%s$' % pattern)
                if alias_re.match(word):
                    # We should only care about the first alias, so returning out is fine.
                    return repl_word
        return word

    def filter_message(self, message):
        message = super(PyborgBrain, self).filter_message(message)
        if not self.settings.aliases:
            return message

        words = message.split()
        words = (self.apply_aliases(word) for word in words)
        return ' '.join(words)

    def save(self):
        if self.settings.no_save:
            return

        self.log.info("Writing dictionary...")

        with open('words.dat', 'wb') as words_file:
            marshal.dump(self.words, words_file)
        with open('lines.dat', 'wb') as lines_file:
            marshal.dump(self.lines, lines_file)
        with open('version', 'w') as version_file:
            version_file.write(self.saves_version)

        archive = zipfile.ZipFile('archive.zip', 'w', zipfile.ZIP_DEFLATED)
        archive.write('words.dat')
        archive.write('lines.dat')
        archive.write('version')
        archive.close()

        try:
            os.remove('words.dat')
            os.remove('lines.dat')
            os.remove('version')
        except (OSError, IOError), e:
            self.log.error("Couldn't remove dictionary files: %s", str(e))

        # Write out all the words, sorted by number of contexts.
        words = sorted(self.words.keys(), key=lambda w: len(self.words[w]))
        with open('words.txt', 'w') as words_file:
            for word in words:
                words_file.write(word)
                words_file.write('\n')

    def learn_sentence(self, sentence, num_context):
        """
        Learn from a sentence.
        """
        words = sentence.split()

        # Ignore empty sentences.
        # TODO: this used to be sentences with fewer than three words. should it be?
        if not words:
            return

        all_vowels = "aÃ Ã¢eÃ©Ã¨ÃªiÃ®Ã¯oÃ¶Ã´uÃ¼Ã»y"

        for word in words:
            for censored in self.settings.censored:
                pattern = "^%s$" % censored
                if re.search(pattern, word):
                    self.log.debug("Not learning a sentence: word %r is censored", word)
                    return
            if not self.settings.learning and word not in self.words:
                self.log.debug("Not learning a sentence: learning is off and %r is a new word", word)
                return
            if len(word) > self.settings.max_word_length:
                self.log.debug("Not learning a sentence: word %r is too long", word)
                return

            vowels, digits, chars = 0, 0, 0
            for c in word:
                if c in all_vowels:
                    vowels += 1
                if c.isalpha():
                    chars += 1
                if c.isdigit():
                    digits += 1

            if chars and digits:
                self.log.debug("Not learning a sentence: word %r is mixed alphanumeric", word)
                return
            if chars and len(word) > 5 and vowels / len(word) < self.settings.min_vowel_ratio:
                self.log.debug("Not learning a sentence: word %r has too few vowels (%.2f)", word, num_vowels // len(word))
                return

        words = ['#nick' if '-' in word or '_' in word else word for word in words]

        try:
            contexts_per_word = self.settings.num_contexts / self.settings.num_words
        except ZeroDivisionError:
            contexts_per_word = 0

        clean_sentence = " ".join(words)

        # Hash collisions we don't care about. 2^32 is big :-)
        hashval = hash(clean_sentence)

        # Check context isn't already known
        if hashval in self.lines:
            self.lines[hashval][1] += num_context
        # TODO: is this a bug that we can learn until 100 cpw even when "learning" is off?
        elif contexts_per_word <= 100 or self.settings.learning:
            self.lines[hashval] = [clean_sentence, num_context]
            # Add a link for each word.
            for i, word in izip(count(0), words):
                try:
                    word_contexts = self.words[word]
                except KeyError:
                    self.settings.num_words += 1
                    word_contexts = self.words[word] = list()
                word_contexts.append(struct.pack("lH", hashval, i))
                self.settings.num_contexts += 1

        # Stop learning when we know enough words.
        if self.settings.num_words >= self.settings.max_words:
            self.log.info("STOP LEARNING: got %d words (max %d)", self.settings.num_words, self.settings.max_words)
            self.settings.learning = False

    def learn(self, body, num_context=1):
        """
        Lines should be cleaned (filter_message()) before passing
        to this.
        """
        for sentence in body.split('. '):
            self.learn_sentence(sentence, num_context)

    def unlearn_word(self, context):
        """
        Unlearn all contexts containing 'context'. If 'context'
        is a single word then all contexts containing that word
        will be removed, just like the old !unlearn <word>
        """
        # Pad thing to look for
        # We pad so we don't match 'shit' when searching for 'hit', etc.
        context = " " + context + " "
        # Search through contexts
        # count deleted items
        dellist = []
        # words that will have broken context due to this
        wordlist = []
        for x in self.lines.keys():
            # get context. pad
            c = " " + self.lines[x][0] + " "
            if c.find(context) != -1:
                # Split line up
                wlist = self.lines[x][0].split()
                # add touched words to list
                for w in wlist:
                    if not w in wordlist:
                        wordlist.append(w)
                dellist.append(x)
                del self.lines[x]
        words = self.words
        # update links
        for x in wordlist:
            word_contexts = words[x]
            # Check all the word's links (backwards so we can delete)
            for y in xrange(len(word_contexts) - 1, -1, -1):
                # Check for any of the deleted contexts
                if struct.unpack("lH", word_contexts[y])[0] in dellist:
                    del word_contexts[y]
                    self.settings.num_contexts = self.settings.num_contexts - 1
            if len(words[x]) == 0:
                del words[x]
                self.settings.num_words = self.settings.num_words - 1
                self.log.info("\"%s\" vaped totally", x)

    def reply(self, body):
        """
        Reply to a line of text.
        """
        # split sentences into list of words
        _words = body.split()
        words = []
        for i in _words:
            words += i.split()
        del _words

        if len(words) == 0:
            return ""

        # remove words on the ignore list
        #words = filter((lambda x: x not in self.settings.ignore_list and not x.isdigit()), words)
        words = (x for x in words if x not in self.settings.ignore_list and not x.isdigit())

        # Find rarest word (excluding those unknown)
        index = []
        known = -1
        # The word has to be seen in already 3 contexts differents for being choosen
        known_min = 3
        for x in words:
            if self.words.has_key(x):
                k = len(self.words[x])
            else:
                continue
            if (known == -1 or k < known) and k > known_min:
                index = [x]
                known = k
                continue
            elif k == known:
                index.append(x)
                continue
        # Index now contains list of rarest known words in sentence
        if len(index) == 0:
            return ""
        word = index[random.randint(0, len(index) - 1)]

        # Build sentence backwards from "chosen" word
        sentence = [word]
        done = 0
        while done == 0:
            # create a dictionary wich will contain all the words we can found before the "chosen" word
            pre_words = {"" : 0}
            #this is for prevent the case when we have an ignore_listed word
            word = str(sentence[0].split( " " )[0])
            for x in xrange(0, len(self.words[word]) - 1):
                l, w = struct.unpack("lH", self.words[word][x])
                context = self.lines[l][0]
                num_context = self.lines[l][1]
                cwords = context.split()
                # if the word is not the first of the context, look the previous one
                if cwords[w] != word:
                    print context
                if w:
                    # look if we can found a pair with the choosen word, and the previous one
                    if len(sentence) > 1 and len(cwords) > w + 1:
                        if sentence[1] != cwords[w + 1]:
                            continue

                    # if the word is in ignore_list, look the previous word
                    look_for = cwords[w - 1]
                    if look_for in self.settings.ignore_list and w > 1:
                        look_for = cwords[w - 2] + " " + look_for

                    #saves how many times we can found each word
                    if not (pre_words.has_key(look_for)):
                        pre_words[look_for] = num_context
                    else :
                        pre_words[look_for] += num_context

                else:
                    pre_words[""] += num_context

            # Sort the words
            liste = pre_words.items()
            liste.sort( lambda x, y: cmp( y[1], x[1] ) )

            numbers = [liste[0][1]]
            for x in xrange(1, len( liste)):
                numbers.append(liste[x][1] + numbers[x - 1])

            # take one them from the list (randomly)
            mot = random.randint(0, numbers[len(numbers) - 1])
            for x in xrange(0, len(numbers)):
                if mot <= numbers[x]:
                    mot = liste[x][0]
                    break

            # if the word is already choosen, pick the next one
            while mot in sentence:
                x += 1
                if x >= len(liste) - 1:
                    mot = ''
                mot = liste[x][0]

            mot = mot.split(" ")
            mot.reverse()
            if mot == ['']:
                done = 1
            else:
                #map((lambda x: sentence.insert(0, x)), mot)
                [sentence.insert(0, x) for x in mot]

        pre_words = sentence
        sentence = sentence[-2:]

        # Now build sentence forwards from "chosen" word

        # We've got
        # cwords:    ...    cwords[w-1]    cwords[w]    cwords[w+1]    cwords[w+2]
        # sentence:    ...    sentence[-2]    sentence[-1]    look_for    look_for ?

        # we are looking, for a cwords[w] known, and maybe a cwords[w-1] known, what will be the cwords[w+1] to choose.
        # cwords[w+2] is need when cwords[w+1] is in ignored list

        done = 0
        while done == 0:
            # create a dictionary wich will contain all the words we can found before the "chosen" word
            post_words = {"" : 0}
            word = str(sentence[-1].split(" ")[-1])
            for x in self.words[word]:
                l, w = struct.unpack("lH", x)
                context = self.lines[l][0]
                num_context = self.lines[l][1]
                cwords = context.split()
                #look if we can found a pair with the choosen word, and the next one
                if len(sentence) > 1:
                    if sentence[len( sentence ) - 2] != cwords[w - 1]:
                        continue

                if w < len(cwords) - 1:
                    #if the word is in ignore_list, look the next word
                    look_for = cwords[w + 1]
                    if look_for in self.settings.ignore_list and w < len(cwords) - 2:
                        look_for = look_for + " " + cwords[w + 2]

                    if not (post_words.has_key(look_for)):
                        post_words[look_for] = num_context
                    else:
                        post_words[look_for] += num_context
                else:
                    post_words[""] += num_context
            # Sort the words
            liste = post_words.items()
            liste.sort(lambda x, y: cmp(y[1], x[1]))
            numbers = [liste[0][1]]

            for x in xrange(1, len(liste)):
                numbers.append(liste[x][1] + numbers[x - 1])

            #take one them from the list (randomly)
            mot = random.randint(0, numbers[len(numbers) - 1])
            for x in xrange(0, len(numbers)):
                if mot <= numbers[x]:
                    mot = liste[x][0]
                    break

            x = -1
            while mot in sentence:
                x += 1
                if x >= len(liste) - 1:
                    mot = ''
                    break
                mot = liste[x][0]

            mot = mot.split(" ")
            if mot == ['']:
                done = 1
            else:
                [sentence.append( x ) for x in mot]
                #map((lambda x: sentence.append(x)), mot)

        sentence = pre_words[:-2] + sentence

        # Replace aliases
        for x in xrange(0, len(sentence)):
            if sentence[x][0] == "~":
                sentence[x] = sentence[x][1:]

        # Insert space between each words
        #map((lambda x: sentence.insert(1 + x * 2, " ")), xrange(0, len(sentence) - 1))
        [sentence.insert(1 + x * 2, " ") for x in xrange(0, len(sentence) - 1)]

        # correct the ' & , spaces problem
        # code is not very good and can be improve but does his job...
        for x in xrange(0, len(sentence)):
            if sentence[x] == "'":
                sentence[x - 1] = ""
                sentence[x + 1] = ""
            for split_char in ['?', '!', ',']:
                if sentence[x] == split_char:
                    sentence[x - 1] = ""

        # return as string..
        return "".join( sentence )

    def replace_word(self, old, new):
        """
        Replace all occuraces of 'old' in the dictionary with
        'new'. Nice for fixing learnt typos.
        """
        try:
            pointers = self.words[old]
        except KeyError:
            return old + " not known."
        changed = 0

        for x in pointers:
            # pointers consist of (line, word) to self.lines
            l, w = struct.unpack("lH", x)
            line = self.lines[l][0].split()
            number = self.lines[l][1]
            if line[w] != old:
                # fucked dictionary
                print "Broken link: %s %s" % (x, self.lines[l][0])
                continue
            else:
                line[w] = new
                self.lines[l][0] = " ".join(line)
                self.lines[l][1] += number
                changed += 1

        if self.words.has_key(new):
            self.settings.num_words -= 1
            self.words[new].extend(self.words[old])
        else:
            self.words[new] = self.words[old]
        del self.words[old]
        return "%d instances of %s replaced with %s" % (changed, old, new)

    def known_words(self):
        num_w = self.settings.num_words
        num_c = self.settings.num_contexts
        num_l = len(self.lines)
        if num_w != 0:
            num_cpw = num_c / float(num_w)  # contexts per word
        else:
            num_cpw = 0.0
        return "I know %d words (%d contexts, %.2f per word), %d lines." % (num_w, num_c, num_cpw, num_l)

    @command
    def known(self, io_module, command_args, args):
        words = command_args
        if not words:
            return self.known_words()

        msg = "Number of contexts: "
        for word in words:
            word = word.lower()
            if self.words.has_key(word):
                contexts = len(self.words[word])
                msg += word + "/%i " % contexts
            else:
                msg += word + "/unknown "
        msg = msg.replace("#nick", "$nick")
        return msg

    @owner_command
    def limit(self, io_module, command_args, args):
        msg = "The max limit is "
        if not command_args:
            msg += str(self.settings.max_words)
        else:
            limit = int(command_args[0].lower())
            self.settings.max_words = limit
            msg += "now " + command_list[1]
        return msg

    @owner_command
    def checkdict(self, io_module, command_args, args):
        t = time.time()
        num_broken = 0
        num_bad = 0
        for w in self.words.keys():
            wlist = self.words[w]

            for i in xrange(len(wlist) - 1, -1, -1):
                line_idx, word_num = struct.unpack("lH", wlist[i])

                # Nasty critical error we should fix
                if not self.lines.has_key(line_idx):
                    print "Removing broken link '%s' -> %d" % (w, line_idx)
                    num_broken = num_broken + 1
                    del wlist[i]
                else:
                    # Check pointed to word is correct
                    split_line = self.lines[line_idx][0].split()
                    if split_line[word_num] != w:
                        print "Line '%s' word %d is not '%s' as expected." % \
                            (self.lines[line_idx][0], word_num, w)
                        num_bad = num_bad + 1
                        del wlist[i]
            if len(wlist) == 0:
                del self.words[w]
                self.settings.num_words = self.settings.num_words - 1
                print "\"%s\" vaped totally" % w

        return "Checked dictionary in %0.2fs. Fixed links: %d broken, %d bad." % \
            (time.time() - t, num_broken, num_bad)

    @owner_command
    def rebuilddict(self, io_module, command_args, args):
        # Rebuild the dictionary by discarding the word links and
        # re-parsing each line
        if self.settings.learning == 1:
            t = time.time()

            old_lines = self.lines
            old_num_words = self.settings.num_words
            old_num_contexts = self.settings.num_contexts

            self.words = {}
            self.lines = {}
            self.settings.num_words = 0
            self.settings.num_contexts = 0

            for k in old_lines.keys():
                self.learn(old_lines[k][0], old_lines[k][1])

            return "Rebuilt dictionary in %0.2fs. Words %d (%+d), contexts %d (%+d)" % \
                (time.time() - t, old_num_words, self.settings.num_words - old_num_words,
                old_num_contexts, self.settings.num_contexts - old_num_contexts)

    @owner_command
    def purge(self, io_module, command_args, args):
        # Remove rare words.
        t = time.time()

        liste = []
        compteur = 0

        if command_args:
            # limite d occurences a effacer
            c_max = command_args[0].lower()
        else:
            c_max = 0

        c_max = int(c_max)

        for w in self.words.keys():
            digit = 0
            char = 0
            for c in w:
                if c.isalpha():
                    char += 1
                if c.isdigit():
                    digit += 1

            #Compte les mots inferieurs a cette limite
            c = len(self.words[w])
            if c < 2 or (digit and char):
                liste.append(w)
                compteur += 1
                if compteur == c_max:
                    break

        if c_max < 1:
            #io_module.output(str(compteur)+" words to remove", args)
            io_module.output("%s words to remove" % compteur, args)
            return

        #supprime les mots
        [self.unlearn_word( w ) for w in liste[0:]]

        return "Purge dictionary in %0.2fs. %d words removed" % \
            (time.time() - t, compteur)

    @owner_command
    def replace(self, io_module, command_args, args):
        # Change a typo in the dictionary
        if len(command_args) < 2:
            return
        old = command_args[0].lower()
        new = command_args[1].lower()
        return self.replace_word(old, new)

    @owner_command
    def alias(self, io_module, command_args, args):
        # no arguments. list aliases words
        if not command_args:
            if len(self.settings.aliases) == 0:
                msg = "No aliases"
            else:
                msg = "I will alias the word(s) %s" \
                    % ", ".join(self.settings.aliases.keys())
        # add every word listed to alias list
        elif len(command_args) == 1:
            command_arg = command_args[0]
            if command_arg[0] != '~':
                command_arg = '~' + command_arg
            if command_arg in self.settings.aliases:
                msg = "Thoses words : %s  are aliases to %s" \
                    % (" ".join(self.settings.aliases[command_arg]), command_arg)
            else:
                msg = "The alias %s is not known" % command_arg[1:]
        elif len(command_args) > 1:
            # create the aliases
            alias_word = command_args.pop(0)
            msg = "The words : "
            if alias_word[0] != '~':
                alias_word = '~' + alias_word
            if not (alias_word in self.settings.aliases):
                self.settings.aliases[alias_word] = [alias_word[1:]]
                self.replace_word(alias_word[1:], alias_word)
                msg += alias_word[1:] + " "
            for alias_pat in command_list:
                msg += "%s " % alias_pat
                self.settings.aliases[alias_word].append(alias_pat)
                #replace each words by his alias
                self.replace_word(alias_pat, alias_word)
            msg += "have been aliased to %s" % alias_word
        return msg

    @owner_command
    def contexts(self, io_module, command_args, args):
        # This is a large lump of data and should
        # probably be printed, not module.output XXX

        # build context we are looking for
        context = " ".join(command_args)
        context = context.lower()
        if context == "":
            return
        io_module.output("Contexts containing \"" + context + "\":", args)
        # Build context list
        # Pad it
        context = " " + context + " "
        c = []
        # Search through contexts
        for x in self.lines.keys():
            # get context
            ctxt = self.lines[x][0]
            # add leading whitespace for easy sloppy search code
            ctxt = " " + ctxt + " "
            if ctxt.find(context) != -1:
                # Avoid duplicates (2 of a word
                # in a single context)
                if len(c) == 0:
                    c.append(self.lines[x][0])
                elif c[len(c) - 1] != self.lines[x][0]:
                    c.append(self.lines[x][0])
        x = 0
        while x < 5:
            if x < len(c):
                io_module.output(c[x], args)
            x += 1
        if len(c) == 5:
            return
        if len(c) > 10:
            io_module.output("...(" + `len( c ) - 10` + " skipped)...", args)
        x = len(c) - 5
        if x < 5:
            x = 5
        while x < len(c):
            io_module.output(c[x], args)
            x += 1

    @owner_command
    def unlearn(self, io_module, command_args, args):
        # build context we are looking for
        context = " ".join(command_args)
        context = context.lower()
        if context == "":
            return
        print "Looking for: " + context
        # Unlearn contexts containing 'context'
        t = time.time()
        self.unlearn_word(context)
        # we don't actually check if anything was
        # done..
        msg = "Unlearn done in %0.2fs" % (time.time() - t)
        return msg

    @owner_command
    def censor(self, io_module, command_args, args):
        # no arguments. list censored words
        if not command_args:
            if len(self.settings.censored) == 0:
                msg = "No words censored"
            else:
                msg = "I will not use the word(s) %s" % ", ".join(self.settings.censored)
        # add every word listed to censored list
        else:
            for word in command_args:
                if word in self.settings.censored:
                    msg += "%s is already censored" % word
                else:
                    self.settings.censored.append(word.lower())
                    self.unlearn_word(word)
                    msg += "done"
                msg += "\n"
        return msg

    @owner_command
    def uncensor(self, io_module, command_args, args):
        # Remove everyone listed from the ignore list
        # eg !unignore tom dick harry
        msg = ""
        for word in command_args:
            try:
                self.settings.censored.remove(word.lower())
                msg = "done"
            except ValueError:
                pass
        return msg


class Pyborg(object):

    ver_string = "I am a version 1.1.2 PyBorg"

    # Main command list
    commandlist = "Pyborg commands:\n!checkdict, !contexts, !help, !known, !learning, !rebuilddict, \
!replace, !unlearn, !purge, !version, !words, !limit, !alias, !save, !censor, !uncensor, !owner"
    commanddict = {
        "help": "Owner command. Usage: !help [command]\nPrints information about using a command, or a list of commands if no command is given",
        "version": "Usage: !version\nDisplay what version of Pyborg we are running",
        "words": "Usage: !words\nDisplay how many words are known",
        "known": "Usage: !known word1 [word2 [...]]\nDisplays if one or more words are known, and how many contexts are known",
        "contexts": "Owner command. Usage: !contexts <phrase>\nPrint contexts containing <phrase>",
        "unlearn": "Owner command. Usage: !unlearn <expression>\nRemove all occurances of a word or expression from the dictionary. For example '!unlearn of of' would remove all contexts containing double 'of's",
        "purge": "Owner command. Usage: !purge [number]\nRemove all occurances of the words that appears in less than <number> contexts",
        "replace": "Owner command. Usage: !replace <old> <new>\nReplace all occurances of word <old> in the dictionary with <new>",
        "learning": "Owner command. Usage: !learning [on|off]\nToggle bot learning. Without arguments shows the current setting",
        "checkdict": "Owner command. Usage: !checkdict\nChecks the dictionary for broken links. Shouldn't happen, but worth trying if you get KeyError crashes",
        "rebuilddict": "Owner command. Usage: !rebuilddict\nRebuilds dictionary links from the lines of known text. Takes a while. You probably don't need to do it unless your dictionary is very screwed",
        "censor": "Owner command. Usage: !censor [word1 [...]]\nPrevent the bot using one or more words. Without arguments lists the currently censored words",
        "uncensor": "Owner command. Usage: !uncensor word1 [word2 [...]]\nRemove censorship on one or more words",
        "limit": "Owner command. Usage: !limit [number]\nSet the number of words that pyBorg can learn",
        "alias": "Owner command. Usage: !alias : Show the differents aliases\n!alias <alias> : show the words attached to this alias\n!alias <alias> <word> : link the word to the alias",
        "owner": "Usage : !owner password\nAdd the user in the owner list"
    }

    log = logging.getLogger('Pyborg')

    def __init__(self):
        """
        Open the dictionary. Resize as required.
        """
        self.settings = Settings({
            'aliases': Setting("A list of similar words", {}),
            'censored': Setting("Words that indicate not to learn the sentences in which they appear", []),
            'ignore_list': Setting("Words to ignore for the answer", ['!.', '?.', "'", ',', ';']),
            'learning': Setting("If True, the bot will learn new words", True),
            'max_words': Setting("Max number of words to learn", 6000),
            'max_word_length': Setting("Max number of characters a word can have to learn it", 13),
            'min_vowel_ratio': Setting("Min ratio of vowels to characters a word can have to learn it", 0.25),
            'no_save': Setting("If True, don't overwrite the dictionary and configuration on disk", False),
            'num_aliases': Setting("Total known aliases", 0),
            'num_contexts': Setting("Total word contexts", 0),
            'num_words': Setting("Total known unique words", 0),
            'process_with': Setting("Which library to generate replies with ('pyborg' or 'megahal')", "pyborg"),
        })
        self.settings.load('pyborg.cfg')

        self.answers = Settings({
            'sentences': Setting("A list of prepared answers", {}),
        })
        self.answers.load('answers.txt')

        self.unfilterd = {}

        # Read the dictionary
        if self.settings.process_with == "pyborg":
            self.brain = PyborgBrain(self.settings)
        elif self.settings.process_with == "megahal":
            self.brain = MegahalBrain(self.settings)
        else:
            raise ValueError("Unknown 'process_with' value {0}".format(self.settings.process_with))

        self.settings.save()

    def save_all(self):
        if self.settings.no_save:
            return

        self.brain.save()

        sentence_list = sorted((sentence for sentence in self.unfilterd.iteritems()), key=lambda s: s[1])
        with open('sentences.txt', 'w') as sentence_file:
            for word, count in sentence_list:
                sentence_file.write(word)
                sentence_file.write('\n')

        self.settings.save()

    def process_msg(self, io_module, body, replyrate, learn, args, owner=False):
        """
        Process message 'body' and pass back to IO module with args.
        If owner, allow owner commands.
        """
        # add trailing space so sentences are broken up correctly
        body = body + " "

        # Parse commands
        if body.startswith('!'):
            self.do_commands(io_module, body, args, owner)
            return

        # Filter out garbage and do some formatting
        body = self.brain.filter_message(body)

        # Learn from input
        if learn == 1 and self.settings.learning:
            self.brain.learn(body)

        # Make a reply if desired
        if random.randint(0, 99) < replyrate:
            message = ""

            #Look if we can find a prepared answer
            for sentence in self.answers.sentences.keys():
                pattern = "^%s$" % sentence
                if re.search(pattern, body):
                    message = self.answers.sentences[sentence][random.randint(0, len(self.answers.sentences[sentence]) - 1)]
                    break
                else:
                    if body in self.unfilterd:
                        self.unfilterd[body] = self.unfilterd[body] + 1
                    else:
                        self.unfilterd[body] = 0

            if message == "":
                message = self.brain.reply(body)

            # single word reply: always output
            if len(message.split()) == 1:
                io_module.output(message, args)
                return
            # empty. do not output
            if message == "":
                return
            # else output
            if not owner:
                time.sleep(.2 * len(message))
            io_module.output(message, args)

    def do_commands(self, io_module, body, args, owner):
        """
        Respond to user comands.
        """
        command_list = body.split()
        command = command_list.pop(0).lstrip('!').lower()

        command_method = getattr(self, command, None)
        self.log.debug("What is command %r?", command)
        if command_method is None:
            self.log.debug("No such pyborg command %r. Is there a brain command %r?", command, command)
            command_method = getattr(self.brain, command, None)
        if command_method is None:
            self.log.debug("No such pyborg or brain command %r, doing nothing :(")
            return
        if not getattr(command_method, 'is_command', False):
            self.log.debug("Found requested method %r for command %r, but it's not a command, doing nothing :(",
                command_method, command)
            return
        if getattr(command_method, 'is_owner_command', False) and not owner:
            self.log.debug("Command %r is an owner command but requestor is not the owner, doing nothing :(", command)
            return

        self.log.debug("Yay, running command %r!", command)
        try:
            message = command_method(io_module, command_list, args)
        except Exception, exc:
            message = 'Oops, internal error :('
            self.log.exception()
        if message:
            io_module.output(message, args)

    @command
    def version(self, io_module, command_args, args):
        return self.ver_string

    @owner_command
    def save(self, io_module, command_args, args):
        self.save_all()
        return "Dictionary saved"

    @owner_command
    def help(self, io_module, command_args, args):
        if command_args:
            # Help for a specific command
            cmd = command_args[0].lower()
            dic = None
            if cmd in self.commanddict.keys():
                dic = self.commanddict
            elif cmd in io_module.commanddict.keys():
                dic = io_module.commanddict
            if dic:
                for i in dic[cmd].split("\n"):
                    io_module.output(i, args)
            else:
                return "No help on command '%s'" % cmd
        else:
            for i in self.commandlist.split("\n"):
                io_module.output( i, args )
            for i in io_module.commandlist.split("\n"):
                io_module.output( i, args )

    @owner_command
    def learning(self, io_module, command_args, args):
        msg = "Learning mode "
        if not command_args:
            if self.settings.learning == 0:
                msg += "off"
            else:
                msg += "on"
        else:
            toggle = command_args[0].lower()
            if toggle == "on":
                msg += "on"
                self.settings.learning = 1
            else:
                msg += "off"
                self.settings.learning = 0
        return msg

    @owner_command
    def quit(self, io_module, command_args, args):
        self.save_all()
        sys.exit()

    def reply(self, body):
        return self.brain.reply(body)

    def learn(self, body):
        return self.brain.learn(body)
