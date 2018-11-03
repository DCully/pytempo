from distutils.core import setup

test_deps = [
    'numpy',
    'flake8',
    'scipy',
    'coverage',
]

extras={
    'test': test_deps,
}

setup(
    name='PyTempo',
    version='0.1.0',
    description='Causal tempo detection '
                'for 44100hz, 16-bit audio data streams',
    author='David Cully',
    author_email='david.a.cully@gmail.com',
    url='https://github.com/dcully/pytempo',
    packages=[
        'pytempo',
    ],
    tests_require=test_deps,
    extras_require=extras,
)
