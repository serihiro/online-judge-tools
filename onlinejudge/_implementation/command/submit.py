# Python Version: 3.x
import pathlib
import re
import sys
import time
import webbrowser
from typing import *

import onlinejudge
import onlinejudge._implementation.download_history
import onlinejudge._implementation.logging as log
import onlinejudge._implementation.utils as utils
from onlinejudge.type import *

if TYPE_CHECKING:
    import argparse


def submit(args: 'argparse.Namespace') -> None:
    # guess url
    history = onlinejudge._implementation.download_history.DownloadHistory()
    if args.file.parent.resolve() == pathlib.Path.cwd():
        guessed_urls = history.get()
    else:
        log.warning('cannot guess URL since the given file is not in the current directory')
        guessed_urls = []
    if args.url is None:
        if len(guessed_urls) == 1:
            args.url = guessed_urls[0]
            log.info('guessed problem: %s', args.url)
        else:
            log.error('failed to guess the URL to submit')
            log.info('please manually specify URL as: $ oj submit URL FILE')
            sys.exit(1)

    # parse url
    problem = onlinejudge.dispatch.problem_from_url(args.url)
    if problem is None:
        sys.exit(1)

    # read code
    with args.file.open('rb') as fh:
        code = fh.read()  # type: bytes
    format_config = {
        'dos2unix': args.format_dos2unix or args.golf,
        'rstrip': args.format_dos2unix or args.golf,
    }
    code = format_code(code, **format_config)

    # report code
    log.info('code (%d byte):', len(code))
    log.emit(utils.make_pretty_large_file_content(code, limit=30, head=10, tail=10, bold=True))

    with utils.with_cookiejar(utils.new_session_with_our_user_agent(), path=args.cookie) as sess:
        # guess or select language ids
        language_dict = {language.id: language.name for language in problem.get_available_languages(session=sess)}  # type: Dict[LanguageId, str]
        matched_lang_ids = None  # type: Optional[List[str]]
        if args.language in language_dict:
            matched_lang_ids = [args.language]
        else:
            if args.guess:
                kwargs = {
                    'language_dict': language_dict,
                    'cxx_latest': args.guess_cxx_latest,
                    'cxx_compiler': args.guess_cxx_compiler,
                    'python_version': args.guess_python_version,
                    'python_interpreter': args.guess_python_interpreter,
                }
                matched_lang_ids = guess_lang_ids_of_file(args.file, code, **kwargs)
                if not matched_lang_ids:
                    log.info('failed to guess languages from the file name')
                    matched_lang_ids = list(language_dict.keys())
                if args.language is not None:
                    log.info('you can use `--no-guess` option if you want to do an unusual submission')
                    matched_lang_ids = select_ids_of_matched_languages(args.language.split(), matched_lang_ids, language_dict=language_dict)
            else:
                if args.language is None:
                    matched_lang_ids = None
                else:
                    matched_lang_ids = select_ids_of_matched_languages(args.language.split(), list(language_dict.keys()), language_dict=language_dict)

        # report selected language ids
        if matched_lang_ids is not None and len(matched_lang_ids) == 1:
            args.language = matched_lang_ids[0]
            log.info('chosen language: %s (%s)', args.language, language_dict[LanguageId(args.language)])
        else:
            if matched_lang_ids is None:
                log.error('language is unknown')
                log.info('supported languages are:')
            elif len(matched_lang_ids) == 0:
                log.error('no languages are matched')
                log.info('supported languages are:')
            else:
                log.error('Matched languages were not narrowed down to one.')
                log.info('You have to choose:')
            for lang_id in sorted(matched_lang_ids or language_dict.keys()):
                log.emit('%s (%s)', lang_id, language_dict[LanguageId(lang_id)])
            sys.exit(1)

        # confirm
        guessed_unmatch = ([problem.get_url()] != guessed_urls)
        if guessed_unmatch:
            samples_text = ('samples of "{}'.format('", "'.join(guessed_urls)) if guessed_urls else 'no samples')
            log.warning('the problem "%s" is specified to submit, but %s were downloaded in this directory. this may be mis-operation', problem.get_url(), samples_text)
        if args.wait:
            log.status('sleep(%.2f)', args.wait)
            time.sleep(args.wait)
        if not args.yes:
            if guessed_unmatch:
                problem_id = problem.get_url().rstrip('/').split('/')[-1].split('?')[-1]  # this is too ad-hoc
                key = problem_id[:3] + (problem_id[-1] if len(problem_id) >= 4 else '')
                sys.stdout.write('Are you sure? Please type "{}" '.format(key))
                sys.stdout.flush()
                c = sys.stdin.readline().rstrip()
                if c != key:
                    log.info('terminated.')
                    return
            else:
                sys.stdout.write('Are you sure? [y/N] ')
                sys.stdout.flush()
                c = sys.stdin.read(1)
                if c.lower() != 'y':
                    log.info('terminated.')
                    return

        # submit
        try:
            submission = problem.submit_code(code, language_id=LanguageId(args.language), session=sess)
        except NotLoggedInError:
            log.failure('login required')
            sys.exit(1)
        except SubmissionError:
            log.failure('submission failed')
            sys.exit(1)

        # show result
        if args.open:
            browser = webbrowser.get()
            log.status('open the submission page with browser')
            opened = browser.open_new_tab(submission.get_url())
            if not opened:
                log.failure('failed to open the url. please set the $BROWSER envvar')


