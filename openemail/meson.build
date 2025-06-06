moduledir = pkgdatadir / 'openemail'

subdir('gtk')

gnome.compile_resources(
  'openemail',
  configure_file(
    input: 'openemail.gresource.xml.in',
    output: '@BASENAME@',
    configuration: conf,
  ),
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

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
    'dict_store.py',
    'mail.py',
    'main.py',
  ],
  install_dir: moduledir,
)

install_subdir('core', install_dir: moduledir)
install_subdir('widgets', install_dir: moduledir)
