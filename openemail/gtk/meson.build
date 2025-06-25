blueprints = custom_target(
  'blueprints',
  input: files(
    'attachments.blp',
    'auth-view.blp',
    'compose-dialog.blp',
    'contact-row.blp',
    'contacts-page.blp',
    'content-page.blp',
    'content-view.blp',
    'help-overlay.blp',
    'message-row.blp',
    'message-view.blp',
    'messages-page.blp',
    'navigation-row.blp',
    'preferences.blp',
    'profile-settings.blp',
    'profile-view.blp',
    'window.blp',
  ),
  output: '.',
  command: [
    find_program('blueprint-compiler'),
    'batch-compile',
    '@OUTPUT@',
    '@CURRENT_SOURCE_DIR@',
    '@INPUT@',
  ],
)

gnome.compile_resources(
  'gtk',
  configure_file(
    input: 'gtk.gresource.xml.in',
    output: '@BASENAME@',
    configuration: conf,
  ),
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)
