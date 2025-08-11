desktop_file = i18n.merge_file(
    input: configure_file(
        input: 'openemail.desktop.in',
        output: '@PLAINNAME@',
        configuration: conf,
    ),
    output: f'@app_id@.desktop',
    type: 'desktop',
    po_dir: '../po',
    install: true,
    install_dir: get_option('datadir') / 'applications',
)

desktop_utils = find_program('desktop-file-validate', required: false)
if desktop_utils.found()
    test('Validate desktop file', desktop_utils, args: [desktop_file])
endif

appstream_file = i18n.merge_file(
    input: configure_file(
        input: 'openemail.metainfo.xml.in',
        output: '@PLAINNAME@',
        configuration: conf,
    ),
    output: f'@app_id@.metainfo.xml',
    po_dir: '../po',
    install: true,
    install_dir: get_option('datadir') / 'metainfo',
)

appstreamcli = find_program('appstreamcli', required: false, disabler: true)
test(
    'Validate appstream file',
    appstreamcli,
    args: ['validate', '--no-net', '--explain', appstream_file],
)

install_data(
    configure_file(
        input: 'openemail.gschema.xml.in',
        output: f'@app_id@.gschema.xml',
        configuration: conf,
    ),
    install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

compile_schemas = find_program(
    'glib-compile-schemas',
    required: false,
    disabler: true,
)
test(
    'Validate schema file',
    compile_schemas,
    args: ['--strict', '--dry-run', meson.current_source_dir()],
)

configure_file(
    input: 'openemail.in',
    output: '@BASENAME@',
    configuration: conf,
    install_dir: bindir,
    install_mode: 'r-xr-xr-x',
)

configure_file(
    input: 'openemail.service.in',
    output: f'@app_id@.service',
    configuration: conf,
    install_dir: get_option('datadir') / 'dbus-1' / 'services',
)

gnome.compile_resources(
    'data',
    configure_file(
        input: 'data.gresource.xml.in',
        output: '@BASENAME@',
        configuration: conf,
    ),
    gresource_bundle: true,
    install: true,
    install_dir: pkgdatadir,
    dependencies: appstream_file,
)

subdir('icons')
