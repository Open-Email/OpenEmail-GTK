blueprints = custom_target(
  input: files(
    'attachments.blp',
    'compose-dialog.blp',
    'contact-row.blp',
    'contacts.blp',
    'content.blp',
    'login-view.blp',
    'message-row.blp',
    'message-view.blp',
    'messages.blp',
    'navigation-row.blp',
    'page.blp',
    'preferences.blp',
    'profile-settings.blp',
    'profile.blp',
    'shortcuts-dialog.blp',
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
