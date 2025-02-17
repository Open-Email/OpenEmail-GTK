moduledir = pkgdatadir / 'openemail'

blueprints = custom_target('blueprints',
  input: files(
    'gtk/auth-view.blp',
    'gtk/contacts-page.blp',
    'gtk/content-view.blp',
    'gtk/help-overlay.blp',
    'gtk/preferences.blp',
    'gtk/profile-page.blp',
    'gtk/sidebar-item.blp',
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

install_data([
    '__init__.py',
    'crypto.py',
    'main.py',
    'network.py',
    'user.py',
    configure_file(
      input:  'shared.py.in',
      output: 'shared.py',
      configuration: conf
    ),
  ],
  install_dir: moduledir
)

install_data([
    'gtk/auth_view.py',
    'gtk/contacts_page.py',
    'gtk/content_view.py',
    'gtk/preferences.py',
    'gtk/profile_page.py',
    'gtk/sidebar_item.py',
    'gtk/window.py',
  ],
  install_dir: join_paths(moduledir, 'gtk')
)
