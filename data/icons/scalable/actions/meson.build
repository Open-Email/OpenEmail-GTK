gnome.compile_resources(
  'openemail-icons',
  configure_file(
    input: 'icons.gresource.xml.in',
    output: '@BASENAME@',
    configuration: conf,
  ),
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)
