moduledir = pkgdatadir / 'openemail'

subdir('gtk')

configure_file(
  input: 'openemail.in',
  output: '@BASENAME@',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'r-xr-xr-x',
)

install_data(
  [
    configure_file(input: '__init__.py.in', output: '@BASENAME@', configuration: conf),
    'main.py',
  ],
  install_dir: moduledir,
)

install_subdir('core', install_dir: moduledir)
install_subdir('lib', install_dir: moduledir)
install_subdir('widgets', install_dir: moduledir)
