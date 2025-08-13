moduledir = py_installation.get_install_dir() / 'openemail'

subdir('gtk/ui')

init = configure_file(
    input: 'configuration.py.in',
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
        'configuration.py',
        'configuration.py.in',
        'meson.build',
    ],
)