def select_ids_of_matched_languages(words: List[str], lang_ids: List[str], language_dict, split: bool = False, remove: bool = False) -> List[str]:
    result = []
    for lang_id in lang_ids:
        desc = language_dict[lang_id].lower()
        if split:
            desc = desc.split()
        pred = all([word.lower() in desc for word in words])
        if remove:
            pred = not pred
        if pred:
            result.append(lang_id)
    return result


def is_cplusplus_description(description: str) -> bool:
    # Here, 'clang' is not used as intended. Think about strings like "C++ (Clang)", "Clang++" (this includes "g++" as a substring), or "C (Clang)".
    return 'c++' in description.lower() or 'g++' in description.lower()


def parse_cplusplus_compiler(description: str) -> str:
    """
    :param description: must be for C++
    """

    assert is_cplusplus_description(description)
    if 'clang' in description.lower():
        return 'clang'
    if 'gcc' in description.lower() or 'g++' in description.lower():
        return 'gcc'
    return 'gcc'  # by default


def parse_cplusplus_version(description: str) -> Optional[str]:
    """
    :param description: must be for C++
    """

    assert is_cplusplus_description(description)
    match = re.search(r'[CG]\+\+\s?(\d\w)\b', description)
    if match:
        return match.group(1)
    return None


def is_python_description(description: str) -> bool:
    return 'python' in description.lower() or 'pypy' in description.lower()


