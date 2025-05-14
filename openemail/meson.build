moduledir = pkgdatadir / 'openemail'

blueprints = custom_target('blueprints',
  input: files(
    'gtk/auth-view.blp',
    'gtk/compose-dialog.blp',
    'gtk/contact-row.blp',
    'gtk/contacts-page.blp',
    'gtk/content-page.blp',
    'gtk/content-view.blp',
    'gtk/help-overlay.blp',
    'gtk/navigation-row.blp',
    'gtk/message-row.blp',
    'gtk/message-view.blp',
    'gtk/preferences.blp',
    'gtk/profile-settings.blp',
    'gtk/profile-view.blp',
    'gtk/request-buttons.blp',
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
    configure_file(
      input:  '__init__.py.in',
      output: '__init__.py',
      configuration: conf
    ),
    'dict_store.py',
    'mail.py',
    'main.py',
  ],
  install_dir: moduledir
)

install_subdir('core', install_dir: moduledir)
install_subdir('widgets', install_dir: moduledir)