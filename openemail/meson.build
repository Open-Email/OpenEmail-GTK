moduledir = pkgdatadir / 'openemail'

blueprints = custom_target('blueprints',
  input: files(
    'gtk/auth-view.blp',
    'gtk/messages-page.blp',
    'gtk/contact-row.blp',
    'gtk/contacts-page.blp',
    'gtk/content-page.blp',
    'gtk/content-view.blp',
    'gtk/help-overlay.blp',
    'gtk/navigation-row.blp',
    'gtk/message-row.blp',
    'gtk/message-view.blp',
    'gtk/preferences.blp',
    'gtk/profile-view.blp',
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
    'message.py',
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
    'gtk/messages_page.py',
    'gtk/contacts_page.py',
    'gtk/content_page.py',
    'gtk/content_view.py',
    'gtk/message_view.py',
    'gtk/navigation_row.py',
    'gtk/preferences.py',
    'gtk/profile_view.py',
    'gtk/window.py',
  ],
  install_dir: join_paths(moduledir, 'gtk')
)
