blueprints = custom_target(
    input: files(
        'attachments.blp',
        'attachments-item.blp',
        'compose-sheet.blp',
        'contact-row.blp',
        'contacts.blp',
        'dialogs.blp',
        'login-view.blp',
        'message-row.blp',
        'message-view.blp',
        'messages.blp',
        'page.blp',
        'preferences.blp',
        'profile-settings.blp',
        'profile-view.blp',
        'shortcuts-dialog.blp',
        'thread-view.blp',
        'window.blp',
    ),
    output: '.',
    command: [
        find_program('blueprint-compiler'),
        'batch-compile',
        '--minify',
        '@OUTPUT@',
        '@CURRENT_SOURCE_DIR@',
        '@INPUT@',
    ],
)

gnome.compile_resources(
    'ui',
    configure_file(
        input: 'ui.gresource.xml.in',
        output: '@BASENAME@',
        configuration: conf,
    ),
    gresource_bundle: true,
    install: true,
    install_dir: pkgdatadir,
    dependencies: blueprints,
)