def parse_python_version(description: str) -> Optional[int]:
    """
    :param description: must be for Python
    """

    assert is_python_description(description)
    match = re.match(r'([23])\.(?:\d+(?:\.\d+)?|x)', description)
    if match:
        return int(match.group(1))
    match = re.match(r'(?:Python|PyPy) *\(?([23])', description, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def parse_python_interpreter(description: str) -> str:
    """
    :param description: must be for Python
    """

    assert is_python_description(description)
    if 'pypy' in description.lower():
        return 'pypy'
    else:
        return 'cpython'


def guess_lang_ids_of_file(filename: pathlib.Path, code: bytes, language_dict, cxx_latest: bool = False, cxx_compiler: str = 'all', python_version: str = 'all', python_interpreter: str = 'all') -> List[str]:
    assert cxx_compiler in ('gcc', 'clang', 'all')
    assert python_version in ('2', '3', 'auto', 'all')
    assert python_interpreter in ('cpython', 'pypy', 'all')

    ext = filename.suffix
    lang_ids = language_dict.keys()

    log.debug('file extension: %s', ext)
    ext = ext.lstrip('.')

    if ext in ('cpp', 'cxx', 'cc', 'C'):
        log.debug('language guessing: C++')
        # memo: https://stackoverflow.com/questions/1545080/c-code-file-extension-cc-vs-cpp
        lang_ids = list(filter(lambda lang_id: is_cplusplus_description(language_dict[lang_id]), lang_ids))
        if not lang_ids:
            return []
        log.debug('all lang ids for C++: %s', lang_ids)

        # compiler
        found_gcc = False
        found_clang = False
        for lang_id in lang_ids:
            compiler = parse_cplusplus_compiler(language_dict[lang_id])
            if compiler == 'gcc':
                found_gcc = True
            elif compiler == 'clang':
                found_clang = True
        if found_gcc and found_clang:
            log.status('both GCC and Clang are available for C++ compiler')
            if cxx_compiler == 'gcc':
                log.status('use: GCC')
                lang_ids = list(filter(lambda lang_id: parse_cplusplus_compiler(language_dict[lang_id]) in ('gcc', None), lang_ids))
            elif cxx_compiler == 'clang':
                log.status('use: Clang')
                lang_ids = list(filter(lambda lang_id: parse_cplusplus_compiler(language_dict[lang_id]) in ('clang', None), lang_ids))
            else:
                assert cxx_compiler == 'all'
        log.debug('lang ids after compiler filter: %s', lang_ids)

        # version
        if cxx_latest:
            saved_lang_ids = lang_ids
            lang_ids = []
            for compiler in ('gcc', 'clang'):  # use the latest for each compiler
                ids = list(filter(lambda lang_id: parse_cplusplus_compiler(language_dict[lang_id]) in (compiler, None), saved_lang_ids))
                if not ids:
                    continue
                ids.sort(key=lambda lang_id: (parse_cplusplus_version(language_dict[lang_id]) or '', language_dict[lang_id]))
                lang_ids += [ids[-1]]  # since C++11 < C++1y < ... as strings
        log.debug('lang ids after version filter: %s', lang_ids)

        assert lang_ids
        lang_ids = sorted(set(lang_ids))
        return lang_ids

    elif ext == 'py':
        log.debug('language guessing: Python')

        # interpreter
        lang_ids = list(filter(lambda lang_id: is_python_description(language_dict[lang_id]), lang_ids))
        if any([parse_python_interpreter(language_dict[lang_id]) == 'pypy' for lang_id in lang_ids]):
            log.status('PyPy is available for Python interpreter')
        if python_interpreter != 'all':
            lang_ids = list(filter(lambda lang_id: parse_python_interpreter(language_dict[lang_id]) == python_interpreter, lang_ids))

        # version
        three_found = False
        two_found = False
        for lang_id in lang_ids:
            version = parse_python_version(language_dict[lang_id])
            log.debug('%s (%s) is recognized as Python %s', lang_id, language_dict[lang_id], str(version or 'unknown'))
            if version == 3:
                three_found = True
            if version == 2:
                two_found = True
        if two_found and three_found:
            log.status('both Python2 and Python3 are available for version of Python')
            if python_version in ('2', '3'):
                versions = [int(python_version)]  # type: List[Optional[int]]
            elif python_version == 'all':
                versions = [2, 3]
            else:
                assert python_version == 'auto'
                lines = code.splitlines()
                if code.startswith(b'#!'):
                    s = lines[0]  # use shebang
                else:
                    s = b'\n'.join(lines[:10] + lines[-5:])  # use modelines
                versions = []
                for version in (2, 3):
                    if re.search(r'python *(version:? *)?%d'.encode() % version, s.lower()):
                        versions += [version]
                if not versions:
                    log.status('no version info in code')
                    versions = [3]
            log.status('use: %s', ', '.join(map(str, versions)))
            lang_ids = list(filter(lambda lang_id: parse_python_version(language_dict[lang_id]) in versions + [None], lang_ids))

        lang_ids = sorted(set(lang_ids))
        return lang_ids

    else:
        log.debug('language guessing: others')
        table = [
             { 'names': [ 'awk'                   ], 'exts': [ 'awk'       ] },
             { 'names': [ 'bash'                  ], 'exts': [ 'sh'        ] },
             { 'names': [ 'brainfuck'             ], 'exts': [ 'bf'        ] },
             { 'names': [ 'c#'                    ], 'exts': [ 'cs'        ] },
             { 'names': [ 'c'                     ], 'exts': [ 'c'         ], 'split': True },
             { 'names': [ 'ceylon'                ], 'exts': [ 'ceylon'    ] },
             { 'names': [ 'clojure'               ], 'exts': [ 'clj'       ] },
             { 'names': [ 'common lisp'           ], 'exts': [ 'lisp', 'lsp', 'cl' ] },
             { 'names': [ 'crystal'               ], 'exts': [ 'cr'        ] },
             { 'names': [ 'd'                     ], 'exts': [ 'd'         ], 'split': True },
             { 'names': [ 'f#'                    ], 'exts': [ 'fs'        ] },
             { 'names': [ 'fortran'               ], 'exts': [ 'for', 'f', 'f90', 'f95', 'f03' ] },
             { 'names': [ 'go'                    ], 'exts': [ 'go'        ], 'split': True },
             { 'names': [ 'haskell'               ], 'exts': [ 'hs'        ] },
             { 'names': [ 'java'                  ], 'exts': [ 'java'      ] },
             { 'names': [ 'javascript'            ], 'exts': [ 'js'        ] },
             { 'names': [ 'julia'                 ], 'exts': [ 'jl'        ] },
             { 'names': [ 'kotlin'                ], 'exts': [ 'kt', 'kts' ] },
             { 'names': [ 'lua'                   ], 'exts': [ 'lua'       ] },
             { 'names': [ 'nim'                   ], 'exts': [ 'nim'       ] },
             { 'names': [ 'moonscript'            ], 'exts': [ 'moon'      ] },
             { 'names': [ 'objective-c'           ], 'exts': [ 'm'         ] },
             { 'names': [ 'ocaml'                 ], 'exts': [ 'ml'        ] },
             { 'names': [ 'octave'                ], 'exts': [ 'm'         ] },
             { 'names': [ 'pascal'                ], 'exts': [ 'pas'       ] },
             { 'names': [ 'perl6'                 ], 'exts': [ 'p6', 'pl6', 'pm6' ] },
             { 'names': [ 'perl'                  ], 'exts': [ 'pl', 'pm'  ], 'split': True },
             { 'names': [ 'php'                   ], 'exts': [ 'php'       ] },
             { 'names': [ 'ruby'                  ], 'exts': [ 'rb'        ] },
             { 'names': [ 'rust'                  ], 'exts': [ 'rs'        ] },
             { 'names': [ 'scala'                 ], 'exts': [ 'scala'     ] },
             { 'names': [ 'scheme'                ], 'exts': [ 'scm'       ] },
             { 'names': [ 'sed'                   ], 'exts': [ 'sed'       ] },
             { 'names': [ 'standard ml'           ], 'exts': [ 'sml'       ] },
             { 'names': [ 'swift'                 ], 'exts': [ 'swift'     ] },
             { 'names': [ 'text'                  ], 'exts': [ 'txt'       ] },
             { 'names': [ 'typescript'            ], 'exts': [ 'ts'        ] },
             { 'names': [ 'unlambda'              ], 'exts': [ 'unl'       ] },
             { 'names': [ 'vim script'            ], 'exts': [ 'vim'       ] },
             { 'names': [ 'visual basic'          ], 'exts': [ 'vb'        ] },
        ]  # type: List[Dict[str, Any]]  # yapf: disable

        lang_ids = []
        for data in table:
            if ext in data['exts']:
                for name in data['names']:
                    lang_ids += select_ids_of_matched_languages([name], language_dict.keys(), language_dict=language_dict, split=data.get('split', False))
        return sorted(set(lang_ids))


def format_code(code: bytes, dos2unix: bool = False, rstrip: bool = False) -> bytes:
    if dos2unix:
        log.status('dos2unix...')
        code = code.replace(b'\r\n', b'\n')
    if rstrip:
        log.status('rstrip...')
        code = code.rstrip()
    return code
