from distutils.core import setup

setup(
    name='pyborg',
    version='1.1.2',
    py_modules=['pyborg', 'cfgfile'],
    scripts=[
        'bin/pyborg-filein.py',
        'bin/pyborg-irc.py',
        'bin/pyborg-linein.py',
    ],
)
