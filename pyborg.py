# -*- coding: utf-8 -*-
#
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

from __future__ import division

from itertools import count, islice, izip
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

        self.num_words = len(self.words)
        self.num_contexts = sum(len(line[0].split()) for line in self.lines.itervalues())

        self.log.debug("Checking dictionary for new aliases...")
        for word in self.words.keys():
            if word.startswith('~'):
                if word not in self.settings.aliases:
                    self.log.debug("Unlearning alias %r", word)
                    self.unlearn_word(word)
            else:
                for alias_word, patterns in self.settings.aliases.iteritems():
                    for alias_pattern in patterns:
                        pattern = r'^%s$' % alias_pattern
                        if re.search(pattern, word):
                            self.log.debug("Discovered alias %r for word %r, replacing", alias_word, word)
                            self.replace_word(word, alias_word)

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
        if self.settings.protect:
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

        all_vowels = u'a\xe0\xe2e\xe9\xe8\xeai\xee\xefo\xf6\xf4u\xfc\xfby'

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
            contexts_per_word = self.num_contexts / self.num_words
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
            for i, word in enumerate(words):
                try:
                    word_contexts = self.words[word]
                except KeyError:
                    self.num_words += 1
                    word_contexts = self.words[word] = list()
                word_contexts.append(struct.pack("lH", hashval, i))
                self.num_contexts += 1

        # Stop learning when we know enough words.
        if self.num_words >= self.settings.max_words:
            self.log.info("STOP LEARNING: got %d words (max %d)", self.num_words, self.settings.max_words)
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
        # We need only search lines that contain the words in the context.
        context_words = context.split()
        if not context_words:
            self.log.debug("No words to unlearn!")
            return
        first_word = context_words[0]
        if first_word not in self.words:
            self.log.debug("Already unlearned all possible contexts for %r", first_word)
            return
        lines_to_search = (struct.unpack("lH", ctx)[0] for ctx in self.words[first_word])

        # Pad thing to look for
        # We pad so we don't match 'shit' when searching for 'hit', etc.
        context = " " + context + " "

        words_to_repair = set()
        for line_hash in lines_to_search:
            line_text, line_contexts = self.lines[line_hash]
            c = " " + line_text + " "
            if c.find(context) != -1:
                words_to_repair.update(line_text.split())
                del self.lines[line_hash]

        for word in words_to_repair:
            word_contexts = self.words[word]
            num_contexts = len(word_contexts)
            word_contexts = list(ctx for ctx in word_contexts if struct.unpack("lH", ctx)[0] in self.lines)
            self.num_contexts -= num_contexts - len(word_contexts)

            if word_contexts:
                self.words[word] = word_contexts
            else:
                del self.words[word]
                self.num_words -= 1
                self.log.info("Unlearned all contexts for word %r", word)

    def reply(self, body):
        """
        Reply to a line of text.
        """
        words = body.split()
        if not words:
            self.log.debug("No words to reply to, returning empty reply")
            return ''

        # Remove numbers and words on the ignore list.
        #words = filter((lambda x: x not in self.settings.ignore_list and not x.isdigit()), words)
        words = list(x for x in words if x not in self.settings.ignore_list and not x.isdigit())
        self.log.debug("Minus ignored words: %r", words)

        # Find the rarest words in the sentence that have at least 3 contexts.
        known_min = 3
        word_data = list((word, len(self.words.get(word, ()))) for word in words)
        self.log.debug("Seed words and context counts: %r", word_data)
        word_data = list((word, contexts) for word, contexts in word_data if contexts >= known_min)
        try:
            fewest_contexts = min(contexts for word, contexts in word_data)
        except ValueError:
            self.log.debug("No eligible seed words in %r, returning empty reply", body)
            return ''
        rarest_words = list(word for word, contexts in word_data if contexts == fewest_contexts)
        self.log.debug("Rarest words with %d contexts: %r", fewest_contexts, rarest_words)

        # Index now contains list of rarest known words in sentence
        word = random.choice(rarest_words)
        self.log.debug("Selected seed word: %r", word)

        def choose_words(sentence, reverse=False):
            search_direction = -1 if reverse else 1

            sentence = list(reversed(sentence)) if reverse else list(sentence)
            EOL = object()
            while True:
                # create a dictionary wich will contain all the words we can found before the "chosen" word
                candidate_words = { EOL: 0 }

                this_word = sentence[-1]
                self.log.debug("Examining candidates to follow word %r in %d contexts",
                    this_word, len(self.words[this_word]))
                for context in self.words[this_word]:
                    line_hash, word_index = struct.unpack("lH", context)
                    line, num_contexts = self.lines[line_hash]
                    line_words = line.split()

                    assert line_words[word_index] == this_word, 'Inconsistent context %r thought word %r was #%d' % (
                        line, this_word, word_index)

                    try:
                        cand_index = word_index + search_direction
                        if cand_index < 0:
                            raise IndexError
                        cand_word = line_words[cand_index]
                    except IndexError:
                        # The seed word is at the end of the line, so nominate the EOL.
                        self.log.debug("Found current word %r at the end of line %r, so nominating EOL", this_word, line)
                        candidate_words[EOL] += num_contexts
                        continue

                    # Don't nominate a word that's already in the sentence.
                    if cand_word in sentence:
                        self.log.debug("Skipping candidate word %r: already in the sentence", cand_word)
                        continue

                    # Does the *previous* word in the candidate word's sentence *also* match?
                    # That is, does the candidate word follow a run of *two* words in the sentence?
                    try:
                        following_line_index = word_index - search_direction
                        if following_line_index < 0:
                            raise IndexError
                        following_word_matches = sentence[-2] == line_words[following_line_index]
                    except IndexError:
                        # Either the seed sentence or the candidate line are too short to consider the next word, but that's okay.
                        self.log.debug("Couldn't determine if candidate word %r has a run-of-2, so benefitting its doubt",
                            cand_word)
                    else:
                        # If there *are* following words to compare at all, require they match.
                        if following_word_matches:
                            self.log.debug("Skipping candidate word %r: previous word is %r, but wanted %r",
                                cand_word, line_words[word_index - search_direction], sentence[-2])
                            continue

                    candidate_words[cand_word] = candidate_words.get(cand_word, 0) + num_contexts
                    self.log.debug("Yay, candidate word %r up to %d contexts!", cand_word, candidate_words[cand_word])

                self.log.debug("From seed word %r, discovered candidates: %r", this_word, candidate_words)

                # Randomly select an unused candidate word, weighted by number of contexts.
                total_contexts = sum(candidate_words.values())
                selection = random.randint(0, total_contexts)
                for cand_word, cand_contexts in candidate_words.iteritems():
                    selection -= cand_contexts
                    if selection <= 0:
                        break

                selected_word = cand_word
                if selected_word is EOL:
                    break

                sentence.append(cand_word)

            if reverse:
                return list(reversed(sentence))
            return sentence

        pre_words = choose_words([word], reverse=True)
        self.log.debug("Chose left reply: %r", pre_words)
        post_words = choose_words(pre_words[-2:])
        self.log.debug("Chose right reply from %r end of left: %r", pre_words[-2:], post_words)
        sentence = pre_words[:-2] + post_words
        self.log.debug("So sentence is %r!", sentence)

        # Clean up aliases.
        sentence = (word.lstrip('~') for word in sentence)

        result_sentence = ' '.join(sentence)

        punctuation_fixups = {
            " ' ": "'",
            ' ?': '?',
            ' !': '!',
            ' ,': ',',
        }
        for punct_from, punct_to in punctuation_fixups.iteritems():
            result_sentence = result_sentence.replace(punct_from, punct_to)

        return result_sentence

    def replace_word(self, old_word, new_word):
        """
        Replace all occuraces of 'old' in the dictionary with
        'new'. Nice for fixing learnt typos.
        """
        try:
            contexts = self.words[old_word]
        except KeyError:
            return old + " not known."
        changed = 0

        for context in contexts:
            line_hash, word_index = struct.unpack("lH", context)
            line_text, line_contexts = self.lines[line_hash]
            line_words = line_text.split()

            assert line_words[word_index] == old_word, 'Inconsistent context %r thought word %r was #%d' % (
                line_hash, old_word, word_index)

            line_words[word_index] = new_word
            line_text = " ".join(line_words)
            self.lines[line_hash][0] = line_text
            changed += 1

        if new_word in self.words:
            self.num_words -= 1
            self.words[new_word].extend(self.words[old_word])
        else:
            self.words[new_word] = self.words[old_word]
        del self.words[old_word]

        return "%d instances of %s replaced with %s" % (changed, old_word, new_word)

    def known_words(self):
        num_w = self.num_words
        num_c = self.num_contexts
        num_l = len(self.lines)
        if num_w != 0:
            num_cpw = num_c / float(num_w)  # contexts per word
        else:
            num_cpw = 0.0
        return "I know %d words (%d contexts, %.2f per word), %d lines." % (num_w, num_c, num_cpw, num_l)

    @command
    def known(self, io_module, command_args, args):
        if not command_args:
            return self.known_words()
        words = command_args

        msg = "Number of contexts: "
        for word in words:
            word = word.lower()
            if word in self.words:
                contexts = len(self.words[word])
                msg += word + "/%i " % contexts
            else:
                msg += word + "/unknown "
        msg = msg.replace("#nick", "$nick")
        return msg

    @owner_command
    def limit(self, io_module, command_args, args):
        if not command_args:
            return "The max limit is %d words." % self.settings.max_words
        self.settings.max_words = int(command_args[0].lower())
        return "Set the max word limit to %d words." % self.settings.max_words

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
                self.num_words -= 1
                print "\"%s\" vaped totally" % w

        return "Checked dictionary in %0.2fs. Fixed links: %d broken, %d bad." % \
            (time.time() - t, num_broken, num_bad)

    @owner_command
    def rebuilddict(self, io_module, command_args, args):
        # Rebuild the dictionary by discarding the word links and
        # re-parsing each line
        if not self.settings.learning:
            return "Not learning, so not rebuilding."

        t = time.time()

        old_lines = self.lines.values()
        old_num_words = self.num_words
        old_num_contexts = self.num_contexts

        self.words = {}
        self.lines = {}
        self.num_words = 0
        self.num_contexts = 0

        for line_text, line_contexts in old_lines:
            self.learn(line_text, line_contexts)

        return "Rebuilt dictionary in %0.2fs. Words %d (%+d), contexts %d (%+d)" % (
            time.time() - t, self.num_words, self.num_words - old_num_words,
            self.num_contexts, self.num_contexts - old_num_contexts)

    @owner_command
    def purge(self, io_module, command_args, args):
        # Remove rare words.
        t = time.time()

        def is_rare_word(word, contexts):
            if len(contexts) < 2:
                return True
            if word.isalnum() and not (word.isdigit() or word.isalpha()):
                return True
            return False

        rare_words = (word for word, contexts in self.words.iteritems() if is_rare_word(word, contexts))

        if not command_args:
            return "There are %d possible rare (and alphanumeric) words to remove." % len(list(rare_words))

        num_words_to_unlearn = int(command_args[0])
        words_to_unlearn = list(islice(rare_words, num_words_to_unlearn))
        for word in words_to_unlearn:
            self.unlearn_word(word)

        return "Unlearned %d rare words in %0.2fs." % (len(words_to_unlearn), time.time() - t)

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

        if not command_args:
            return
        context = ' '.join(command_args).lower()

        io_module.output("Contexts containing '%s':" % context, args)

        context = " " + context + " "
        lines = set()
        # Search through contexts
        # Would be nice not to have find *all* the contexts, but we want their number.
        for line_text, line_contexts in self.lines.itervalues():
            line_text = " " + line_text + " "
            if context in line_text:
                lines.add(line_text)

        # If there are only a few contexts, show them all.
        # ("1 skipped" would be silly so show 16 if there are 16.)
        if len(lines) <= 16:
            for line in lines:
                io_module.output(line, args)
            return

        # There may be a lot of contexts, so show only the "first" five and "last" ten.
        these_lines = list(islice(lines, 15))
        for line in these_lines[:5]:
            io_module.output(line, args)
        io_module.output('...(%d skipped)...' % len(lines) - 15, args)
        for line in these_lines[5:]:
            io_module.output(line, args)

    @owner_command
    def unlearn(self, io_module, command_args, args):
        if not command_args:
            return
        context = " ".join(command_args).lower()
        self.log.debug("Looking to unlearn %r", context)

        t = time.time()
        num_lines = len(self.lines)
        self.unlearn_word(context)
        unlearned = num_lines - len(self.lines)
        return "Unlearned %d contexts in %0.2fs." % (unlearned, time.time() - t)

    @owner_command
    def censor(self, io_module, command_args, args):
        if not command_args:
            if not self.settings.censored:
                return "No words are censored."
            return "I will not use the words: %s" % ", ".join(self.settings.censored)

        messages = list()
        for word in command_args:
            word = word.lower()
            if word in self.settings.censored:
                messages.append("%s is already censored." % word)
            else:
                self.settings.censored.append(word)
                self.unlearn_word(word)
                messages.append("Censored and unlearned %s." % word)
        return '\n'.join(messages)

    @owner_command
    def uncensor(self, io_module, command_args, args):
        # Remove everyone listed from the ignore list
        # eg !unignore tom dick harry
        messages = list()
        for word in command_args:
            word = word.lower()
            try:
                self.settings.censored.remove(word.lower())
                messages.append("Uncensored %s." % word)
            except ValueError:
                messages.append("%s was already not censored." % word)
        return '\n'.join(messages)


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
            'protect': Setting("If True, don't overwrite the dictionary and configuration on disk", False),
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
        if self.settings.protect:
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
            self.log.exception('Internal error dispatching command %r', body)
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
