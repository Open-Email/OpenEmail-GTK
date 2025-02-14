moduledir = pkgdatadir / 'openemail'

blueprints = custom_target('blueprints',
  input: files(
    'gtk/contacts-page.blp',
    'gtk/help-overlay.blp',
    'gtk/profile-page.blp',
    'gtk/window.blp',
  ),
  output: '.',
  command: [find_program('blueprint-compiler'), 'batch-compile',
            '@OUTPUT@', '@CURRENT_SOURCE_DIR@', '@INPUT@'],
)

gnome.compile_resources('openemail',
  configure_file(
    input:  'gresource.xml.in',
    output: 'gresource.xml',
    configuration: conf,
  ),
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)

configure_file(
  input:  'openemail.in',
  output: 'openemail',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'r-xr-xr-x'
)

openemail_sources = [
  '__init__.py',
  'client.py',
  'contacts_page.py',
  'main.py',
  'profile_page.py',
  'window.py',
  configure_file(
    input:  'shared.py.in',
    output: 'shared.py',
    configuration: conf
  ),
]

install_data(openemail_sources, install_dir: moduledir)
