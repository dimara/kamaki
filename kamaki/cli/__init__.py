#!/usr/bin/env python
# Copyright 2011-2012 GRNET S.A. All rights reserved.
#
# Redistribution and use in source and binary forms, with or
# without modification, are permitted provided that the following
# conditions are met:
#
#   1. Redistributions of source code must retain the above
#      copyright notice, this list of conditions and the following
#      disclaimer.
#
#   2. Redistributions in binary form must reproduce the above
#      copyright notice, this list of conditions and the following
#      disclaimer in the documentation and/or other materials
#      provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY GRNET S.A. ``AS IS'' AND ANY EXPRESS
# OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL GRNET S.A OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and
# documentation are those of the authors and should not be
# interpreted as representing official policies, either expressed
# or implied, of GRNET S.A.

from __future__ import print_function

import logging

from inspect import getargspec
from argparse import ArgumentParser, ArgumentError
from os.path import basename
from sys import exit, stdout, argv

from kamaki.cli.errors import CLIError, CLICmdSpecError
from kamaki.cli.utils import magenta, red, yellow, print_dict, print_list,\
    remove_colors
from kamaki.cli.command_tree import CommandTree
from kamaki.cli.argument import _arguments, parse_known_args
from kamaki.cli.history import History

cmd_spec_locations = [
    'kamaki.cli.commands',
    'kamaki.commands',
    'kamaki.cli',
    'kamaki',
    '']
_commands = CommandTree(name='kamaki',
    description='A command line tool for poking clouds')

# If empty, all commands are loaded, if not empty, only commands in this list
# e.g. [store, lele, list, lolo] is good to load store_list but not list_store
# First arg should always refer to a group
candidate_command_terms = []
allow_no_commands = False
allow_all_commands = False
allow_subclass_signatures = False


def _allow_class_in_cmd_tree(cls):
    global allow_all_commands
    if allow_all_commands:
        return True
    global allow_no_commands
    if allow_no_commands:
        return False

    term_list = cls.__name__.split('_')
    global candidate_command_terms
    index = 0
    for term in candidate_command_terms:
        try:
            index += 1 if term_list[index] == term else 0
        except IndexError:  # Whole term list matched!
            return True
    if allow_subclass_signatures:
        if index == len(candidate_command_terms) and len(term_list) > index:
            try:  # is subterm already in _commands?
                _commands.get_command('_'.join(term_list[:index + 1]))
            except KeyError:  # No, so it must be placed there
                return True
        return False

    return True if index == len(term_list) else False


def command():
    """Class decorator that registers a class as a CLI command"""

    def decorator(cls):
        """Any class with name of the form cmd1_cmd2_cmd3_... is accepted"""

        if not _allow_class_in_cmd_tree(cls):
            return cls

        cls.description, sep, cls.long_description\
            = cls.__doc__.partition('\n')

        # Generate a syntax string based on main's arguments
        spec = getargspec(cls.main.im_func)
        args = spec.args[1:]
        n = len(args) - len(spec.defaults or ())
        required = ' '.join('<%s>' % x\
            .replace('____', '[:')\
            .replace('___', ':')\
            .replace('__', ']').\
            replace('_', ' ') for x in args[:n])
        optional = ' '.join('[%s]' % x\
            .replace('____', '[:')\
            .replace('___', ':')\
            .replace('__', ']').\
            replace('_', ' ') for x in args[n:])
        cls.syntax = ' '.join(x for x in [required, optional] if x)
        if spec.varargs:
            cls.syntax += ' <%s ...>' % spec.varargs

        # store each term, one by one, first
        _commands.add_command(cls.__name__, cls.description, cls)

        return cls
    return decorator


def _update_parser(parser, arguments):
    for name, argument in arguments.items():
        try:
            argument.update_parser(parser, name)
        except ArgumentError:
            pass


def _init_parser(exe):
    parser = ArgumentParser(add_help=False)
    parser.prog = '%s <cmd_group> [<cmd_subbroup> ...] <cmd>' % exe
    _update_parser(parser, _arguments)
    return parser


def _print_error_message(cli_err):
    errmsg = '%s' % cli_err
    if cli_err.importance == 1:
        errmsg = magenta(errmsg)
    elif cli_err.importance == 2:
        errmsg = yellow(errmsg)
    elif cli_err.importance > 2:
        errmsg = red(errmsg)
    stdout.write(errmsg)
    print_list(cli_err.details)


def get_command_group(unparsed):
    groups = _arguments['config'].get_groups()
    for grp_candidate in unparsed:
        if grp_candidate in groups:
            unparsed.remove(grp_candidate)
            return grp_candidate
    return None


def load_command(group, unparsed, reload_package=False):
    global candidate_command_terms
    candidate_command_terms = [group] + unparsed
    load_group_package(group, reload_package)

    #From all possible parsed commands, chose the first match in user string
    final_cmd = _commands.get_command(group)
    for term in unparsed:
        cmd = final_cmd.get_subcmd(term)
        if cmd is not None:
            final_cmd = cmd
            unparsed.remove(cmd.name)
    return final_cmd


def shallow_load():
    """Load only group names and descriptions"""
    global allow_no_commands
    allow_no_commands = True  # load only descriptions
    for grp in _arguments['config'].get_groups():
        load_group_package(grp)
    allow_no_commands = False


def load_group_package(group, reload_package=False):
    spec_pkg = _arguments['config'].value.get(group, 'cli')
    if spec_pkg is None:
        return None
    for location in cmd_spec_locations:
        location += spec_pkg if location == '' else ('.' + spec_pkg)
        try:
            package = __import__(location, fromlist=['API_DESCRIPTION'])
        except ImportError:
            continue
        if reload_package:
            reload(package)
        for grp, descr in package.API_DESCRIPTION.items():
            _commands.add_command(grp, descr)
        return package
    raise CLICmdSpecError(details='Cmd Spec Package %s load failed' % spec_pkg)


