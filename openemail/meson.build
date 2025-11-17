moduledir = py_installation.get_install_dir() / 'openemail'

subdir('gtk/ui')

configure_file(
    input: '_config.py.in',
    output: '@BASENAME@',
    configuration: conf,
    install_dir: moduledir,
)

install_subdir(
    '.',
    install_dir: moduledir,
    exclude_directories: ['gtk' /'ui'],
    exclude_files: [
        '__builtins__.pyi',
        '_config.py',
        '_config.py.in',
        'meson.build',
    ],
)