def print_commands(prefix=None, full_depth=False):
    cmd_list = _commands.get_groups() if prefix is None\
        else _commands.get_subcommands(prefix)
    cmds = {}
    for subcmd in cmd_list:
        if subcmd.sublen() > 0:
            sublen_str = '( %s more terms ... )' % subcmd.sublen()
            cmds[subcmd.name] = [subcmd.help, sublen_str]\
                if subcmd.has_description else sublen_str
        else:
            cmds[subcmd.name] = subcmd.help
    if len(cmds) > 0:
        print('\nOptions:')
        print_dict(cmds, ident=12)
    if full_depth:
        _commands.pretty_print()


def setup_logging(silent=False, debug=False, verbose=False, include=False):
    """handle logging for clients package"""

    def add_handler(name, level, prefix=''):
        h = logging.StreamHandler()
        fmt = logging.Formatter(prefix + '%(message)s')
        h.setFormatter(fmt)
        logger = logging.getLogger(name)
        logger.addHandler(h)
        logger.setLevel(level)

    if silent:
        add_handler('', logging.CRITICAL)
    elif debug:
        add_handler('requests', logging.INFO, prefix='* ')
        add_handler('clients.send', logging.DEBUG, prefix='> ')
        add_handler('clients.recv', logging.DEBUG, prefix='< ')
    elif verbose:
        add_handler('requests', logging.INFO, prefix='* ')
        add_handler('clients.send', logging.INFO, prefix='> ')
        add_handler('clients.recv', logging.INFO, prefix='< ')
    elif include:
        add_handler('clients.recv', logging.INFO)
    else:
        add_handler('', logging.WARNING)


def _exec_cmd(instance, cmd_args, help_method):
    try:
        return instance.main(*cmd_args)
    except TypeError as err:
        if err.args and err.args[0].startswith('main()'):
            print(magenta('Syntax error'))
            if instance.get_argument('verbose'):
                print(unicode(err))
            help_method()
        else:
            raise
    except CLIError as err:
        if instance.get_argument('debug'):
            raise
        _print_error_message(err)
    return 1


def one_command():
    _debug = False
    _help = False
    _verbose = False
    try:
        exe = basename(argv[0])
        parser = _init_parser(exe)
        parsed, unparsed = parse_known_args(parser, _arguments)
        _colors = _arguments['config'].get('global', 'colors')
        if _colors != 'on':
            remove_colors()
        _history = History(_arguments['config'].get('history', 'file'))
        _history.add(' '.join([exe] + argv[1:]))
        _debug = _arguments['debug'].value
        _help = _arguments['help'].value
        _verbose = _arguments['verbose'].value
        if _arguments['version'].value:
            exit(0)

        group = get_command_group(unparsed)
        if group is None:
            parser.print_help()
            shallow_load()
            print_commands(full_depth=_debug)
            exit(0)

        cmd = load_command(group, unparsed)
        # Find the most specific subcommand
        for term in list(unparsed):
            if cmd.is_command:
                break
            if cmd.contains(term):
                cmd = cmd.get_subcmd(term)
                unparsed.remove(term)

        if _help or not cmd.is_command:
            if cmd.has_description:
                parser.description = cmd.help
            else:
                try:
                    parser.description =\
                        _commands.get_closest_ancestor_command(cmd.path).help
                except KeyError:
                    parser.description = ' '
            parser.prog = '%s %s ' % (exe, cmd.path.replace('_', ' '))
            if cmd.is_command:
                cli = cmd.get_class()
                parser.prog += cli.syntax
                _update_parser(parser, cli().arguments)
            else:
                parser.prog += '[...]'
            parser.print_help()

            # load one more level just to see what is missing
            global allow_subclass_signatures
            allow_subclass_signatures = True
            load_command(group, cmd.path.split('_')[1:], reload_package=True)

            print_commands(cmd.path, full_depth=_debug)
            exit(0)

        setup_logging(silent=_arguments['silent'].value,
            debug=_debug,
            verbose=_verbose,
            include=_arguments['include'].value)
        cli = cmd.get_class()
        executable = cli(_arguments)
        _update_parser(parser, executable.arguments)
        parser.prog = '%s %s %s'\
            % (exe, cmd.path.replace('_', ' '), cli.syntax)
        parsed, new_unparsed = parse_known_args(parser, _arguments)
        unparsed = [term for term in unparsed if term in new_unparsed]
        ret = _exec_cmd(executable, unparsed, parser.print_help)
        exit(ret)
    except CLIError as err:
        if _debug:
            raise
        _print_error_message(err)
        exit(1)

from command_shell import _fix_arguments, Shell


def _start_shell():
    shell = Shell()
    shell.set_prompt(basename(argv[0]))
    from kamaki import __version__ as version
    shell.greet(version)
    shell.do_EOF = shell.do_exit
    return shell


def run_shell():
    _fix_arguments()
    shell = _start_shell()
    _config = _arguments['config']
    _config.value = None
    for grp in _config.get_groups():
        global allow_all_commands
        allow_all_commands = True
        load_group_package(grp)
    setup_logging(silent=_arguments['silent'].value,
        debug=_arguments['debug'].value,
        verbose=_arguments['verbose'].value,
        include=_arguments['include'].value)
    shell.cmd_tree = _commands
    shell.run()


def main():

    if len(argv) <= 1:
        run_shell()
    else:
        one_command()
